import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
except ImportError:  # pragma: no cover - dependency is required at runtime
    APIConnectionError = APITimeoutError = APIStatusError = AuthenticationError = RateLimitError = ()
    _OPENAI_ERROR_TYPES = ()
else:
    _OPENAI_ERROR_TYPES = (
        APIConnectionError,
        APITimeoutError,
        APIStatusError,
        AuthenticationError,
        RateLimitError,
    )

from app.logging import log_event

logger = logging.getLogger(__name__)
MAX_RETRY_DELAY_SECONDS = 5


def openai_request_id(value) -> str | None:
    try:
        if not isinstance(value, Exception):
            candidate = getattr(value, "_request_id", None)
            return candidate if isinstance(candidate, str) and candidate else None
        if not isinstance(value, _OPENAI_ERROR_TYPES):
            return None
        candidate = getattr(value, "request_id", None)
        if isinstance(candidate, str) and candidate:
            return candidate
        response = getattr(value, "response", None)
        headers = getattr(response, "headers", None)
        candidate = headers.get("x-request-id") or headers.get("X-Request-ID")
        return candidate if isinstance(candidate, str) and candidate else None
    except Exception:
        return None


def openai_error_category(error: Exception) -> str:
    if isinstance(error, APITimeoutError):
        return "openai_timeout"
    if isinstance(error, APIConnectionError):
        return "openai_connection"
    if isinstance(error, RateLimitError):
        return "openai_rate_limit"
    if isinstance(error, AuthenticationError):
        return "openai_authentication"
    if isinstance(error, APIStatusError):
        return "openai_5xx" if error.status_code >= 500 else "openai_4xx"
    return "internal"


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
    operation_name: str,
    max_retries: int = 2,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    random_value: Callable[[], float] = random.random,
) -> Any:
    retries = min(max(0, max_retries), 2)
    for attempt in range(retries + 1):
        try:
            return await operation()
        except Exception as error:
            log_event(
                logger,
                logging.WARNING,
                "openai_request_failed",
                operation=operation_name,
                retry_count=attempt,
                openai_request_id=openai_request_id(error),
                error_category=openai_error_category(error),
            )
            if attempt >= retries or not _transient(error):
                raise
            delay = _retry_after(error)
            if delay is None:
                delay = (0.1 * (2**attempt)) + (0.1 * random_value())
            await sleep(min(delay, MAX_RETRY_DELAY_SECONDS))
