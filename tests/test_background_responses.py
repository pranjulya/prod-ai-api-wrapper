import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app
from conftest import FakeRedis


class FakeResponses:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="resp_background", _request_id="req_test_14")


class FakeOpenAI:
    def __init__(self):
        self.responses = FakeResponses()

    async def close(self):
        pass


def headers(key="background-key"):
    return {"Authorization": "Bearer test-wrapper-key", "Idempotency-Key": key, "X-Correlation-ID": "background-test"}


def event(records, name):
    return [record for record in records if record["event"] == name]


def test_background_creation_and_replay(monkeypatch, captured_events):
    openai = FakeOpenAI()
    redis = FakeRedis()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    with TestClient(create_app()) as client:
        first = client.post("/v1/responses/background", headers=headers("background-key-sentinel-task-3"), json={"input": "prompt-sentinel-task-3"})
        second = client.post("/v1/responses/background", headers=headers("background-key-sentinel-task-3"), json={"input": "prompt-sentinel-task-3"})

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert first.json()["id"].startswith("job_")
    assert first.json()["status"] == "in_progress"
    assert first.json()["status_url"].endswith(first.json()["id"])
    assert first.json()["correlation_id"] == "background-test"
    assert openai.responses.calls == [{"input": "prompt-sentinel-task-3", "model": "gpt-5-mini", "background": True}]
    job_values = [value for key, value in redis.values.items() if key.startswith("wrapper:job:")]
    assert len(job_values) == 1
    assert '"status":"in_progress"' in job_values[0]
    assert '"openai_response_id":"resp_background"' in job_values[0]
    created = event(captured_events, "background_job_created")
    replayed = event(captured_events, "idempotency_replayed")
    assert len(created) == 1
    assert created[0]["job_id"] == first.json()["id"]
    assert created[0]["operation"] == "background_create"
    assert created[0]["openai_request_id"] == "req_test_14"
    assert replayed[-1]["job_id"] == first.json()["id"]
    assert replayed[-1]["operation"] == "background_create"
    assert "resp_background" not in json.dumps(captured_events)
    assert "prompt-sentinel-task-3" not in json.dumps(captured_events)
    assert "background-key-sentinel-task-3" not in json.dumps(captured_events)


def test_background_rejects_missing_key(monkeypatch):
    openai = FakeOpenAI()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/responses/background", headers={"Authorization": "Bearer test-wrapper-key"}, json={"input": "Hi"}
        )
    assert response.status_code == 422
    assert openai.responses.calls == []


def test_background_same_key_different_body_conflicts(monkeypatch):
    openai = FakeOpenAI()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    with TestClient(create_app()) as client:
        client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})
        response = client.post("/v1/responses/background", headers=headers(), json={"input": "Different"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_background_redis_failure_logs_request_failed(monkeypatch, captured_events):
    class ErrorRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise ConnectionError("offline secret")

    openai = FakeOpenAI()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    monkeypatch.setattr("app.main.create_redis", lambda url: ErrorRedis())

    with TestClient(create_app()) as client:
        response = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})

    failed = event(captured_events, "request_failed")[-1]
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert failed["status_code"] == 503
    assert failed["error_category"] == "redis"
    assert failed["operation"] == "background_create"
    assert "offline secret" not in json.dumps(captured_events)
