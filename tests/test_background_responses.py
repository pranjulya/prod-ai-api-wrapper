import json
from types import SimpleNamespace

from conftest import FakeRedis
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app
from app.services import jobs as jobs_service


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


class ExecuteErrorPipeline:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def set(self, *args, **kwargs):
        self.pipeline.set(*args, **kwargs)

    def incr(self, *args, **kwargs):
        self.pipeline.incr(*args, **kwargs)

    def expire(self, *args, **kwargs):
        self.pipeline.expire(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.pipeline.delete(*args, **kwargs)

    async def execute(self):
        if any(command[0] == "set" and command[1].startswith("wrapper:job:") for command in self.pipeline.commands):
            raise ConnectionError("pipeline failed")
        return await self.pipeline.execute()


class ProviderIdErrorRedis(FakeRedis):
    def pipeline(self, transaction=True):
        return ExecuteErrorPipeline(super().pipeline(transaction=transaction))


class IdempotencyStoreErrorRedis(FakeRedis):
    async def set(self, key, value, nx=False, ex=None):
        if key.startswith("wrapper:idempotency:") and not nx:
            raise ConnectionError("store failed")
        return await super().set(key, value, nx=nx, ex=ex)


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


def test_background_post_provider_job_update_failure_does_not_call_provider_twice(monkeypatch):
    openai = FakeOpenAI()
    redis = ProviderIdErrorRedis()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)

    with TestClient(create_app()) as client:
        first = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})
        second = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_in_progress"
    assert len(openai.responses.calls) == 1


def test_background_idempotency_store_failure_preserves_job_and_does_not_call_provider_twice(monkeypatch):
    openai = FakeOpenAI()
    redis = IdempotencyStoreErrorRedis()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)

    with TestClient(create_app()) as client:
        first = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})
        second = client.post("/v1/responses/background", headers=headers(), json={"input": "Hi"})

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_in_progress"
    assert len(openai.responses.calls) == 1
    assert jobs_service.job_key(first.json()["id"]) in redis.values
    assert jobs_service.response_job_key("resp_background") in redis.values
