from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app
from conftest import FakeRedis


class FakeResponses:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="resp_background")


class FakeOpenAI:
    def __init__(self):
        self.responses = FakeResponses()

    async def close(self):
        pass


def headers(key="background-key"):
    return {"Authorization": "Bearer test-wrapper-key", "Idempotency-Key": key, "X-Correlation-ID": "background-test"}


def test_background_creation_and_replay(monkeypatch):
    openai = FakeOpenAI()
    redis = FakeRedis()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    with TestClient(create_app()) as client:
        first = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})
        second = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert first.json()["id"].startswith("job_")
    assert first.json()["status"] == "in_progress"
    assert first.json()["status_url"].endswith(first.json()["id"])
    assert first.json()["correlation_id"] == "background-test"
    assert openai.responses.calls == [{"input": "Hi", "model": "gpt-5-mini", "background": True}]
    job_values = [value for key, value in redis.values.items() if key.startswith("wrapper:job:")]
    assert len(job_values) == 1
    assert '"status":"in_progress"' in job_values[0]
    assert '"openai_response_id":"resp_background"' in job_values[0]


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
