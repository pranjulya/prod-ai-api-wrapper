from datetime import datetime, timezone

from app.schemas.jobs import JobRecord


def job_key(job_id: str) -> str:
    return f"wrapper:job:{job_id}"


async def create_job(redis, record: JobRecord, ttl_seconds: int) -> None:
    await redis.set(job_key(record.id), record.model_dump_json(), ex=ttl_seconds)


async def update_job(redis, record: JobRecord) -> None:
    remaining = max(1, int((record.expires_at - datetime.now(timezone.utc)).total_seconds()))
    await redis.set(job_key(record.id), record.model_dump_json(), ex=remaining)


async def get_job(redis, job_id: str) -> JobRecord | None:
    value = await redis.get(job_key(job_id))
    return None if value is None else JobRecord.model_validate_json(value)


async def delete_job(redis, job_id: str) -> None:
    await redis.delete(job_key(job_id))
