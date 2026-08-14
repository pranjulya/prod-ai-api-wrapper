# Phase 13 OpenAI Webhooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify OpenAI terminal-response webhooks, update Redis background jobs exactly once, and expose normalized completed output through polling.

**Architecture:** Process verified events inline and use Redis as the cross-instance coordination authority. Store a hashed OpenAI-response-to-job reverse index, claim each event with `SET NX EX`, retrieve completed responses through the existing bounded retry policy, then atomically update the job and mark the event processed.

**Tech Stack:** Python 3.12, FastAPI, OpenAI Python SDK 3.x, redis-py asyncio, Pydantic, pytest, HTTPX.

## Global Constraints

- Work only on `feature/phase-13-openai-webhooks`; do not implement Phase 14.
- Use `AsyncOpenAI.webhooks.unwrap` with the raw request body and headers.
- Keep OpenAI SDK retries disabled; wrapper retries remain capped at two retries (three total attempts).
- Do not add a queue, worker, in-process background task, or dependency.
- Missing or invalid signatures return correlated `401 invalid_webhook_signature` before Redis or response retrieval.
- Support only `response.completed`, `response.failed`, `response.cancelled`, and `response.incomplete`; acknowledge other verified events without mutation.
- Hash event IDs and OpenAI response IDs in Redis key names.
- Retain processed-event markers for at least 259,200 seconds.
- Terminal job states are absorbing; later terminal events cannot overwrite them.
- Never log secrets, signature headers, raw webhook bodies, prompts, model output, Redis values, or raw upstream exceptions.
- Tests use fake OpenAI and Redis implementations and never make billable requests.

---

### Task 1: Share response normalization and extend completed job output

**Files:**
- Create: `app/services/responses.py`
- Modify: `app/api/responses.py`
- Modify: `app/schemas/jobs.py`
- Modify: `tests/test_job_status.py`
- Test: `tests/test_responses.py`

**Interfaces:**
- Consumes: `ResponsesResponse`, `Usage`, and provider response attributes already used by `create_response`.
- Produces: `normalize_response(response, correlation_id: str) -> ResponsesResponse`; optional `model`, `output_text`, and `usage` fields on `JobRecord` and `BackgroundJobResponse`.

- [ ] **Step 1: Write the failing completed-result polling test**

Add this test to `tests/test_job_status.py`:

```python
from app.schemas.responses import Usage


def test_completed_job_returns_normalized_result(monkeypatch):
    redis = FakeRedis()
    completed = record(JobStatus.COMPLETED).model_copy(
        update={
            "model": "gpt-5-mini",
            "output_text": "finished",
            "usage": Usage(input_tokens=4, output_tokens=2, total_tokens=6),
        }
    )
    redis.values[job_key(JOB_ID)] = completed.model_dump_json()
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)

    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5-mini"
    assert response.json()["output_text"] == "finished"
    assert response.json()["usage"] == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
    }
```

Also extend `test_active_job_returns_202` with:

```python
    assert "model" not in response.json()
    assert "output_text" not in response.json()
    assert "usage" not in response.json()
```

- [ ] **Step 2: Run the focused tests and verify the new test fails**

Run:

```bash
uv run python -m pytest tests/test_job_status.py tests/test_responses.py -q
```

Expected: `test_completed_job_returns_normalized_result` fails because the job schemas do not accept or return the three result fields.

- [ ] **Step 3: Add the shared normalizer**

Create `app/services/responses.py`:

```python
import uuid

from app.schemas.responses import ResponsesResponse, Usage


def normalize_response(response, correlation_id: str) -> ResponsesResponse:
    provider_usage = getattr(response, "usage", None)
    return ResponsesResponse(
        id=f"wrp_resp_{uuid.uuid4()}",
        openai_response_id=getattr(response, "id", None),
        status=getattr(response, "status", None),
        model=getattr(response, "model", None),
        output_text=getattr(response, "output_text", None),
        usage=None
        if provider_usage is None
        else Usage(
            input_tokens=getattr(provider_usage, "input_tokens", None),
            output_tokens=getattr(provider_usage, "output_tokens", None),
            total_tokens=getattr(provider_usage, "total_tokens", None),
        ),
        correlation_id=correlation_id,
    )
```

