# Phase 14 Structured JSON Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit safe structured JSON for application and Uvicorn logs so every wrapper request can be traced by correlation ID across security, provider, background-job, and webhook events.

**Architecture:** Use one standard-library `app/logging.py` module for formatting, configuration, field whitelisting, and correlation context. Existing middleware and route decision points emit explicit events; the retry service owns provider-attempt classification, and Redis webhook finalization reports whether a completed event actually won.

**Tech Stack:** Python 3.12 standard library, FastAPI/Starlette middleware, Uvicorn logging records, OpenAI Python SDK 3.x exceptions, Redis Lua, pytest.

## Global Constraints

- Work only on `feature/phase-14-structured-logging`; do not implement Phase 15.
- Add no runtime or development dependency.
- Keep existing status codes, response bodies, headers, retry ceiling, and Redis semantics.
- Apply validated `LOG_LEVEL` to application and Uvicorn loggers.
- Emit one compact JSON object per managed log record.
- Never serialize credentials, authorization/signature headers, idempotency keys, query strings, bodies, prompts, model output, Redis contents, provider response IDs, webhook event IDs, exception text, arguments, or tracebacks.
- Permit only the approved primitive fields from the design specification.
- Use test doubles only; tests must not contact Redis or OpenAI.
- Use test-driven development: observe each focused test fail before implementing its production change.

## File structure

- Create `app/logging.py`: JSON formatter, logger configuration, event helper, correlation context.
- Create `tests/test_logging.py`: formatter, Uvicorn, configuration, lifecycle, and redaction contract tests.
- Modify `app/main.py`: bootstrap and validated logging configuration.
- Modify `app/middleware/correlation.py`: request lifecycle timing/context/events.
- Modify `app/middleware/authentication.py`: authentication rejection event.
- Modify `app/middleware/rate_limiting.py`: rate-limit and Redis failure events.
- Modify `app/errors.py`: mark validation responses for lifecycle categorization.
- Modify `app/services/retry.py`: shared provider categories, diagnostic request IDs, per-attempt failure events.
- Modify `app/api/responses.py`: provider starts, replays, request IDs, and durable background creation events.
- Modify `app/services/webhooks.py`: typed atomic finalization outcome.
- Modify `app/api/webhooks.py`: verification/rejection/provider/job events.
- Modify focused existing tests and shared fakes only where their observable contract changes.
- Modify `Learning/api-design.md`, `Learning/questions-and-answers.md`, and `Learning/learning-path.md` after runtime behavior is complete.

---

### Task 1: JSON logging core and Uvicorn configuration

**Files:**
- Create: `app/logging.py`
- Modify: `app/main.py:1-47`
- Modify: `tests/conftest.py:1-156`
- Create: `tests/test_logging.py`

**Interfaces:**
- Produces: `JsonFormatter(logging.Formatter)`.
- Produces: `configure_logging(level: str) -> None`.
- Produces: `bind_correlation_id(value: str) -> contextvars.Token`.
- Produces: `reset_correlation_id(token: contextvars.Token) -> None`.
- Produces: `log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None`.
- Later tasks consume the event helper and correlation bindings without importing request objects.

- [ ] **Step 1: Add failing formatter and configuration tests**

Create `tests/test_logging.py` with focused records:

