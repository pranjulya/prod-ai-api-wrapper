import asyncio
from datetime import datetime, timedelta, timezone

from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import job_key
from app.services.webhooks import (
    PROCESSED_EVENT_TTL_SECONDS,
    EventClaim,
    claim_event,
    event_key,
    finalize_event,
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

    assert asyncio.run(claim_event(redis, "evt_private", 100)) is EventClaim.ACQUIRED
    assert asyncio.run(claim_event(redis, "evt_private", 100)) is EventClaim.PROCESSING
    redis.values[event_key("evt_private")] = "processed"
    assert asyncio.run(claim_event(redis, "evt_private", 100)) is EventClaim.PROCESSED
    assert "evt_private" not in event_key("evt_private")


def test_failed_claim_can_be_released():
    redis = FakeRedis()

    assert asyncio.run(claim_event(redis, "evt_retry", 100)) is EventClaim.ACQUIRED
    asyncio.run(release_event(redis, "evt_retry"))

    assert asyncio.run(claim_event(redis, "evt_retry", 100)) is EventClaim.ACQUIRED


def test_finalization_updates_job_and_event_atomically():
    redis = FakeRedis()
    completed = record(JobStatus.COMPLETED)

    asyncio.run(finalize_event(redis, "evt_done", completed))

    assert redis.pipeline_calls == 1
    assert redis.values[event_key("evt_done")] == "processed"
    assert redis.expirations[event_key("evt_done")] == PROCESSED_EVENT_TTL_SECONDS
    assert redis.values[job_key(completed.id)] == completed.model_dump_json()


def test_processing_ttl_covers_all_provider_attempts():
    assert processing_ttl(30) == 100
    assert processing_ttl(5) == 60
