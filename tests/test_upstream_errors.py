from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.main import create_app
from app.services.retry import retry_async


def provider_error(kind, status_code=None):
    if kind in (APIConnectionError, APITimeoutError):
        return kind(request=None)
    response = SimpleNamespace(status_code=status_code, headers={}, request=None)
    return kind(message="provider secret: prompt", response=response, body={"error": "secret"})


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeOpenAI:
    def __init__(self, outcomes):
        self.responses = FakeResponses(outcomes)

    async def close(self):
        pass


@pytest.fixture
def fake_openai(monkeypatch):
    def make(outcomes):
        client = FakeOpenAI(outcomes)
        monkeypatch.setattr("app.main.create_openai_client", lambda settings: client)
        return client

    async def no_wait(seconds):
        pass

    async def immediate_retry(operation):
        return await retry_async(operation, sleep=no_wait, random_value=lambda: 0)

    monkeypatch.setattr("app.api.responses.retry_async", immediate_retry)
    return make


def headers():
    return {"Authorization": "Bearer test-wrapper-key", "X-Correlation-ID": "phase-9-test"}


def response():
    return SimpleNamespace(id="resp_123", status="completed", model="gpt-5-mini", output_text="ok", usage=None)


def test_retries_transient_provider_failure_then_returns_response(fake_openai):
    openai = fake_openai([provider_error(APIConnectionError), response()])

    with TestClient(create_app()) as client:
        result = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert result.status_code == 200
    assert openai.responses.calls == 2


def test_timeout_after_retries_returns_correlated_gateway_timeout(fake_openai):
    openai = fake_openai([provider_error(APITimeoutError)] * 3)

    with TestClient(create_app()) as client:
        result = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert result.status_code == 504
    assert result.json()["error"] == {
        "code": "upstream_timeout",
        "message": "Request failed.",
        "correlation_id": "phase-9-test",
    }
    assert result.headers["X-Correlation-ID"] == "phase-9-test"
    assert openai.responses.calls == 3


@pytest.mark.parametrize(
    ("error", "calls"),
    [
        (provider_error(APIConnectionError), 3),
        (provider_error(APIStatusError, 503), 3),
        (provider_error(RateLimitError, 429), 3),
        (provider_error(AuthenticationError, 401), 1),
    ],
)
def test_provider_unavailable_failures_are_safe_and_correlated(fake_openai, error, calls):
    openai = fake_openai([error] * calls)

    with TestClient(create_app()) as client:
        result = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert result.status_code == 503
    assert result.json()["error"] == {
        "code": "upstream_unavailable",
        "message": "Request failed.",
        "correlation_id": "phase-9-test",
    }
    assert "secret" not in result.text
    assert openai.responses.calls == calls


def test_permanent_provider_error_is_not_retried_and_returns_internal_error(fake_openai):
    openai = fake_openai([provider_error(APIStatusError, 400)])

    with TestClient(create_app()) as client:
        result = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert result.status_code == 500
    assert result.json()["error"]["code"] == "internal_error"
    assert openai.responses.calls == 1


def test_unexpected_provider_error_does_not_leak_secret(fake_openai):
    openai = fake_openai([RuntimeError("openai key=very-secret prompt=private")])

    with TestClient(create_app()) as client:
        result = client.post("/v1/responses", headers=headers(), json={"input": "Hi"})

    assert result.status_code == 500
    assert result.json()["error"] == {
        "code": "internal_error",
        "message": "Internal server error.",
        "correlation_id": "phase-9-test",
    }
    assert "very-secret" not in result.text
    assert openai.responses.calls == 1