```python
import io
import json
import logging
import sys

from app.logging import (
    JsonFormatter,
    bind_correlation_id,
    configure_logging,
    log_event,
    reset_correlation_id,
)


def decode(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def test_application_event_is_json_and_whitelists_fields():
    stream = io.StringIO()
    logger = logging.getLogger("app.test.structured")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    token = bind_correlation_id("corr-1")
    try:
        log_event(
            logger,
            logging.INFO,
            "request_completed",
            method="GET",
            status_code=200,
            duration_ms=1.25,
            authorization="Bearer secret",
            body={"secret": True},
        )
    finally:
        reset_correlation_id(token)

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "request_completed"
    assert payload["level"] == "info"
    assert payload["logger"] == "app.test.structured"
    assert payload["correlation_id"] == "corr-1"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.25
    assert "authorization" not in payload
    assert "body" not in payload
    assert payload["timestamp"].endswith("Z")


def test_uvicorn_access_record_is_structured_without_query_string():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/health/live?token=secret", "1.1", 200),
        None,
    )
    payload = decode(record)
    assert payload == {
        "timestamp": payload["timestamp"],
        "level": "info",
        "event": "uvicorn_access",
        "logger": "uvicorn.access",
        "method": "GET",
        "route": "/health/live",
        "status_code": 200,
    }
    assert "secret" not in json.dumps(payload)


def test_uvicorn_server_record_uses_static_safe_message():
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        "Started %s",
        ("secret",),
        None,
    )
    payload = decode(record)
    assert payload["event"] == "uvicorn_server"
    assert payload["message"] == "Uvicorn server record."
    assert "secret" not in json.dumps(payload)


def test_third_party_record_drops_original_message_and_exception():
    record = logging.LogRecord(
        "httpx",
        logging.ERROR,
        __file__,
        1,
        "Bearer secret-in-message",
        (),
        RuntimeError,
    )
    payload = decode(record)
    assert payload["event"] == "third_party_log"
    assert payload["message"] == "Third-party log record."
    assert "secret-in-message" not in json.dumps(payload)


def test_configuration_is_idempotent_and_applies_level():
    configure_logging("DEBUG")
    configure_logging("DEBUG")
    root = logging.getLogger()
    managed = [handler for handler in root.handlers if getattr(handler, "wrapper_json_handler", False)]
    assert len(managed) == 1
    assert managed[0].stream is sys.stdout
    assert root.level == logging.DEBUG
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert logger.level == logging.DEBUG
        assert logger.handlers == []
        assert logger.propagate is True


def test_malformed_record_falls_back_to_valid_json():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "ignored", (), None)
    record.event = object()
    payload = decode(record)
    assert payload["event"] == "logging_error"
    assert set(payload) == {"timestamp", "level", "event", "logger"}
```

- [ ] **Step 2: Run the focused tests and confirm the missing-module failure**

Run:

```bash
uv run python -m pytest tests/test_logging.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.logging'`.

- [ ] **Step 3: Implement the minimal safe logging module**

Create `app/logging.py` with this shape:

```python
import contextvars
import json
import logging
import math
import sys
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit


ALLOWED_FIELDS = frozenset(
    {
        "correlation_id",
        "method",
        "route",
        "status_code",
        "duration_ms",
        "job_id",
        "retry_count",
        "openai_request_id",
        "error_category",
        "operation",
        "retry_after",
        "webhook_type",
    }
)
_correlation_id = contextvars.ContextVar("correlation_id", default=None)
_MISSING = object()


def _safe(value):
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return _MISSING
    if isinstance(value, bool | str | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return _MISSING


def _timestamp(created: float | None = None) -> str:
    value = datetime.fromtimestamp(created, timezone.utc) if isinstance(created, int | float) else datetime.now(timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = {
                "timestamp": _timestamp(record.created),
                "level": record.levelname.lower(),
                "event": getattr(record, "event", "third_party_log"),
                "logger": record.name,
            }
            if record.name == "uvicorn.access":
                _, method, target, _, status_code = record.args
                payload.update(
                    event="uvicorn_access",
                    method=str(method),
                    route=urlsplit(str(target)).path,
                    status_code=int(status_code),
                )
            elif record.name in {"uvicorn", "uvicorn.error"}:
                payload.update(event="uvicorn_server", message="Uvicorn server record.")
            elif hasattr(record, "event"):
                for field in ALLOWED_FIELDS:
                    value = _safe(getattr(record, field, None))
                    if value is not _MISSING:
                        payload[field] = value
            else:
                payload["message"] = "Third-party log record."
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return json.dumps(
                {
                    "timestamp": _timestamp(),
                    "level": "error",
                    "event": "logging_error",
                    "logger": "logging",
                },
                separators=(",", ":"),
            )


def bind_correlation_id(value: str):
    return _correlation_id.set(value)


def reset_correlation_id(token) -> None:
    _correlation_id.reset(token)


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    extras = {"event": event}
    correlation_id = fields.pop("correlation_id", None) or _correlation_id.get()
    if correlation_id is not None:
        fields["correlation_id"] = correlation_id
    for name, raw in fields.items():
        if name in ALLOWED_FIELDS and _safe(raw) is not _MISSING:
            extras[name] = _safe(raw)
    try:
        logger.log(level, event, extra=extras)
    except Exception:
        return


def configure_logging(level: str) -> None:
    numeric_level = logging.getLevelNamesMapping().get(str(level).strip().upper(), logging.INFO)
    formatter = JsonFormatter()
    root = logging.getLogger()
    root.setLevel(numeric_level)
    for handler in root.handlers:
        handler.setFormatter(formatter)
    managed = next(
        (handler for handler in root.handlers if getattr(handler, "wrapper_json_handler", False)),
        None,
    )
    if managed is None:
        managed = logging.StreamHandler(sys.stdout)
        managed.wrapper_json_handler = True
        root.addHandler(managed)
    managed.setLevel(numeric_level)
    managed.setFormatter(formatter)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(numeric_level)
        logger.propagate = True
```

