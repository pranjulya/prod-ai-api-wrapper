import asyncio
import json
import logging

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.logging import log_event
from app.services.retry import retry_async


def _response(status_code, headers=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return httpx.Response(status_code, headers=headers, request=request)


def _error(cls, **kwargs):
    if cls is APIConnectionError:
        return cls(request=None)
    if cls is APITimeoutError:
        return cls(request=None)
    if cls is AuthenticationError:
        return cls(message="no", response=kwargs.get("response", _response(401)), body=None)
    return cls(message="no", response=kwargs.get("response"), body=None)


def event(records, name):
    return [record for record in records if record["event"] == name]


def test_retries_transient_error_then_succeeds():
    calls = 0
    sleeps = []

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _error(APIConnectionError)
        return "ok"

    async def sleep(delay):
        sleeps.append(delay)

    assert asyncio.run(retry_async(operation, operation_name="create", sleep=sleep, random_value=lambda: 0)) == "ok"
    assert calls == 2
    assert sleeps == [0.1]


def test_exhaustion_raises_final_error_without_extra_sleep(captured_events):
    calls = 0
    sleeps = []

    async def operation():
        nonlocal calls
        calls += 1
        raise _error(APITimeoutError)

    async def sleep(delay):
        sleeps.append(delay)

    with pytest.raises(APITimeoutError):
        asyncio.run(retry_async(operation, operation_name="create", sleep=sleep, random_value=lambda: 0))
    assert calls == 3
    assert sleeps == [0.1, 0.2]
    failed = event(captured_events, "openai_request_failed")
    assert [record["retry_count"] for record in failed] == [0, 1, 2]
    assert {record["operation"] for record in failed} == {"create"}
    assert {record["error_category"] for record in failed} == {"openai_timeout"}


def test_non_retryable_error_is_raised_immediately():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        raise _error(AuthenticationError)

    with pytest.raises(AuthenticationError):
        asyncio.run(retry_async(operation, operation_name="create"))
    assert calls == 1


def test_retries_provider_5xx():
    response = _response(503)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise _error(APIStatusError, response=response)
        return 42

    assert asyncio.run(
        retry_async(operation, operation_name="create", sleep=lambda _: asyncio.sleep(0), random_value=lambda: 0)
    ) == 42


def test_honors_retry_after_header():
    response = _response(429, {"retry-after": "3"})
    sleeps = []
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _error(RateLimitError, response=response)
        return "ok"

    async def sleep(delay):
        sleeps.append(delay)

    assert asyncio.run(retry_async(operation, operation_name="create", sleep=sleep)) == "ok"
    assert sleeps == [3.0]


@pytest.mark.parametrize(
    ("error", "expected_category"),
    [
        (_error(APIConnectionError), "openai_connection"),
        (_error(APITimeoutError), "openai_timeout"),
        (_error(RateLimitError, response=_response(429, {"x-request-id": "req_rl"})), "openai_rate_limit"),
        (_error(AuthenticationError, response=_response(401, {"x-request-id": "req_auth"})), "openai_authentication"),
        (_error(APIStatusError, response=_response(400, {"x-request-id": "req_4xx"})), "openai_4xx"),
        (_error(APIStatusError, response=_response(503, {"x-request-id": "req_5xx"})), "openai_5xx"),
    ],
)
def test_logs_failure_category_and_diagnostic_request_id(captured_events, error, expected_category):
    async def operation():
        raise error

    with pytest.raises(type(error)):
        asyncio.run(retry_async(operation, operation_name="create", max_retries=0))

    failed = event(captured_events, "openai_request_failed")[-1]
    assert failed["operation"] == "create"
    assert failed["retry_count"] == 0
    assert failed["error_category"] == expected_category
    assert failed.get("openai_request_id") == getattr(getattr(error, "response", None), "headers", {}).get("x-request-id")
    assert str(error) not in json.dumps(captured_events)


def test_arbitrary_exception_request_id_is_omitted(captured_events):
    class ArbitraryError(RuntimeError):
        request_id = "arbitrary-exception-id-secret"

    error = ArbitraryError("provider secret")

    async def operation():
        raise error

    with pytest.raises(ArbitraryError) as caught:
        asyncio.run(retry_async(operation, operation_name="create", max_retries=0))

    failed = event(captured_events, "openai_request_failed")[-1]
    assert caught.value is error
    assert "openai_request_id" not in failed
    assert "arbitrary-exception-id-secret" not in json.dumps(captured_events)


def test_raising_request_id_property_does_not_replace_provider_error(captured_events):
    class RaisingRequestIdError(RuntimeError):
        @property
        def request_id(self):
            raise ValueError("request-id-accessor-secret")

    error = RaisingRequestIdError("original provider failure")

    async def operation():
        raise error

    with pytest.raises(RaisingRequestIdError) as caught:
        asyncio.run(retry_async(operation, operation_name="create", max_retries=0))

    assert caught.value is error
    assert "request-id-accessor-secret" not in json.dumps(captured_events)


def test_log_event_swallows_logging_infrastructure_failure():
    class RaisingLogger(logging.Logger):
        def handle(self, record):
            raise RuntimeError("logger infrastructure secret")

    log_event(RaisingLogger("app.test.raising"), logging.WARNING, "openai_request_failed", operation="create")
