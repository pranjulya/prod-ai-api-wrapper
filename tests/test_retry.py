import asyncio

import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.services.retry import retry_async


def _error(cls, **kwargs):
    if cls is APIConnectionError:
        return cls(request=None)
    if cls is APITimeoutError:
        return cls(request=None)
    if cls is AuthenticationError:
        return cls(message="no", response=kwargs.get("response"), body=None)
    return cls(message="no", response=kwargs.get("response"), body=None)


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

    assert asyncio.run(retry_async(operation, sleep=sleep, random_value=lambda: 0)) == "ok"
    assert calls == 2
    assert sleeps == [0.1]


def test_exhaustion_raises_final_error_without_extra_sleep():
    calls = 0
    sleeps = []

    async def operation():
        nonlocal calls
        calls += 1
        raise _error(APITimeoutError)

    async def sleep(delay):
        sleeps.append(delay)

    with pytest.raises(APITimeoutError):
        asyncio.run(retry_async(operation, sleep=sleep, random_value=lambda: 0))
    assert calls == 3
    assert sleeps == [0.1, 0.2]


def test_non_retryable_error_is_raised_immediately():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        raise _error(AuthenticationError)

    with pytest.raises(AuthenticationError):
        asyncio.run(retry_async(operation))
    assert calls == 1


def test_retries_provider_5xx():
    response = type("Response", (), {"status_code": 503, "headers": {}})()
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise _error(APIStatusError, response=response)
        return 42

    assert asyncio.run(retry_async(operation, sleep=lambda _: asyncio.sleep(0), random_value=lambda: 0)) == 42


def test_honors_retry_after_header():
    response = type("Response", (), {"status_code": 429, "headers": {"retry-after": "3"}})()
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

    assert asyncio.run(retry_async(operation, sleep=sleep)) == "ok"
    assert sleeps == [3.0]
