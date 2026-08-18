import asyncio
from datetime import datetime, timedelta, timezone

from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import job_key
from app.services.job_reconciliation import JobWriteResult, write_reconciled_job
from app.services.webhooks import (
    PROCESSED_EVENT_TTL_SECONDS,
    EventClaim,
    FinalizationResult,
    claim_event,
    event_key,
    finalize_event,
    mark_processed,
    processing_ttl,
    release_event,
)
from conftest import FakeRedis


def record(status):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id="job_webhook",
        status=status,
        openai_response_id="resp_webhook",
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status_url="/v1/responses/job_webhook",
        correlation_id="corr",
    )


def test_event_claim_distinguishes_owner_processing_and_processed():
    redis = FakeRedis()

    assert asyncio.run(claim_event(redis, "evt_private", "owner-a", 100)) is EventClaim.ACQUIRED
    assert asyncio.run(claim_event(redis, "evt_private", "owner-b", 100)) is EventClaim.PROCESSING
    redis.values[event_key("evt_private")] = "processed"
    assert asyncio.run(claim_event(redis, "evt_private", "owner-c", 100)) is EventClaim.PROCESSED
    assert "evt_private" not in event_key("evt_private")


def test_failed_claim_can_be_released():
    redis = FakeRedis()

    assert asyncio.run(claim_event(redis, "evt_retry", "owner-a", 100)) is EventClaim.ACQUIRED
    assert asyncio.run(release_event(redis, "evt_retry", "owner-a")) is True

    assert asyncio.run(claim_event(redis, "evt_retry", "owner-b", 100)) is EventClaim.ACQUIRED


def test_stale_owner_cannot_release_mark_or_finalize_new_claim():
    redis = FakeRedis()
    active = record(JobStatus.IN_PROGRESS)
    redis.values[job_key(active.id)] = active.model_dump_json()
    assert asyncio.run(claim_event(redis, "evt_retry", "owner-a", 100)) is EventClaim.ACQUIRED
    redis.values.pop(event_key("evt_retry"))
    assert asyncio.run(claim_event(redis, "evt_retry", "owner-b", 100)) is EventClaim.ACQUIRED

    assert asyncio.run(release_event(redis, "evt_retry", "owner-a")) is False
    assert asyncio.run(mark_processed(redis, "evt_retry", "owner-a")) is False
    assert asyncio.run(
        finalize_event(
            redis,
            "evt_retry",
            "owner-a",
            active.model_copy(update={"status": JobStatus.FAILED}),
        )
    ) is FinalizationResult.STALE

    assert redis.values[event_key("evt_retry")] == "processing:owner-b"
    assert JobRecord.model_validate_json(redis.values[job_key(active.id)]).status is JobStatus.IN_PROGRESS


def test_finalization_updates_job_and_event_atomically():
    redis = FakeRedis()
    active = record(JobStatus.IN_PROGRESS)
    completed = record(JobStatus.COMPLETED)
    redis.values[job_key(active.id)] = active.model_dump_json()
    redis.values[event_key("evt_done")] = "processing:owner-a"

    assert (
        asyncio.run(finalize_event(redis, "evt_done", "owner-a", completed))
        is FinalizationResult.UPDATED
    )

    assert redis.values[event_key("evt_done")] == "processed"
    assert redis.expirations[event_key("evt_done")] == PROCESSED_EVENT_TTL_SECONDS
    assert redis.values[job_key(completed.id)] == completed.model_dump_json()


def test_first_terminal_finalization_wins_across_different_events():
    redis = FakeRedis()
    active = record(JobStatus.IN_PROGRESS)
    redis.values[job_key(active.id)] = active.model_dump_json()
    redis.values[event_key("evt_failed")] = "processing:owner-a"
    redis.values[event_key("evt_completed")] = "processing:owner-b"

    assert asyncio.run(
        finalize_event(
            redis,
            "evt_failed",
            "owner-a",
            active.model_copy(update={"status": JobStatus.FAILED}),
        )
    ) is FinalizationResult.UPDATED
    assert asyncio.run(
        finalize_event(
            redis,
            "evt_completed",
            "owner-b",
            active.model_copy(update={"status": JobStatus.COMPLETED, "output_text": "late"}),
        )
    ) is FinalizationResult.ALREADY_TERMINAL

    stored = JobRecord.model_validate_json(redis.values[job_key(active.id)])
    assert stored.status is JobStatus.FAILED
    assert stored.output_text is None
    assert redis.values[event_key("evt_completed")] == "processed"


def test_poll_and_webhook_finalizers_keep_first_terminal_state():
    for poll_first in (True, False):
        redis = FakeRedis()
        active = record(JobStatus.IN_PROGRESS)
        redis.values[job_key(active.id)] = active.model_dump_json()
        redis.values[event_key("evt-race")] = "processing:webhook-owner"
        polled = active.model_copy(update={"status": JobStatus.FAILED})
        webhook = active.model_copy(update={"status": JobStatus.COMPLETED, "output_text": "done"})

        if poll_first:
            assert asyncio.run(write_reconciled_job(redis, polled)) is JobWriteResult.UPDATED
            assert (
                asyncio.run(finalize_event(redis, "evt-race", "webhook-owner", webhook))
                is FinalizationResult.ALREADY_TERMINAL
            )
            expected = JobStatus.FAILED
        else:
            assert (
                asyncio.run(finalize_event(redis, "evt-race", "webhook-owner", webhook))
                is FinalizationResult.UPDATED
            )
            assert asyncio.run(write_reconciled_job(redis, polled)) is JobWriteResult.ALREADY_TERMINAL
            expected = JobStatus.COMPLETED

        assert JobRecord.model_validate_json(redis.values[job_key(active.id)]).status is expected


def test_processing_ttl_covers_all_provider_attempts():
    assert processing_ttl(30) == 100
    assert processing_ttl(5) == 60