Keep the code boring. Do not add a logger class, schema package, serializer protocol, or configuration object.

- [ ] **Step 4: Add a reusable event-capture fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def captured_events():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(json.loads(JsonFormatter().format(record)))

    logger = logging.getLogger("app")
    handler = Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
```

Add `import logging` and `from app.logging import JsonFormatter` beside the existing imports. Do not expose raw `LogRecord` instances to later tests.

- [ ] **Step 5: Bootstrap logging before Uvicorn emits and reapply validated settings**

Modify `app/main.py`:

```python
import os

from app.logging import configure_logging


configure_logging(os.getenv("LOG_LEVEL", "INFO"))
```

Place the bootstrap call after imports and before `lifespan`. Immediately after `load_settings()` in `lifespan`, add:

```python
configure_logging(app.state.settings.log_level)
```

Do not load all settings at module import; missing secrets must continue failing only when lifespan starts.

- [ ] **Step 6: Run focused and configuration regression tests**

Run:

```bash
uv run python -m pytest tests/test_logging.py tests/test_health.py -q
```

Expected: all focused tests pass, including the existing invalid-`LOG_LEVEL` startup test.

- [ ] **Step 7: Commit the logging core**

```bash
git add app/logging.py app/main.py tests/conftest.py tests/test_logging.py
git commit -m "feat: add JSON logging core"
```

---

### Task 2: Correlated request, authentication, and rate-limit events

**Files:**
- Modify: `app/middleware/correlation.py:1-33`
- Modify: `app/middleware/authentication.py:1-23`
- Modify: `app/middleware/rate_limiting.py:1-33`
- Modify: `app/errors.py:49-50`
- Modify: `tests/test_logging.py`
- Modify: `tests/test_authentication.py:117-145`
- Modify: `tests/test_rate_limiting.py:57-68`

**Interfaces:**
- Consumes: `bind_correlation_id`, `reset_correlation_id`, and `log_event` from Task 1.
- Produces: correlated `request_started`, `request_completed`, `request_failed`, `authentication_failed`, and `rate_limit_rejected` events.
- Preserves: all existing response and middleware ordering behavior.

- [ ] **Step 1: Write failing request-lifecycle tests**

Add to `tests/test_logging.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


def event(records, name):
    return [record for record in records if record["event"] == name]


def test_request_lifecycle_is_correlated_and_uses_route_template(captured_events):
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live",
            headers={
                "Authorization": "Bearer test-wrapper-key",
                "X-Correlation-ID": "trace-14",
            },
        )
    started = event(captured_events, "request_started")[-1]
    completed = event(captured_events, "request_completed")[-1]
    assert started["correlation_id"] == completed["correlation_id"] == "trace-14"
    assert completed["method"] == "GET"
    assert completed["route"] == "/health/live"
    assert completed["status_code"] == 200
    assert completed["duration_ms"] >= 0


def test_invalid_correlation_completion_is_categorized(captured_events):
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live",
            headers={
                "Authorization": "Bearer test-wrapper-key",
                "X-Correlation-ID": "invalid value",
            },
        )
    completed = event(captured_events, "request_completed")[-1]
    assert response.status_code == 400
    assert completed["status_code"] == 400
    assert completed["error_category"] == "validation"
