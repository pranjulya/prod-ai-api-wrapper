import asyncio
from datetime import datetime, timedelta, timezone

from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import create_job, delete_job, job_key, update_job


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expiry = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        self.expiry[key] = ex

    async def delete(self, key):
        self.values.pop(key, None)


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
    assert redis.expiry[job_key(record.id)] == 60
    updated = record.model_copy(update={"status": JobStatus.IN_PROGRESS, "openai_response_id": "resp_123"})
    await update_job(redis, updated)
    assert '"status":"in_progress"' in redis.values[job_key(record.id)]
    assert '"openai_response_id":"resp_123"' in redis.values[job_key(record.id)]
    await delete_job(redis, record.id)
    assert job_key(record.id) not in redis.values
