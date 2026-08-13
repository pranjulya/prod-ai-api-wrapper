import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from openai import APIConnectionError, APITimeoutError, APIStatusError, RateLimitError
except ImportError:  # pragma: no cover - dependency is required at runtime
    APIConnectionError = APITimeoutError = APIStatusError = RateLimitError = ()


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    if headers:
        value = headers.get("retry-after") or headers.get("Retry-After")
        try:
            return max(0.0, float(value)) if value is not None else None
        except (TypeError, ValueError):
            return None
    value = getattr(error, "retry_after", None)
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _transient(error: Exception) -> bool:
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    return isinstance(error, APIStatusError) and getattr(error, "status_code", 0) >= 500


async def retry_async(
    operation: Callable[[], Awaitable[Any]],
    *,
    max_retries: int = 2,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> Any:
    retries = min(max(0, max_retries), 2)
    for attempt in range(retries + 1):
        try:
            return await operation()
        except Exception as error:
            if attempt >= retries or not _transient(error):
                raise
            delay = _retry_after(error)
            if delay is None:
                delay = (0.1 * (2**attempt)) + (0.1 * random_value())
            await sleep(delay)