```

Replace the two plain-text `caplog` assertions in `tests/test_authentication.py` with structured assertions using `captured_events`. Keep the sentinel bearer value and assert it is absent from `json.dumps(captured_events)`.

- [ ] **Step 2: Write failing authentication and limiter event tests**

Add or extend focused tests:

```python
def test_authentication_failure_is_structured_and_redacted(captured_events):
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live",
            headers={"Authorization": "Bearer secret-auth-value"},
        )
    rejected = event(captured_events, "authentication_failed")[-1]
    assert response.status_code == 401
    assert rejected["status_code"] == 401
    assert rejected["error_category"] == "authentication"
    assert "secret-auth-value" not in json.dumps(captured_events)
```

In `tests/test_rate_limiting.py`, extend the existing rejection test:

```python
rejected = [record for record in captured_events if record["event"] == "rate_limit_rejected"][-1]
assert rejected["status_code"] == 429
assert rejected["retry_after"] == int(response.headers["Retry-After"])
assert rejected["error_category"] == "rate_limit"
```

Pass `captured_events` into that test. Add a Redis-error case that asserts a `request_failed` event with category `redis` and the existing 503 response.

- [ ] **Step 3: Run the request/security tests and confirm event assertions fail**

Run:

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py -q
```

Expected: API behavior tests still pass; new event lookups fail because the events are absent.

- [ ] **Step 4: Replace correlation middleware's plain strings with lifecycle events**

In `app/middleware/correlation.py`, add `time.perf_counter`, the Task 1 logging imports, and this small route helper:

```python
def _route(request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)
```

Implement `dispatch` with this ordering:

```python
token = bind_correlation_id(correlation_id)
started_at = time.perf_counter()
log_event(logger, logging.INFO, "request_started", method=request.method)
try:
    if supplied_id is not None and not CORRELATION_ID_PATTERN.fullmatch(supplied_id):
        request.state.error_category = "validation"
        response = error_response(
            400,
            "invalid_correlation_id",
            "Invalid correlation ID.",
            correlation_id,
        )
    else:
        try:
            response = await call_next(request)
        except StarletteHTTPException as exc:
            response = await http_exception_handler(request, exc)
        except Exception:
            request.state.error_category = "internal"
            log_event(
                logger,
                logging.ERROR,
                "request_failed",
                method=request.method,
                route=_route(request),
                status_code=500,
                error_category="internal",
            )
            response = error_response(500, "internal_error", "Internal server error.", correlation_id)
    response.headers["X-Correlation-ID"] = correlation_id
    log_event(
        logger,
        logging.INFO,
        "request_completed",
        method=request.method,
        route=_route(request),
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
        openai_request_id=getattr(request.state, "openai_request_id", None),
        error_category=getattr(request.state, "error_category", None),
    )
    return response
finally:
    reset_correlation_id(token)
```

Retain the existing UUID/pattern logic verbatim; only replace logging and add context/timing.

- [ ] **Step 5: Emit rejection and Redis failure events at their existing branches**

In `AuthenticationMiddleware.dispatch`, immediately before the 401 response:

```python
log_event(
    logger,
    logging.WARNING,
    "authentication_failed",
    method=request.method,
    route=request.url.path,
    status_code=401,
    error_category="authentication",
)
```

In `RateLimitingMiddleware.dispatch`, log Redis failure before raising the existing 503:

```python
log_event(
    logger,
    logging.ERROR,
    "request_failed",
    method=request.method,
    route=request.url.path,
    status_code=503,
    error_category="redis",
)
```

Immediately before the existing 429 response:

```python
log_event(
    logger,
    logging.WARNING,
    "rate_limit_rejected",
    method=request.method,
    route=request.url.path,
    status_code=429,
    retry_after=result.retry_after,
    error_category="rate_limit",
)
```

Create module loggers with `logging.getLogger(__name__)`. Never pass the credential, headers, Redis exception, or limiter key.

In `validation_exception_handler`, set:

```python
request.state.error_category = "validation"
```

before returning the unchanged 422 response.

- [ ] **Step 6: Run focused and existing error tests**

