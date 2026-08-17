from app.schemas.jobs import BackgroundJobError, JobRecord, JobStatus
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
