import hashlib
from datetime import datetime, timezone

from app.schemas.jobs import JobRecord


def job_key(job_id: str) -> str:
    return f"wrapper:job:{job_id}"


def remaining_ttl(record: JobRecord) -> int:
    return max(1, int((record.expires_at - datetime.now(timezone.utc)).total_seconds()))


def response_job_key(openai_response_id: str) -> str:
    digest = hashlib.sha256(openai_response_id.encode()).hexdigest()
    return f"wrapper:openai-response-job:{digest}"


async def create_job(redis, record: JobRecord, ttl_seconds: int) -> None:
    await redis.set(job_key(record.id), record.model_dump_json(), ex=ttl_seconds)


async def update_job(redis, record: JobRecord) -> None:
    await redis.set(job_key(record.id), record.model_dump_json(), ex=remaining_ttl(record))


async def update_job_with_response_id(redis, record: JobRecord) -> None:
    if record.openai_response_id is None:
        raise ValueError("OpenAI response ID is required")
    ttl = remaining_ttl(record)
    pipeline = redis.pipeline(transaction=True)
    pipeline.set(job_key(record.id), record.model_dump_json(), ex=ttl)
    pipeline.set(response_job_key(record.openai_response_id), record.id, ex=ttl)
    await pipeline.execute()


async def get_job(redis, job_id: str) -> JobRecord | None:
    value = await redis.get(job_key(job_id))
    return None if value is None else JobRecord.model_validate_json(value)


async def get_job_id_by_response_id(redis, openai_response_id: str) -> str | None:
    value = await redis.get(response_job_key(openai_response_id))
    if isinstance(value, bytes):
        return value.decode()
    return value


async def delete_job(redis, job_id: str) -> None:
    record = await get_job(redis, job_id)
    pipeline = redis.pipeline(transaction=True)
    pipeline.delete(job_key(job_id))
    if record is not None and record.openai_response_id is not None:
        pipeline.delete(response_job_key(record.openai_response_id))
    await pipeline.execute()