Run:

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py tests/test_responses.py -q
```

Expected: all tests pass; serialized event data contains none of the sentinels.

- [ ] **Step 7: Commit request and security events**

```bash
git add app/middleware/correlation.py app/middleware/authentication.py app/middleware/rate_limiting.py app/errors.py tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py
git commit -m "feat: log request security events"
```

---

### Task 3: OpenAI attempts, idempotency replay, and background-job events

**Files:**
- Modify: `app/services/retry.py:1-51`
- Modify: `app/api/responses.py:1-192`
- Modify: `tests/test_retry.py:1-105`
- Modify: `tests/test_responses.py`
- Modify: `tests/test_background_responses.py`

**Interfaces:**
- Produces: `openai_error_category(error: Exception) -> str`.
- Produces: `openai_request_id(value: object) -> str | None`.
- Changes: `retry_async(operation: Callable[[], Awaitable[Any]], *, operation_name: str, max_retries: int = 2, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep, random_value: Callable[[], float] = random.random) -> Any` requires the bounded operation name.
- Consumes: `log_event` and correlation context from Task 1.
- Produces: `openai_request_started`, `openai_request_failed`, `idempotency_replayed`, and `background_job_created` events.

- [ ] **Step 1: Write failing retry-category and attempt-count tests**

Update every existing `retry_async` call in `tests/test_retry.py` to pass `operation_name="create"`. Add `captured_events` to the exhaustion test and assert:

```python
failed = [record for record in captured_events if record["event"] == "openai_request_failed"]
assert [record["retry_count"] for record in failed] == [0, 1, 2]
assert {record["operation"] for record in failed} == {"create"}
assert {record["error_category"] for record in failed} == {"openai_timeout"}
```

Add a parameterized classification test covering connection, timeout, rate limit, authentication, other 4xx, and 5xx exceptions. Assert the diagnostic request ID is taken from `x-request-id` when present and no exception message is serialized. Add a logger whose `handle` method raises and assert `log_event` returns without propagating that logging-infrastructure exception.

- [ ] **Step 2: Run retry tests and confirm the signature/event failures**

Run:

```bash
uv run python -m pytest tests/test_retry.py -q
```

Expected: failures because `retry_async` does not accept `operation_name` and emits no records.

- [ ] **Step 3: Add shared provider classification and per-attempt logging**

In `app/services/retry.py`, import `logging`, `AuthenticationError`, and `log_event`. Add:

```python
logger = logging.getLogger(__name__)


