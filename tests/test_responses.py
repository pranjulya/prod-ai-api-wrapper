import json
from types import SimpleNamespace

import pytest
from conftest import FakeRedis
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response):
        self.responses = FakeResponses(response)

    async def close(self):
        pass


@pytest.fixture
def fake_openai(monkeypatch):
    response = SimpleNamespace(
        id="resp_123",
        _request_id="req_test_14",
        status="completed",
        model="gpt-5-mini",
        output_text="Hello from OpenAI",
        usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
    )
    fake = FakeOpenAI(response)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: fake)
    return fake


def headers(**extra):
    return {"Authorization": "Bearer test-wrapper-key", "Idempotency-Key": "test-key", **extra}


def event(records, name):
    return [record for record in records if record["event"] == name]


def test_response_uses_default_model_and_normalizes_provider_response(fake_openai):
    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(**{"X-Correlation-ID": "request-123"}), json={"input": "Hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("wrp_resp_")
    assert {key: value for key, value in body.items() if key != "id"} == {
        "openai_response_id": "resp_123",
        "status": "completed",
        "model": "gpt-5-mini",
        "output_text": "Hello from OpenAI",
        "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
        "correlation_id": "request-123",
    }
    assert response.headers["X-Correlation-ID"] == "request-123"
    assert fake_openai.responses.calls == [{"input": "Hi", "model": "gpt-5-mini"}]


def test_response_forwards_only_supplied_approved_fields(fake_openai):
    payload = {
        "input": "Hi",
        "instructions": "Be concise",
        "model": "gpt-4o",
        "max_output_tokens": 12,
        "metadata": {"source": "test"},
    }
    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(), json=payload)

    assert response.status_code == 200
    assert fake_openai.responses.calls == [payload]


@pytest.mark.parametrize(
    "payload",
    [
        {"input": "Hi", "temperature": 0},
        {"input": "   "},
        {"input": "x" * 50_001},
        {"input": "Hi", "instructions": " "},
        {"input": "Hi", "instructions": "x" * 10_001},
        {"input": "Hi", "max_output_tokens": 0},
        {"input": "Hi", "max_output_tokens": 16_385},
        {"input": "Hi", "max_output_tokens": True},
        {"input": "Hi", "max_output_tokens": "12"},
        {"input": "Hi", "max_output_tokens": 12.0},
        {"input": "Hi", "metadata": {"": "value"}},
        {"input": "Hi", "metadata": {"k" * 65: "value"}},
        {"input": "Hi", "metadata": {"key": "v" * 513}},
        {"input": "Hi", "metadata": {str(index): "value" for index in range(17)}},
    ],
)
def test_response_rejects_invalid_payloads(fake_openai, payload):
    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(), json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert fake_openai.responses.calls == []


def test_response_allows_missing_provider_usage(fake_openai):
    fake_openai.responses.response.usage = None

    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert response.status_code == 200
    assert response.json()["usage"] is None


def test_response_ignores_raising_diagnostic_request_id(fake_openai, captured_events):
    class RaisingRequestIdResponse(SimpleNamespace):
        @property
        def _request_id(self):
            raise RuntimeError("diagnostic-accessor-secret")

    fake_openai.responses.response = RaisingRequestIdResponse(
        id="resp_123",
        status="completed",
        model="gpt-5-mini",
        output_text="Hello from OpenAI",
        usage=None,
    )

    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert response.status_code == 200
    assert len(fake_openai.responses.calls) == 1
    assert "diagnostic-accessor-secret" not in json.dumps(captured_events)


def test_response_replay_logs_idempotency_replayed_and_redacts_request_data(fake_openai, captured_events):
    prompt = "prompt-sentinel-task-3"
    key = "idempotency-key-sentinel-task-3"

    with TestClient(create_app()) as client:
        first = client.post(
            "/v1/responses",
            headers=headers(**{"Idempotency-Key": key, "X-Correlation-ID": "request-123"}),
            json={"input": prompt},
        )
        second = client.post(
            "/v1/responses",
            headers=headers(**{"Idempotency-Key": key, "X-Correlation-ID": "request-123"}),
            json={"input": prompt},
        )

    replayed = event(captured_events, "idempotency_replayed")
    completed = [record for record in event(captured_events, "request_completed") if record.get("openai_request_id")][-1]
    assert first.status_code == second.status_code == 200
    assert len(replayed) == 1
    assert replayed[0]["operation"] == "create"
    assert completed["openai_request_id"] == "req_test_14"
    assert "resp_123" not in json.dumps(captured_events)
    assert prompt not in json.dumps(captured_events)
    assert key not in json.dumps(captured_events)


def test_response_redis_failure_logs_request_failed(fake_openai, monkeypatch, captured_events):
    class ErrorRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise ConnectionError("offline secret")

    monkeypatch.setattr("app.main.create_redis", lambda url: ErrorRedis())

    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    failed = event(captured_events, "request_failed")[-1]
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert failed["status_code"] == 503
    assert failed["error_category"] == "redis"
    assert failed["operation"] == "create"
    assert "offline secret" not in json.dumps(captured_events)


def test_response_store_failure_returns_result_without_second_provider_call(fake_openai, monkeypatch):
    class StoreErrorRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            if not nx:
                raise ConnectionError("store failed")
            return await super().set(key, value, nx=nx, ex=ex)

    redis = StoreErrorRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)

    with TestClient(create_app()) as client:
        first = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})
        second = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "idempotency_in_progress"
    assert len(fake_openai.responses.calls) == 1


def test_response_rejects_unsupported_model(fake_openai):
    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(), json={"input": "Hi", "model": "not-allowed"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_model"
    assert fake_openai.responses.calls == []


def test_response_requires_authentication(fake_openai):
    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", json={"input": "Hi"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert fake_openai.responses.calls == []