In `app/api/responses.py`, import `normalize_response`, stop importing `Usage`, and replace the inline provider normalization block with:

```python
    normalized = normalize_response(response, request.state.correlation_id)
```

- [ ] **Step 4: Extend the job schemas and omit absent result fields**

In `app/schemas/jobs.py`, import `Usage` and add the same optional fields to both models:

```python
from app.schemas.responses import Usage


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    openai_response_id: str | None = None
    created_at: datetime
    expires_at: datetime
    status_url: str
    correlation_id: str
    model: str | None = None
    output_text: str | None = None
    usage: Usage | None = None


class BackgroundJobResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    expires_at: datetime
    status_url: str
    correlation_id: str
    model: str | None = None
    output_text: str | None = None
    usage: Usage | None = None
```

Set `response_model_exclude_none=True` on both background route decorators in `app/api/responses.py`:

```python
@router.post(
    "/responses/background",
    response_model=BackgroundJobResponse,
    response_model_exclude_none=True,
    status_code=202,
)

@router.get(
    "/responses/{job_id}",
    response_model=BackgroundJobResponse,
    response_model_exclude_none=True,
)
```

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run python -m pytest tests/test_job_status.py tests/test_responses.py -q
```

Expected: all focused tests pass and existing synchronous response JSON is unchanged.

Commit:

```bash
git add app/services/responses.py app/api/responses.py app/schemas/jobs.py tests/test_job_status.py
git commit -m "refactor: share response normalization"
```

---

### Task 2: Store the OpenAI-response-to-job reverse index atomically

**Files:**
- Modify: `app/services/jobs.py`
- Modify: `app/api/responses.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_jobs_service.py`
- Test: `tests/test_background_responses.py`

**Interfaces:**
- Consumes: `JobRecord`, existing `job_key`, and Redis transactional pipelines.
- Produces: `remaining_ttl(record: JobRecord) -> int`, `response_job_key(openai_response_id: str) -> str`, `update_job_with_response_id(redis, record: JobRecord) -> None`, and `get_job_id_by_response_id(redis, openai_response_id: str) -> str | None`.

- [ ] **Step 1: Write failing reverse-index tests**

Replace the file-local `FakeRedis` with `from conftest import FakeRedis`, change
its existing `redis.expiry[...]` assertion to `redis.expirations[...]`, and add
these imports and test to `tests/test_jobs_service.py`:

```python
from app.services.jobs import (
    get_job_id_by_response_id,
    response_job_key,
    update_job_with_response_id,
)


def test_response_reverse_index_is_atomic_hashed_and_expiring():
    redis = FakeRedis()
    now = datetime.now(timezone.utc)
    stored = JobRecord(
        id="job_reverse",
        status=JobStatus.IN_PROGRESS,
        openai_response_id="resp_private",
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status_url="/v1/responses/job_reverse",
        correlation_id="corr",
    )

    asyncio.run(update_job_with_response_id(redis, stored))

    assert redis.pipeline_calls == 1
    assert asyncio.run(get_job_id_by_response_id(redis, "resp_private")) == stored.id
    assert "resp_private" not in response_job_key("resp_private")
    assert redis.expirations[job_key(stored.id)] > 0
    assert redis.expirations[response_job_key("resp_private")] == redis.expirations[job_key(stored.id)]
