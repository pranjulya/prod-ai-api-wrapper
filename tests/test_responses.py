from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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
        status="completed",
        model="gpt-5-mini",
        output_text="Hello from OpenAI",
        usage=SimpleNamespace(input_tokens=3, output_tokens=4, total_tokens=7),
    )
    fake = FakeOpenAI(response)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: fake)
    return fake


def headers(**extra):
    return {"Authorization": "Bearer test-wrapper-key", **extra}


def test_response_uses_default_model_and_normalizes_provider_response(fake_openai):
    with TestClient(create_app()) as client:
        response = client.post("/v1/responses", headers=headers(**{"X-Correlation-ID": "request-123"}), json={"input": "Hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("wrp_resp_")
    assert body == {
        **body,
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