def openai_request_id(value) -> str | None:
    direct = getattr(value, "_request_id", None) or getattr(value, "request_id", None)
    if isinstance(direct, str) and direct:
        return direct
    response = getattr(value, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        candidate = headers.get("x-request-id") or headers.get("X-Request-ID")
        return candidate if isinstance(candidate, str) and candidate else None
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
```

Add required `operation_name: str` after `*` in `retry_async`. At the beginning of every `except Exception as error` block, before retryability is checked, emit:

```python
log_event(
    logger,
    logging.WARNING,
    "openai_request_failed",
    operation=operation_name,
    retry_count=attempt,
    openai_request_id=openai_request_id(error),
    error_category=openai_error_category(error),
)
```

Do not change the loop bounds, retry conditions, delay calculation, or exception propagation.

- [ ] **Step 4: Write failing response and background event tests**

Extend the existing synchronous replay test to accept `captured_events` and assert exactly one `idempotency_replayed` event with `operation="create"`. Use a prompt sentinel and idempotency-key sentinel and assert neither appears in `json.dumps(captured_events)`.

Extend background creation/replay tests:

```python
created = [record for record in captured_events if record["event"] == "background_job_created"]
assert len(created) == 1
assert created[0]["job_id"] == first.json()["id"]
assert created[0]["operation"] == "background_create"

replayed = [record for record in captured_events if record["event"] == "idempotency_replayed"]
assert replayed[-1]["job_id"] == first.json()["id"]
assert replayed[-1]["operation"] == "background_create"
```

Give the fake successful SDK response `_request_id="req_test_14"` and assert the synchronous `request_completed` or `background_job_created` record contains that diagnostic ID, while the provider response ID remains absent.

- [ ] **Step 5: Run route tests and confirm event assertions fail**

Run:

```bash
uv run python -m pytest tests/test_responses.py tests/test_background_responses.py tests/test_upstream_errors.py -q
```

Expected: event assertions fail and production callers fail until they pass `operation_name`.

- [ ] **Step 6: Instrument the two response creation flows**

Add one module logger to `app/api/responses.py`. For a valid completed synchronous idempotency record, replace the direct return with:

```python
replayed = ResponsesResponse.model_validate(result.record.response)
log_event(
    logger,
    logging.INFO,
    "idempotency_replayed",
    operation="create",
)
return replayed
```

For a valid completed background idempotency record, replace its direct return with:

```python
replayed = BackgroundJobResponse.model_validate(result.record.response)
log_event(
    logger,
    logging.INFO,
    "idempotency_replayed",
    operation="background_create",
    job_id=replayed.id,
)
return replayed
```

Immediately before each provider retry loop, emit:

```python
log_event(logger, logging.INFO, "openai_request_started", operation=operation_name, retry_count=0)
```

Use the literal `"create"` in the synchronous route and
`"background_create"` in the background route; do not add a client-controlled
operation value.

Call the retry helper in the synchronous route as:

```python
response = await retry_async(
    lambda: request.app.state.openai.responses.create(**kwargs),
    operation_name="create",
)
```

Call it in the background route as:

```python
response = await retry_async(
    lambda: request.app.state.openai.responses.create(
        **_request_kwargs(payload, model),
        background=True,
    ),
    operation_name="background_create",
)
```

For synchronous success:

```python
request.state.openai_request_id = openai_request_id(response)
```

For background success, emit only after both the job/mapping update and idempotency store succeed:

```python
log_event(
    logger,
    logging.INFO,
    "background_job_created",
    operation="background_create",
    job_id=record.id,
    openai_request_id=openai_request_id(response),
)
```

Do not log model, payload, prompt, response ID, idempotency key, normalized output, or Redis key. Preserve every existing cleanup branch.

Before each `HTTPException(503)` caused by `RedisError` in these two routes,
emit `request_failed` at error level with the matching bounded operation,
`status_code=503`, and `error_category="redis"`. Do not pass the Redis
exception or any Redis key/value.

- [ ] **Step 7: Run provider, response, and background tests**

Run:

```bash
uv run python -m pytest tests/test_retry.py tests/test_responses.py tests/test_background_responses.py tests/test_upstream_errors.py -q
```

Expected: all tests pass with unchanged provider attempt counts and stable API errors.

- [ ] **Step 8: Commit provider and job creation events**

```bash
git add app/services/retry.py app/api/responses.py tests/test_retry.py tests/test_responses.py tests/test_background_responses.py
git commit -m "feat: log provider and job events"
```

---

### Task 4: Webhook verification and truthful completion events

**Files:**
- Modify: `app/services/webhooks.py:1-95`
- Modify: `app/api/webhooks.py:1-161`
- Modify: `tests/conftest.py:80-124`
- Modify: `tests/test_webhook_service.py:1-120`
- Modify: `tests/test_webhooks.py:1-324`

**Interfaces:**
- Produces: `FinalizationResult(IntEnum)` with `STALE=0`, `UPDATED=1`, `ALREADY_TERMINAL=2`.
- Changes: `finalize_event(redis, event_id: str, owner_token: str, record: JobRecord) -> FinalizationResult`.
- Consumes: `retry_async(operation_name="retrieve")`, `openai_request_id`, and `log_event`.
- Produces: `webhook_verified`, `webhook_rejected`, and truthful `job_completed` events.

- [ ] **Step 1: Write failing typed-finalization tests**

Update `tests/test_webhook_service.py` to import `FinalizationResult`. Change current boolean assertions to:

```python
assert asyncio.run(finalize_event(redis, "evt_done", "owner-a", completed)) is FinalizationResult.UPDATED
```

In the first-terminal-wins test, assert the first call is `UPDATED` and the late call is `ALREADY_TERMINAL`. Keep the stored-state assertions unchanged. The stale-owner test must assert `FinalizationResult.STALE`.

- [ ] **Step 2: Run the service tests and confirm enum assertions fail**

Run:

```bash
uv run python -m pytest tests/test_webhook_service.py -q
```

Expected: import or identity failures because finalization still returns `bool`.

- [ ] **Step 3: Return a precise atomic finalization outcome**

In `FINALIZE_EVENT_SCRIPT`, when current job JSON is terminal, mark the event processed and `return 2`. When the job is updated, `return 1`; ownership or missing-job failures remain `0`.

Add:

```python
from enum import IntEnum, StrEnum


class FinalizationResult(IntEnum):
    STALE = 0
    UPDATED = 1
    ALREADY_TERMINAL = 2
```

Change `finalize_event` to:

```python
async def finalize_event(
    redis,
    event_id: str,
    owner_token: str,
    record: JobRecord,
) -> FinalizationResult:
    result = await redis.eval(
        FINALIZE_EVENT_SCRIPT,
        2,
        event_key(event_id),
        job_key(record.id),
        _processing_value(owner_token),
        record.model_dump_json(),
        remaining_ttl(record),
        EventClaim.PROCESSED.value,
        PROCESSED_EVENT_TTL_SECONDS,
    )
    return FinalizationResult(result)
```

Update `FakeRedis.eval` in `tests/conftest.py` to return `2` after marking an already-terminal job's event processed and `1` after writing a non-terminal job. This fake must mirror the Lua branch exactly.

- [ ] **Step 4: Write failing webhook event and redaction tests**

Extend `tests/test_webhooks.py` with `captured_events` assertions:

```python
def test_verified_webhook_emits_safe_type(monkeypatch, captured_events):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = send(client)
    verified = [record for record in captured_events if record["event"] == "webhook_verified"][-1]
    assert response.status_code == 200
    assert verified["webhook_type"] == "response.completed"
    serialized = json.dumps(captured_events)
    assert "test-signature" not in serialized
    assert "evt_1" not in serialized
    assert "resp_1" not in serialized


def test_invalid_signature_emits_rejected_event(monkeypatch, captured_events):
    redis = FakeRedis()
    openai = FakeOpenAI(webhook_error=InvalidWebhookSignatureError("secret-exception-text"))
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/openai",
            content=b'{"secret-body":true}',
            headers=SIGNED_HEADERS,
        )
    rejected = [record for record in captured_events if record["event"] == "webhook_rejected"][-1]
    assert response.status_code == 401
    assert rejected["status_code"] == 401
    assert rejected["error_category"] == "webhook_signature"
    assert "secret-exception-text" not in json.dumps(captured_events)
    assert "secret-body" not in json.dumps(captured_events)