```

- [ ] **Step 2: Run the service test and verify it fails**

Run:

```bash
uv run python -m pytest tests/test_jobs_service.py::test_response_reverse_index_is_atomic_hashed_and_expiring -q
```

Expected: collection fails because the reverse-index functions do not exist.

- [ ] **Step 3: Generalize the shared fake Redis pipeline**

In `tests/conftest.py`, add `self.expirations = {}` to `FakeRedis.__init__`, record `ex` in direct `set`, and add pipeline commands:

```python
    def set(self, key, value, nx=False, ex=None):
        self.commands.append(("set", key, value, nx, ex))

    def delete(self, key):
        self.commands.append(("delete", key))

    async def execute(self):
        results = []
        with self.redis_client.lock:
            for command in self.commands:
                if command[0] == "incr":
                    key = command[1]
                    value = self.redis_client.values.get(key, 0) + 1
                    self.redis_client.values[key] = value
                    results.append(value)
                elif command[0] == "expire":
                    _, key, seconds, _ = command
                    self.redis_client.expirations[key] = seconds
                    results.append(True)
                elif command[0] == "set":
                    _, key, value, nx, seconds = command
                    if nx and key in self.redis_client.values:
                        results.append(False)
                        continue
                    self.redis_client.values[key] = value
                    if seconds is not None:
                        self.redis_client.expirations[key] = seconds
                    results.append(True)
                elif command[0] == "delete":
                    self.redis_client.values.pop(command[1], None)
                    results.append(True)
        return results
```

Replace `FakeRedis.set` with:

```python
    async def set(self, key, value, nx=False, ex=None):
        with self.lock:
            if nx and key in self.values:
                return False
            self.values[key] = value
            if ex is not None:
                self.expirations[key] = ex
            return True
```

- [ ] **Step 4: Implement the reverse index**

In `app/services/jobs.py`, add:

```python
import hashlib


def remaining_ttl(record: JobRecord) -> int:
    return max(1, int((record.expires_at - datetime.now(timezone.utc)).total_seconds()))


def response_job_key(openai_response_id: str) -> str:
    digest = hashlib.sha256(openai_response_id.encode()).hexdigest()
    return f"wrapper:openai-response-job:{digest}"


async def update_job_with_response_id(redis, record: JobRecord) -> None:
    if record.openai_response_id is None:
        raise ValueError("OpenAI response ID is required")
    ttl = remaining_ttl(record)
    pipeline = redis.pipeline(transaction=True)
    pipeline.set(job_key(record.id), record.model_dump_json(), ex=ttl)
    pipeline.set(response_job_key(record.openai_response_id), record.id, ex=ttl)
    await pipeline.execute()


async def get_job_id_by_response_id(redis, openai_response_id: str) -> str | None:
    value = await redis.get(response_job_key(openai_response_id))
    if isinstance(value, bytes):
        return value.decode()
    return value
```

Change `update_job` to call `remaining_ttl(record)`. In `create_background_response`, replace `update_job` with `update_job_with_response_id` and update the import.

- [ ] **Step 5: Run affected tests and commit**

Run:

```bash
uv run python -m pytest tests/test_jobs_service.py tests/test_background_responses.py tests/test_rate_limiting.py -q
```

Expected: all affected tests pass, including the existing rate-limit pipeline behavior.

Commit:

```bash
git add app/services/jobs.py app/api/responses.py tests/conftest.py tests/test_jobs_service.py
git commit -m "feat: index background responses"
```

---

### Task 3: Coordinate webhook ownership and finalization in Redis

**Files:**
- Create: `app/services/webhooks.py`
- Create: `tests/test_webhook_service.py`
- Modify: `tests/conftest.py` only if the Task 2 fake pipeline needs a correction exposed by these tests.

**Interfaces:**
- Consumes: `job_key`, `remaining_ttl`, `JobRecord`, and Redis `SET NX EX` plus transactional pipelines.
- Produces: `EventClaim`, `event_key(event_id: str) -> str`, `processing_ttl(openai_timeout_seconds: int) -> int`, `claim_event`, `release_event`, `mark_processed`, and `finalize_event`.

- [ ] **Step 1: Write failing coordination tests**

Create `tests/test_webhook_service.py`:

```python
import asyncio
from datetime import datetime, timedelta, timezone

