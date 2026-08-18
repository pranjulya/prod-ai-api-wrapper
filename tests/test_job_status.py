import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
from redis.exceptions import ConnectionError

from app.main import create_app
from app.schemas.jobs import JobRecord, JobStatus
from app.schemas.responses import Usage
from app.services.job_reconciliation import claim_reconciliation
from app.services.jobs import job_key
from app.services.retry import retry_async as run_retry
from conftest import FakeRedis


JOB_ID = "job_00000000-0000-4000-8000-000000000000"


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def retrieve(self, response_id):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeOpenAI:
    def __init__(self, outcomes=()):
        self.responses = FakeResponses(outcomes)

    async def close(self):
        pass


def record(status):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id=JOB_ID,
        status=status,
        openai_response_id="resp_secret",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        status_url=f"/v1/responses/{JOB_ID}",
        correlation_id="original-correlation",
    )


def headers():
    return {"Authorization": "Bearer test-wrapper-key", "X-Correlation-ID": "poll-correlation"}


def completed_response():
    return SimpleNamespace(
        id="resp_private",
        _request_id="req_poll",
        status="completed",
        model="gpt-5-mini",
        output_text="finished",
        usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
    )


def install(monkeypatch, redis, openai):
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)


def provider_error(kind, status_code=None):
    if kind in (APIConnectionError, APITimeoutError):
        return kind(request=None)
    response = SimpleNamespace(status_code=status_code, headers={}, request=None)
    return kind(
        message="provider secret: prompt",
        response=response,
        body={"error": "secret"},
    )


def install_active_job(monkeypatch, outcomes):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    openai = FakeOpenAI(outcomes)
    install(monkeypatch, redis, openai)

    async def no_wait(seconds):
        return None

    async def immediate_retry(operation, *, operation_name, max_retries=2):
        return await run_retry(
            operation,
            operation_name=operation_name,
            max_retries=max_retries,
            sleep=no_wait,
            random_value=lambda: 0,
        )

    monkeypatch.setattr("app.api.responses.retry_async", immediate_retry)
    return redis, openai


def test_nonterminal_job_without_provider_id_returns_cached_202(monkeypatch):
    redis = FakeRedis()
    cached = record(JobStatus.PENDING).model_copy(update={"openai_response_id": None})
    redis.values[job_key(JOB_ID)] = cached.model_dump_json()
    openai = FakeOpenAI([])
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())

    assert response.status_code == 202
    assert openai.responses.calls == 0


def test_poll_recovers_completed_job(monkeypatch):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    openai = FakeOpenAI([completed_response()])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["output_text"] == "finished"
    assert response.json()["usage"]["total_tokens"] == 6
    assert "openai_response_id" not in response.json()
    assert openai.responses.calls == 1


@pytest.mark.parametrize(
    ("provider_status", "local_status"),
    [("queued", "pending"), ("in_progress", "in_progress")],
)
def test_poll_keeps_provider_nonterminal_status_at_202(monkeypatch, provider_status, local_status):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    openai = FakeOpenAI([SimpleNamespace(status=provider_status)])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert response.json()["status"] == local_status


def test_poll_returns_cached_job_when_reconciliation_is_already_claimed(monkeypatch):
    redis = FakeRedis()
    cached = record(JobStatus.IN_PROGRESS)
    redis.values[job_key(JOB_ID)] = cached.model_dump_json()
    asyncio.run(claim_reconciliation(redis, JOB_ID, "other-owner", 100))
    openai = FakeOpenAI([completed_response()])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert openai.responses.calls == 0


def test_terminal_job_does_not_retrieve_provider(monkeypatch):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.COMPLETED).model_dump_json()
    openai = FakeOpenAI([completed_response()])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert openai.responses.calls == 0


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INCOMPLETE])
def test_terminal_job_returns_200(monkeypatch, status):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(status).model_dump_json()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == status


def test_completed_job_returns_normalized_result(monkeypatch):
    redis = FakeRedis()
    completed = record(JobStatus.COMPLETED).model_copy(
        update={
            "model": "gpt-5-mini",
            "output_text": "finished",
            "usage": Usage(input_tokens=4, output_tokens=2, total_tokens=6),
        }
    )
    redis.values[job_key(JOB_ID)] = completed.model_dump_json()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)

    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5-mini"
    assert response.json()["output_text"] == "finished"
    assert response.json()["usage"] == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
    }


@pytest.mark.parametrize("job_id", ["not-a-job", JOB_ID])
def test_missing_or_malformed_job_returns_safe_404(monkeypatch, job_id):
    monkeypatch.setattr("app.main.create_redis", lambda url: FakeRedis())
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{job_id}", headers=headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_expired_job_returns_404(monkeypatch):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.EXPIRED).model_dump_json()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_redis_failure_returns_503(monkeypatch):
    class ErrorRedis(FakeRedis):
        async def get(self, key):
            raise ConnectionError("offline")

    monkeypatch.setattr("app.main.create_redis", lambda url: ErrorRedis())
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_status_requires_authentication():
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "error",
    [
        provider_error(APITimeoutError),
        provider_error(APIConnectionError),
        provider_error(RateLimitError, 429),
        provider_error(APIStatusError, 503),
    ],
)
def test_transient_retrieval_failure_returns_cached_202(monkeypatch, error):
    redis, _ = install_active_job(monkeypatch, [error, error, error])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert response.json()["status"] == "in_progress"
    assert JobRecord.model_validate_json(redis.values[job_key(JOB_ID)]).status is JobStatus.IN_PROGRESS


def test_provider_404_becomes_safe_terminal_failure(monkeypatch):
    redis, _ = install_active_job(monkeypatch, [provider_error(APIStatusError, 404)])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == {
        "code": "background_response_unavailable",
        "message": "Background response is no longer available.",
    }
    assert "secret" not in response.text


def test_provider_auth_failure_preserves_job_and_returns_503(monkeypatch):
    redis, _ = install_active_job(monkeypatch, [provider_error(AuthenticationError, 401)])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert JobRecord.model_validate_json(redis.values[job_key(JOB_ID)]).status is JobStatus.IN_PROGRESS


def test_permanent_provider_4xx_preserves_job_and_returns_safe_500(monkeypatch):
    redis, _ = install_active_job(monkeypatch, [provider_error(APIStatusError, 400)])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert JobRecord.model_validate_json(redis.values[job_key(JOB_ID)]).status is JobStatus.IN_PROGRESS


def test_reconciliation_redis_failure_returns_503(monkeypatch):
    class EvalErrorRedis(FakeRedis):
        async def eval(self, script, numkeys, *args):
            raise ConnectionError("offline")

    redis = EvalErrorRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    install(monkeypatch, redis, FakeOpenAI([completed_response()]))
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_poll_reconciliation_logs_exclude_sensitive_values(monkeypatch, captured_events):
    install_active_job(monkeypatch, [completed_response()])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    serialized = json.dumps(captured_events)
    for forbidden in (
        "resp_private",
        "finished",
        "test-openai-key",
        "test-webhook-secret",
        "test-wrapper-key",
    ):
        assert forbidden not in serialized
