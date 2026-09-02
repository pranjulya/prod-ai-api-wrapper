import hashlib
from enum import IntEnum, StrEnum

from app.schemas.jobs import JobRecord
from app.services.jobs import job_key, remaining_ttl
from app.services.retry import MAX_RETRY_DELAY_SECONDS

PROCESSED_EVENT_TTL_SECONDS = 259_200
RELEASE_EVENT_SCRIPT = """-- release-webhook-event
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call("DEL", KEYS[1])
"""
MARK_PROCESSED_SCRIPT = """-- mark-webhook-event-processed
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
redis.call("SET", KEYS[1], ARGV[2], "EX", tonumber(ARGV[3]))
return 1
"""
FINALIZE_EVENT_SCRIPT = """-- finalize-webhook-event
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
local current = redis.call("GET", KEYS[2])
if not current then return 0 end
local status = cjson.decode(current)["status"]
if status == "completed" or status == "failed" or status == "cancelled"
   or status == "incomplete" or status == "expired" then
    redis.call("SET", KEYS[1], ARGV[4], "EX", tonumber(ARGV[5]))
    return 2
end
redis.call("SET", KEYS[2], ARGV[2], "EX", tonumber(ARGV[3]))
redis.call("SET", KEYS[1], ARGV[4], "EX", tonumber(ARGV[5]))
return 1
"""


class EventClaim(StrEnum):
    ACQUIRED = "acquired"
    PROCESSING = "processing"
    PROCESSED = "processed"


class FinalizationResult(IntEnum):
    STALE = 0
    UPDATED = 1
    ALREADY_TERMINAL = 2


def event_key(event_id: str) -> str:
    digest = hashlib.sha256(event_id.encode()).hexdigest()
    return f"wrapper:webhook:event:{digest}"


def processing_ttl(openai_timeout_seconds: int) -> int:
    return max(60, 3 * openai_timeout_seconds + 2 * MAX_RETRY_DELAY_SECONDS + 10)


def _processing_value(owner_token: str) -> str:
    return f"processing:{owner_token}"


async def claim_event(redis, event_id: str, owner_token: str, ttl_seconds: int) -> EventClaim:
    key = event_key(event_id)
    if await redis.set(key, _processing_value(owner_token), nx=True, ex=ttl_seconds):
        return EventClaim.ACQUIRED
    value = await redis.get(key)
    if isinstance(value, bytes):
        value = value.decode()
    return EventClaim.PROCESSED if value == EventClaim.PROCESSED.value else EventClaim.PROCESSING


async def release_event(redis, event_id: str, owner_token: str) -> bool:
    result = await redis.eval(
        RELEASE_EVENT_SCRIPT,
        1,
        event_key(event_id),
        _processing_value(owner_token),
    )
    return bool(result)


async def mark_processed(redis, event_id: str, owner_token: str) -> bool:
    result = await redis.eval(
        MARK_PROCESSED_SCRIPT,
        1,
        event_key(event_id),
        _processing_value(owner_token),
        EventClaim.PROCESSED.value,
        PROCESSED_EVENT_TTL_SECONDS,
    )
    return bool(result)


async def finalize_event(
    redis,
    event_id: str,
    owner_token: str,
    record: JobRecord,
) -> FinalizationResult:
    result = await redis.eval(
        FINALIZE_EVENT_SCRIPT,
        2,
        event_key(event_id),
        job_key(record.id),
        _processing_value(owner_token),
        record.model_dump_json(),
        remaining_ttl(record),
        EventClaim.PROCESSED.value,
        PROCESSED_EVENT_TTL_SECONDS,
    )
    return FinalizationResult(result)