from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import job_key
from app.services.webhooks import (
    PROCESSED_EVENT_TTL_SECONDS,
    EventClaim,
    claim_event,
    event_key,
    finalize_event,
    processing_ttl,
    release_event,
)
from conftest import FakeRedis


def record(status):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id="job_webhook",
        status=status,
        openai_response_id="resp_webhook",
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status_url="/v1/responses/job_webhook",
        correlation_id="corr",
    )


def test_event_claim_distinguishes_owner_processing_and_processed():
    redis = FakeRedis()
    assert asyncio.run(claim_event(redis, "evt_private", 100)) is EventClaim.ACQUIRED
    assert asyncio.run(claim_event(redis, "evt_private", 100)) is EventClaim.PROCESSING
    redis.values[event_key("evt_private")] = "processed"
    assert asyncio.run(claim_event(redis, "evt_private", 100)) is EventClaim.PROCESSED
    assert "evt_private" not in event_key("evt_private")


def test_failed_claim_can_be_released():
    redis = FakeRedis()
    assert asyncio.run(claim_event(redis, "evt_retry", 100)) is EventClaim.ACQUIRED
    asyncio.run(release_event(redis, "evt_retry"))
    assert asyncio.run(claim_event(redis, "evt_retry", 100)) is EventClaim.ACQUIRED


def test_finalization_updates_job_and_event_atomically():
    redis = FakeRedis()
    completed = record(JobStatus.COMPLETED)
    asyncio.run(finalize_event(redis, "evt_done", completed))

    assert redis.pipeline_calls == 1
    assert redis.values[event_key("evt_done")] == "processed"
    assert redis.expirations[event_key("evt_done")] == PROCESSED_EVENT_TTL_SECONDS
    assert redis.values[job_key(completed.id)] == completed.model_dump_json()


def test_processing_ttl_covers_all_provider_attempts():
    assert processing_ttl(30) == 100
    assert processing_ttl(5) == 60
```

- [ ] **Step 2: Run the tests and verify collection fails**

Run:

```bash
uv run python -m pytest tests/test_webhook_service.py -q
```

Expected: collection fails because `app.services.webhooks` does not exist.

- [ ] **Step 3: Implement the Redis webhook service**

Create `app/services/webhooks.py`:

```python
import hashlib
from enum import StrEnum

from app.schemas.jobs import JobRecord
from app.services.jobs import job_key, remaining_ttl


PROCESSED_EVENT_TTL_SECONDS = 259_200


class EventClaim(StrEnum):
    ACQUIRED = "acquired"
    PROCESSING = "processing"
    PROCESSED = "processed"


def event_key(event_id: str) -> str:
    digest = hashlib.sha256(event_id.encode()).hexdigest()
    return f"wrapper:webhook:event:{digest}"


def processing_ttl(openai_timeout_seconds: int) -> int:
    return max(60, 3 * openai_timeout_seconds + 10)


async def claim_event(redis, event_id: str, ttl_seconds: int) -> EventClaim:
    key = event_key(event_id)
    if await redis.set(key, EventClaim.PROCESSING.value, nx=True, ex=ttl_seconds):
        return EventClaim.ACQUIRED
    value = await redis.get(key)
    if isinstance(value, bytes):
        value = value.decode()
    return EventClaim.PROCESSED if value == EventClaim.PROCESSED.value else EventClaim.PROCESSING


async def release_event(redis, event_id: str) -> None:
    await redis.delete(event_key(event_id))


async def mark_processed(redis, event_id: str) -> None:
    await redis.set(
        event_key(event_id),
        EventClaim.PROCESSED.value,
        ex=PROCESSED_EVENT_TTL_SECONDS,
    )


async def finalize_event(redis, event_id: str, record: JobRecord) -> None:
    pipeline = redis.pipeline(transaction=True)
    pipeline.set(
        job_key(record.id),
        record.model_dump_json(),
        ex=remaining_ttl(record),
    )
    pipeline.set(
        event_key(event_id),
        EventClaim.PROCESSED.value,
        ex=PROCESSED_EVENT_TTL_SECONDS,
    )
    await pipeline.execute()