```

Use the existing oversized fixed/chunked test to assert `request_too_large`. Extend completed processing to assert one `job_completed` with the wrapper job ID. Extend the late-terminal race to assert no `job_completed` event when finalization reports `ALREADY_TERMINAL`.

Import `json` in this test module. Reuse the existing `FakeRedis`, `FakeOpenAI`,
`event`, `seed_job`, `install`, `send`, and `completed_response` definitions;
do not create a second fixture layer.

- [ ] **Step 5: Run webhook tests and confirm missing-event failures**

Run:

```bash
uv run python -m pytest tests/test_webhook_service.py tests/test_webhooks.py -q
```

Expected: typed finalization tests pass after Step 3; event assertions fail because the route is not yet instrumented.

- [ ] **Step 6: Emit webhook events without logging raw delivery data**

Add a module logger in `app/api/webhooks.py`. Make `_invalid_signature` emit:

```python
log_event(
    logger,
    logging.WARNING,
    "webhook_rejected",
    status_code=401,
    error_category="webhook_signature",
)
```

Before returning 413, emit the same event with status 413 and category `request_too_large`. Immediately after `webhooks.unwrap` succeeds, emit:

```python
log_event(logger, logging.INFO, "webhook_verified", webhook_type=event.type)
```

Before completed-response retrieval, emit `openai_request_started` with operation `retrieve`; call:

```python
provider = await retry_async(
    lambda: request.app.state.openai.responses.retrieve(event.data.id),
    operation_name="retrieve",
)
request.state.openai_request_id = openai_request_id(provider)
```

Handle finalization explicitly:

```python
finalization = await finalize_event(redis, event.id, owner_token, record)
if finalization is FinalizationResult.STALE:
    raise HTTPException(status_code=503)
if target_status is JobStatus.COMPLETED and finalization is FinalizationResult.UPDATED:
    log_event(
        logger,
        logging.INFO,
        "job_completed",
        correlation_id=record.correlation_id,
        operation="retrieve",
        job_id=record.id,
        openai_request_id=openai_request_id(provider),
    )
