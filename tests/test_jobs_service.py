import asyncio
from datetime import datetime, timedelta, timezone

from app.schemas.jobs import JobRecord, JobStatus
from app.services import jobs as jobs_service
from app.services.jobs import (
    create_job,
    delete_job,
    get_job,
    job_key,
    update_job,
)
from conftest import FakeRedis


def test_job_create_update_delete():
    asyncio.run(_exercise_job_storage())


async def _exercise_job_storage():
    redis = FakeRedis()
    now = datetime.now(timezone.utc)
    record = JobRecord(
        id="job_123",
        status=JobStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status_url="/v1/responses/job_123",
        correlation_id="corr",
    )
    await create_job(redis, record, 60)
    assert job_key(record.id) == "wrapper:job:job_123"
    assert redis.expirations[job_key(record.id)] == 60
    updated = record.model_copy(update={"status": JobStatus.IN_PROGRESS, "openai_response_id": "resp_123"})
    await update_job(redis, updated)
    assert '"status":"in_progress"' in redis.values[job_key(record.id)]
    assert '"openai_response_id":"resp_123"' in redis.values[job_key(record.id)]
    await jobs_service.update_job_with_response_id(redis, updated)
    pipelines_before_delete = redis.pipeline_calls
    await delete_job(redis, record.id)
    assert job_key(record.id) not in redis.values
    assert jobs_service.response_job_key("resp_123") not in redis.values
    assert redis.pipeline_calls == pipelines_before_delete + 1


def test_get_job_returns_record_without_writing():
    asyncio.run(_get_job_without_writing())


async def _get_job_without_writing():
    redis = FakeRedis()
    now = datetime.now(timezone.utc)
    record = JobRecord(
        id="job_123",
        status=JobStatus.COMPLETED,
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status_url="/v1/responses/job_123",
        correlation_id="corr",
    )
    redis.values[job_key(record.id)] = record.model_dump_json()
    assert await get_job(redis, record.id) == record
    assert await get_job(redis, "job_missing") is None


def test_response_reverse_index_is_atomic_hashed_and_expiring():
    redis = FakeRedis()
    now = datetime.now(timezone.utc)
    stored = JobRecord(
        id="job_reverse",
        status=JobStatus.IN_PROGRESS,
        openai_response_id="resp_private",
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status_url="/v1/responses/job_reverse",
        correlation_id="corr",
    )

    asyncio.run(jobs_service.update_job_with_response_id(redis, stored))

    assert redis.pipeline_calls == 1
    assert asyncio.run(jobs_service.get_job_id_by_response_id(redis, "resp_private")) == stored.id
    assert "resp_private" not in jobs_service.response_job_key("resp_private")
    assert redis.expirations[job_key(stored.id)] > 0
    assert redis.expirations[jobs_service.response_job_key("resp_private")] == redis.expirations[job_key(stored.id)]