```

- [ ] **Step 4: Run service and regression tests**

Run:

```bash
uv run python -m pytest tests/test_webhook_service.py tests/test_jobs_service.py tests/test_rate_limiting.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/webhooks.py tests/test_webhook_service.py tests/conftest.py
git commit -m "feat: coordinate webhook events"
```

---

### Task 4: Verify and process OpenAI webhook requests

**Files:**
- Create: `app/api/webhooks.py`
- Modify: `app/main.py`
- Modify: `app/clients/openai_client.py`
- Modify: `tests/test_openai_lifecycle.py`
- Create: `tests/test_webhooks.py`
- Test: `tests/test_authentication.py`
- Test: `tests/test_rate_limiting.py`

**Interfaces:**
- Consumes: `AsyncOpenAI.webhooks.unwrap`, `normalize_response`, job reverse lookup, `EventClaim`, and webhook finalization functions from Tasks 1-3.
- Produces: `POST /webhooks/openai -> {"received": true}` with verified, retry-safe terminal processing.

- [ ] **Step 1: Add failing client-configuration and route tests**

Extend `test_openai_sdk_retries_are_disabled` in `tests/test_openai_lifecycle.py`:

```python
        assert client.webhook_secret == "test-webhook-secret"
```

Create `tests/test_webhooks.py` with reusable fakes and the first two boundary tests:

```python
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError, InvalidWebhookSignatureError
from redis.exceptions import ConnectionError

from app.main import create_app
from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import job_key, response_job_key
from app.services.webhooks import event_key
from conftest import FakeRedis


JOB_ID = "job_00000000-0000-4000-8000-000000000000"


class FakeWebhooks:
    def __init__(self, event=None, error=None):
        self.event = event
        self.error = error
        self.calls = []

    def unwrap(self, body, headers):
        self.calls.append((body, headers))
        if self.error:
            raise self.error
        return self.event


class FakeResponses:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.retrieve_calls = []

    async def retrieve(self, response_id):
        self.retrieve_calls.append(response_id)
        if self.error:
            raise self.error
        return self.result


class FakeOpenAI:
    def __init__(self, event=None, result=None, webhook_error=None, response_error=None):
        self.webhooks = FakeWebhooks(event, webhook_error)
        self.responses = FakeResponses(result, response_error)

    async def close(self):
        pass


def event(event_id="evt_1", event_type="response.completed", response_id="resp_1"):
    return SimpleNamespace(
        id=event_id,
        type=event_type,
        data=SimpleNamespace(id=response_id),
    )


def job(status=JobStatus.IN_PROGRESS):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id=JOB_ID,
        status=status,
        openai_response_id="resp_1",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        status_url=f"/v1/responses/{JOB_ID}",
        correlation_id="background-correlation",
    )


def install(monkeypatch, redis, openai):
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)


