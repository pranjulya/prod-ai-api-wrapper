from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app
from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import job_key
from conftest import FakeRedis


JOB_ID = "job_00000000-0000-4000-8000-000000000000"


class FakeOpenAI:
    def __init__(self):
        self.calls = 0

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


@pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.IN_PROGRESS])
def test_active_job_returns_202(monkeypatch, status):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(status).model_dump_json()
    openai = FakeOpenAI()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)

    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())

    assert response.status_code == 202
    assert response.json()["status"] == status
    assert "openai_response_id" not in response.json()
    assert response.headers["X-Correlation-ID"] == "poll-correlation"
    assert openai.calls == 0


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INCOMPLETE])
def test_terminal_job_returns_200(monkeypatch, status):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(status).model_dump_json()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == status


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
