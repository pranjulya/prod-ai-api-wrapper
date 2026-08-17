from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.schemas.jobs import BackgroundJobError, BackgroundJobResponse, JobRecord, JobStatus
from app.services.job_reconciliation import apply_job_transition, transition_from_provider


def record(status=JobStatus.IN_PROGRESS):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id="job_test",
        status=status,
        openai_response_id="resp_private",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        status_url="/v1/responses/job_test",
        correlation_id="corr-original",
    )


def provider(status, *, output_text=None):
    return SimpleNamespace(
        id="resp_private",
        status=status,
        model="gpt-5-mini",
        output_text=output_text,
        usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
    )


def test_background_error_is_typed_and_optional():
    failed = record(JobStatus.FAILED).model_copy(
        update={"error": BackgroundJobError(code="safe", message="Safe message.")}
    )
    public = BackgroundJobResponse.model_validate(failed, from_attributes=True)
    assert public.error.model_dump() == {"code": "safe", "message": "Safe message."}
    assert BackgroundJobResponse.model_validate(record(), from_attributes=True).error is None


def test_completed_provider_is_normalized_into_job():
    updated = transition_from_provider(record(), provider("completed", output_text="done"))
    assert updated is not None
    assert updated.status is JobStatus.COMPLETED
    assert updated.model == "gpt-5-mini"
    assert updated.output_text == "done"
    assert updated.usage.total_tokens == 6
    assert updated.correlation_id == "corr-original"


def test_provider_status_mapping_and_unknown_status():
    expected = {
        "queued": JobStatus.PENDING,
        "in_progress": JobStatus.IN_PROGRESS,
        "failed": JobStatus.FAILED,
        "cancelled": JobStatus.CANCELLED,
        "incomplete": JobStatus.INCOMPLETE,
    }
    for provider_status, local_status in expected.items():
        assert transition_from_provider(record(), provider(provider_status)).status is local_status
    assert transition_from_provider(record(), provider("future_status")) is None


def test_explicit_transition_supports_webhook_terminal_status():
    assert apply_job_transition(record(), JobStatus.FAILED).status is JobStatus.FAILED