def test_invalid_signature_is_rejected_before_state_access(monkeypatch):
    redis = FakeRedis()
    openai = FakeOpenAI(webhook_error=InvalidWebhookSignatureError("bad"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/openai",
            content=b'{"signed":true}',
            headers={"X-Correlation-ID": "webhook-correlation"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_signature"
    assert response.json()["error"]["correlation_id"] == "webhook-correlation"
    assert redis.values == {}
    assert openai.responses.retrieve_calls == []


def test_missing_signature_is_rejected_by_the_real_sdk():
    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b'{}')

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_signature"


def test_verified_unsupported_event_is_acknowledged_without_state_change(monkeypatch):
    redis = FakeRedis()
    openai = FakeOpenAI(event=event(event_type="batch.completed"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/openai",
            content=b"raw-body",
            headers={"webhook-id": "wh_test"},
        )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert openai.webhooks.calls[0][0] == b"raw-body"
    assert openai.webhooks.calls[0][1]["webhook-id"] == "wh_test"
    assert redis.values == {}
    assert redis.pipeline_calls == 0
```

- [ ] **Step 2: Add failing terminal, duplicate, race, and failure tests**

Add these exact test cases to `tests/test_webhooks.py`:

```python
def seed_job(redis, record=None):
    record = record or job()
    redis.values[job_key(record.id)] = record.model_dump_json()
    redis.values[response_job_key("resp_1")] = record.id
    return record


def completed_response():
    usage = SimpleNamespace(input_tokens=5, output_tokens=3, total_tokens=8)
    return SimpleNamespace(
        id="resp_1",
        status="completed",
        model="gpt-5-mini",
        output_text="done",
        usage=usage,
    )


def test_completed_event_updates_polling_result_once(monkeypatch):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        first = client.post("/webhooks/openai", content=b"raw")
        second = client.post("/webhooks/openai", content=b"raw")
        polled = client.get(
            f"/v1/responses/{JOB_ID}",
            headers={"Authorization": "Bearer test-wrapper-key"},
        )

    assert first.status_code == second.status_code == 200
    assert openai.responses.retrieve_calls == ["resp_1"]
    assert polled.json()["status"] == "completed"
    assert polled.json()["model"] == "gpt-5-mini"
    assert polled.json()["output_text"] == "done"
    assert polled.json()["usage"]["total_tokens"] == 8


def test_unknown_response_is_retryable_and_released(monkeypatch):
    redis = FakeRedis()
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        first = client.post("/webhooks/openai", content=b"raw")
        seed_job(redis)
        second = client.post("/webhooks/openai", content=b"raw")

    assert first.status_code == 503
    assert second.status_code == 200


def test_later_terminal_event_does_not_overwrite_completed_job(monkeypatch):
    redis = FakeRedis()
    seed_job(redis, job(JobStatus.COMPLETED).model_copy(update={"output_text": "kept"}))
    openai = FakeOpenAI(event=event(event_id="evt_late", event_type="response.failed"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    stored = JobRecord.model_validate_json(redis.values[job_key(JOB_ID)])
    assert response.status_code == 200
    assert stored.status is JobStatus.COMPLETED
    assert stored.output_text == "kept"
    assert openai.responses.retrieve_calls == []
```

Add the remaining terminal, ownership, Redis, and timeout cases:

```python
@pytest.mark.parametrize(
    ("event_type", "expected_status"),
    [
        ("response.failed", JobStatus.FAILED),
        ("response.cancelled", JobStatus.CANCELLED),
        ("response.incomplete", JobStatus.INCOMPLETE),
    ],
)
def test_non_completed_terminal_events_do_not_retrieve(
    monkeypatch, event_type, expected_status
):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(event_type=event_type))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    stored = JobRecord.model_validate_json(redis.values[job_key(JOB_ID)])
    assert response.status_code == 200
    assert stored.status is expected_status
    assert openai.responses.retrieve_calls == []


def test_concurrent_owner_returns_retryable_503(monkeypatch):
    redis = FakeRedis()
    redis.values[event_key("evt_1")] = "processing"
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    assert response.status_code == 503
    assert openai.responses.retrieve_calls == []


def test_redis_failure_returns_retryable_503(monkeypatch):
    class ErrorRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise ConnectionError("offline")

    redis = ErrorRedis()
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_retrieval_timeout_returns_504_and_releases_claim(monkeypatch):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(
        event=event(),
        response_error=APITimeoutError(request=None),
    )
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert event_key("evt_1") not in redis.values


def test_transient_retrieval_exhaustion_returns_503_and_releases_claim(monkeypatch):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(
        event=event(),
        response_error=APIConnectionError(request=None),
    )
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert event_key("evt_1") not in redis.values


def test_transient_retrieval_is_retried_then_completed(monkeypatch):
    class FlakyResponses(FakeResponses):
        async def retrieve(self, response_id):
            self.retrieve_calls.append(response_id)
            if len(self.retrieve_calls) == 1:
                raise APIConnectionError(request=None)
            return self.result

    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    openai.responses = FlakyResponses(result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"raw")

    assert response.status_code == 200
    assert openai.responses.retrieve_calls == ["resp_1", "resp_1"]
```

Update the two pre-route expectations in `tests/test_authentication.py`.
The webhook entry in `test_framework_errors_are_correlated_standard_errors`
must now expect `401` instead of `404`, and the dedicated exemption test becomes:

```python
def test_webhook_path_is_exempt_from_wrapper_authentication():
    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_signature"
    assert response.headers["X-Correlation-ID"]
```

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
uv run python -m pytest tests/test_webhooks.py tests/test_openai_lifecycle.py -q
```

Expected: failures because the client lacks `webhook_secret` and the route does not exist.

- [ ] **Step 4: Configure the SDK and register the route**

Add this argument in `create_openai_client`:

```python
        webhook_secret=settings.openai_webhook_secret,
```

Create `app/api/webhooks.py` with the verified inline processor:

```python
from fastapi import APIRouter, HTTPException, Request
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InvalidWebhookSignatureError,
    RateLimitError,
)
from redis.exceptions import RedisError

from app.errors import error_response
from app.schemas.jobs import JobStatus
from app.services.jobs import get_job, get_job_id_by_response_id
from app.services.responses import normalize_response
from app.services.retry import retry_async
from app.services.webhooks import (
    EventClaim,
    claim_event,
    finalize_event,
    mark_processed,
    processing_ttl,
    release_event,
)


router = APIRouter()
EVENT_STATUSES = {
    "response.completed": JobStatus.COMPLETED,
    "response.failed": JobStatus.FAILED,
    "response.cancelled": JobStatus.CANCELLED,
    "response.incomplete": JobStatus.INCOMPLETE,
}
TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.INCOMPLETE,
    JobStatus.EXPIRED,
}


async def _release_safely(redis, event_id: str) -> None:
    try:
        await release_event(redis, event_id)
    except RedisError:
        pass


@router.post("/openai")
async def receive_openai_webhook(request: Request):
    raw_body = await request.body()
    try:
        event = request.app.state.openai.webhooks.unwrap(raw_body, request.headers)
    except InvalidWebhookSignatureError:
        return error_response(
            401,
            "invalid_webhook_signature",
            "Webhook signature verification failed.",
            request.state.correlation_id,
        )

    target_status = EVENT_STATUSES.get(event.type)
    if target_status is None:
        return {"received": True}

    redis = request.app.state.redis
    claimed = False
    try:
        claim = await claim_event(
            redis,
            event.id,
            processing_ttl(request.app.state.settings.openai_timeout_seconds),
        )
        if claim is EventClaim.PROCESSED:
            return {"received": True}
        if claim is EventClaim.PROCESSING:
            raise HTTPException(status_code=503)
        claimed = True

        job_id = await get_job_id_by_response_id(redis, event.data.id)
        record = None if job_id is None else await get_job(redis, job_id)
        if record is None:
            await release_event(redis, event.id)
            claimed = False
            raise HTTPException(status_code=503)

        if record.status in TERMINAL_STATUSES:
            await mark_processed(redis, event.id)
            claimed = False
            return {"received": True}

        if target_status is JobStatus.COMPLETED:
            provider = await retry_async(
                lambda: request.app.state.openai.responses.retrieve(event.data.id)
            )
            if getattr(provider, "status", None) != "completed":
                await release_event(redis, event.id)
                claimed = False
                raise HTTPException(status_code=503)
            normalized = normalize_response(provider, record.correlation_id)
            record = record.model_copy(
                update={
                    "status": JobStatus.COMPLETED,
                    "model": normalized.model,
                    "output_text": normalized.output_text,
                    "usage": normalized.usage,
                }
            )
        else:
            record = record.model_copy(update={"status": target_status})

        await finalize_event(redis, event.id, record)
        claimed = False
        return {"received": True}
    except RedisError:
        if claimed:
            await _release_safely(redis, event.id)
        raise HTTPException(status_code=503) from None
    except APITimeoutError:
        if claimed:
            await _release_safely(redis, event.id)
        raise HTTPException(status_code=504) from None
    except (APIConnectionError, AuthenticationError, RateLimitError):
        if claimed:
            await _release_safely(redis, event.id)
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        if claimed:
            await _release_safely(redis, event.id)
        if error.status_code >= 500:
            raise HTTPException(status_code=503) from None
        raise
    except Exception:
        if claimed:
            await _release_safely(redis, event.id)
        raise
```

Register it in `app/main.py`:

```python
from app.api.webhooks import router as webhooks_router

app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
```

- [ ] **Step 5: Run webhook, middleware, and provider-error tests**

Run:

```bash
uv run python -m pytest tests/test_webhooks.py tests/test_openai_lifecycle.py tests/test_authentication.py tests/test_rate_limiting.py tests/test_retry.py -q
```

Expected: all focused tests pass; webhook calls require no wrapper bearer key and consume no rate-limit counter.

- [ ] **Step 6: Commit**

```bash
git add app/api/webhooks.py app/main.py app/clients/openai_client.py tests/test_openai_lifecycle.py tests/test_webhooks.py tests/test_authentication.py
git commit -m "feat: process OpenAI webhooks"
```

---

### Task 5: Document the milestone and verify the complete phase

**Files:**
- Modify: `Learning/api-design.md`
- Modify: `Learning/questions-and-answers.md`
- Modify: `Learning/learning-path.md`

**Interfaces:**
- Consumes: the completed Phase 13 behavior from Tasks 1-4.
- Produces: an accurate public contract and learning record; no runtime interface.

- [ ] **Step 1: Update the API contract**

In `Learning/api-design.md`, extend the background-job section with a completed example containing `model`, `output_text`, and `usage`. State explicitly that webhook requests use the raw body, valid signatures return `200 {"received": true}`, invalid signatures return `401 invalid_webhook_signature`, and temporary processing failures return retryable `503` or `504` errors.

- [ ] **Step 2: Record the operational decisions**

Add these questions and concrete answers to `Learning/questions-and-answers.md`:

```markdown
## Why verify a webhook before parsing or updating Redis?

The signature covers the raw body and delivery headers. Verifying first prevents
a forged request from selecting a job, triggering OpenAI retrieval, or changing
shared state.

## Why keep processed webhook event IDs in Redis?

OpenAI can deliver the same event more than once. A shared atomic Redis claim
makes duplicate delivery harmless across workers and API instances, while a
short processing state allows recovery after an interrupted attempt.

## Why return an error instead of acknowledging temporary webhook failures?

A successful response tells OpenAI that delivery is complete. Returning a safe
non-2xx response when Redis or retrieval is unavailable preserves OpenAI's retry
mechanism and prevents accepted events from being lost.
```

Change the webhook learning-path entry to:

```markdown
14. **Webhooks (complete)** — verify OpenAI events, deduplicate delivery in
    Redis, and update terminal jobs exactly once.
```

- [ ] **Step 3: Run complete verification**

Run:

```bash
uv run python -m pytest
uv run python -m compileall app tests
git diff --check
```

Expected: the full suite passes, compilation succeeds, and the diff check emits no errors.

- [ ] **Step 4: Review the final diff against the design**

Run:

```bash
git status --short
git diff --stat main...HEAD
git diff main -- app tests Learning
```

Confirm every Phase 13 requirement has an implementation and test, no Phase 14 structured logging was added, no secret or raw webhook payload appears in logs, and no real OpenAI request exists in tests.

- [ ] **Step 5: Commit documentation**

```bash
git add Learning/api-design.md Learning/questions-and-answers.md Learning/learning-path.md
git commit -m "docs: record webhook milestone"
```
