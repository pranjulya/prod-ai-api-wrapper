import hashlib
from enum import StrEnum

from app.schemas.jobs import JobRecord
from app.services.jobs import job_key, remaining_ttl


PROCESSED_EVENT_TTL_SECONDS = 259_200


class EventClaim(StrEnum):
    ACQUIRED = "acquired"
    PROCESSING = "processing"
    PROCESSED = "processed"


def event_key(event_id: str) -> str:
    digest = hashlib.sha256(event_id.encode()).hexdigest()
    return f"wrapper:webhook:event:{digest}"


def processing_ttl(openai_timeout_seconds: int) -> int:
    return max(60, 3 * openai_timeout_seconds + 10)


async def claim_event(redis, event_id: str, ttl_seconds: int) -> EventClaim:
    key = event_key(event_id)
    if await redis.set(key, EventClaim.PROCESSING.value, nx=True, ex=ttl_seconds):
        return EventClaim.ACQUIRED
    value = await redis.get(key)
    if isinstance(value, bytes):
        value = value.decode()
    return EventClaim.PROCESSED if value == EventClaim.PROCESSED.value else EventClaim.PROCESSING


async def release_event(redis, event_id: str) -> None:
    await redis.delete(event_key(event_id))


async def mark_processed(redis, event_id: str) -> None:
    await redis.set(
        event_key(event_id),
        EventClaim.PROCESSED.value,
        ex=PROCESSED_EVENT_TTL_SECONDS,
    )


async def finalize_event(redis, event_id: str, record: JobRecord) -> None:
    pipeline = redis.pipeline(transaction=True)
    pipeline.set(
        job_key(record.id),
        record.model_dump_json(),
        ex=remaining_ttl(record),
    )
    pipeline.set(
        event_key(event_id),
        EventClaim.PROCESSED.value,
        ex=PROCESSED_EVENT_TTL_SECONDS,
    )
    await pipeline.execute()
