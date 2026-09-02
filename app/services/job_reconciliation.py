import hashlib
from enum import IntEnum

from app.schemas.jobs import BackgroundJobError, JobRecord, JobStatus
from app.services.jobs import job_key, remaining_ttl
from app.services.responses import normalize_response

TERMINAL_STATUSES = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.INCOMPLETE,
        JobStatus.EXPIRED,
    }
)
PROVIDER_STATUSES = {
    "queued": JobStatus.PENDING,
    "in_progress": JobStatus.IN_PROGRESS,
    "completed": JobStatus.COMPLETED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
    "incomplete": JobStatus.INCOMPLETE,
}
RECONCILIATION_COOLDOWN_SECONDS = 5
FINISH_RECONCILIATION_SCRIPT = """-- finish-job-reconciliation
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
redis.call("SET", KEYS[1], ARGV[2], "EX", tonumber(ARGV[3]))
return 1
"""
WRITE_RECONCILED_JOB_SCRIPT = """-- write-reconciled-job
local current = redis.call("GET", KEYS[1])
if not current then return 0 end
local status = cjson.decode(current)["status"]
if status == "completed" or status == "failed" or status == "cancelled"
   or status == "incomplete" or status == "expired" then return 2 end
redis.call("SET", KEYS[1], ARGV[1], "EX", tonumber(ARGV[2]))
return 1
"""


class JobWriteResult(IntEnum):
    MISSING = 0
    UPDATED = 1
    ALREADY_TERMINAL = 2


def reconciliation_key(job_id: str) -> str:
    digest = hashlib.sha256(job_id.encode()).hexdigest()
    return f"wrapper:job-reconciliation:{digest}"


def _processing_value(owner_token: str) -> str:
    return f"processing:{owner_token}"


async def claim_reconciliation(redis, job_id: str, owner_token: str, ttl_seconds: int) -> bool:
    return bool(
        await redis.set(
            reconciliation_key(job_id),
            _processing_value(owner_token),
            nx=True,
            ex=ttl_seconds,
        )
    )


async def finish_reconciliation(redis, job_id: str, owner_token: str) -> bool:
    result = await redis.eval(
        FINISH_RECONCILIATION_SCRIPT,
        1,
        reconciliation_key(job_id),
        _processing_value(owner_token),
        "cooldown",
        RECONCILIATION_COOLDOWN_SECONDS,
    )
    return bool(result)


async def write_reconciled_job(redis, record: JobRecord) -> JobWriteResult:
    result = await redis.eval(
        WRITE_RECONCILED_JOB_SCRIPT,
        1,
        job_key(record.id),
        record.model_dump_json(),
        remaining_ttl(record),
    )
    return JobWriteResult(result)


def apply_job_transition(
    record: JobRecord,
    status: JobStatus,
    *,
    provider=None,
    error: BackgroundJobError | None = None,
) -> JobRecord:
    updates = {"status": status, "error": error}
    if status is JobStatus.COMPLETED:
        if provider is None or getattr(provider, "status", None) != "completed":
            raise ValueError("Completed transition requires a completed provider response")
        normalized = normalize_response(provider, record.correlation_id)
        updates.update(
            model=normalized.model,
            output_text=normalized.output_text,
            usage=normalized.usage,
        )
    return record.model_copy(update=updates)


def transition_from_provider(record: JobRecord, provider) -> JobRecord | None:
    status = PROVIDER_STATUSES.get(getattr(provider, "status", None))
    if status is None:
        return None
    return apply_job_transition(record, status, provider=provider if status is JobStatus.COMPLETED else None)