```

Initialize `provider = None` before the terminal-type branch. Do not log `event.id`, `event.data.id`, the owner token, request headers, raw body, provider object, output text, or Redis exceptions.

In the webhook `except RedisError` branch, emit `request_failed` at error level
with `operation="webhook"`, `status_code=503`, and
`error_category="redis"` before releasing the owned claim and raising the
unchanged HTTP exception.

- [ ] **Step 7: Run all webhook and retry integration tests**

Run:

```bash
uv run python -m pytest tests/test_webhook_service.py tests/test_webhooks.py tests/test_retry.py tests/test_job_status.py -q
```

Expected: all tests pass; late terminal events stay absorbing and emit no false completion.

- [ ] **Step 8: Commit webhook observability**

```bash
git add app/services/webhooks.py app/api/webhooks.py tests/conftest.py tests/test_webhook_service.py tests/test_webhooks.py
git commit -m "feat: log webhook outcomes"
```

---

### Task 5: Learning documentation and complete verification

**Files:**
- Modify: `Learning/api-design.md`
- Modify: `Learning/questions-and-answers.md`
- Modify: `Learning/learning-path.md`

**Interfaces:**
- Documents the exact JSON contract implemented by Tasks 1-4.
- Adds no runtime behavior.

- [ ] **Step 1: Document the JSON contract and redaction boundary**

Add a concise logging section to `Learning/api-design.md` containing this example:

```json
{
  "timestamp": "2026-08-16T12:00:00.000Z",
  "level": "info",
  "event": "request_completed",
  "logger": "app.middleware.correlation",
  "correlation_id": "client.request-1",
  "method": "POST",
  "route": "/v1/responses",
  "status_code": 200,
  "duration_ms": 125.4
}
```

State that optional fields are omitted when unavailable, `LOG_LEVEL` applies to application/Uvicorn logs, and logs never contain secrets, headers, bodies, prompts, output, Redis contents, provider response IDs, webhook event IDs, query strings, or raw exception details.

- [ ] **Step 2: Add the learning explanation and mark the milestone complete**

Add to `Learning/questions-and-answers.md`:

```markdown
## Why use structured JSON instead of formatted log sentences?

Stable event and field names let log tools filter by correlation ID, route,
status, retry count, or error category without parsing human prose. A strict
field allowlist also makes the sensitive-data boundary testable.

## Why omit raw exception messages and request bodies?

Those values can contain credentials, prompts, model output, or upstream data.
The wrapper records a stable category and diagnostic request ID instead, which
supports investigation without copying sensitive content into logs.
```

Change the observability entry in `Learning/learning-path.md` to:

```markdown
15. **Observability (complete)** — emit safe structured application and Uvicorn
    events with correlation IDs, durations, retry counts, and error categories.
```

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
uv run python -m pytest
```

Expected: all tests pass; the count is at least the Phase 13 baseline of 137.

- [ ] **Step 4: Run static and diff verification**

Run:

```bash
uv run python -m compileall app tests
git diff --check
git status --short
git diff --stat main...HEAD
```

Expected: compilation and diff check exit zero; only Phase 14 files are changed.

- [ ] **Step 5: Audit log call sites for forbidden values**

Run:

```bash
rg -n "log_event|logger\." app
rg -n "Authorization|Idempotency-Key|webhook-signature|raw_body|output_text|model_dump|exc_info|stack_info" app/logging.py app/middleware app/api app/services/retry.py
```

Inspect every match. Confirm forbidden values appear only in request processing or explicit exclusion logic, never as a `log_event` argument or formatter output. Confirm no `logger.exception`, `exc_info=True`, arbitrary `record.__dict__`, or `default=str` serializer exists.

- [ ] **Step 6: Commit documentation**

```bash
git add Learning/api-design.md Learning/questions-and-answers.md Learning/learning-path.md
git commit -m "docs: record logging milestone"
```

- [ ] **Step 7: Request final code review**

Review `main...HEAD` against:

```text
docs/superpowers/specs/2026-08-16-phase-14-structured-json-logging-design.md
docs/superpowers/plans/2026-08-16-phase-14-structured-json-logging.md
```

Require zero Critical or Important findings before offering branch integration. Re-run the complete suite after any review fix.
