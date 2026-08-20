# Background Job Poll Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make authenticated background-job polling recover terminal OpenAI responses when webhook delivery is missing, without allowing concurrent polling to overwrite terminal state or stampede OpenAI.

**Architecture:** The status handler remains Redis-first and uses a hashed per-job Redis lease before retrieving a non-terminal OpenAI response. A focused reconciliation service owns provider-to-job mapping, lease cooldown, and terminal-absorbing Redis writes; the webhook path reuses the same mapping while retaining its atomic event finalizer.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, OpenAI Python SDK, async Redis, Redis Lua, pytest, `uv`

## Global Constraints

- Work only on `fix/background-job-reconciliation`; do not commit directly to `main`.
- Use TDD for every behavior: observe the focused test fail before adding implementation.
- Webhooks remain the fast path; polling is a recovery path.
- Terminal jobs, expired jobs, and jobs without `openai_response_id` never contact OpenAI.
- Timeout, connection failure, `429`, and provider `5xx` return the cached non-terminal job with HTTP `202`.
- Provider `404` stores terminal `failed` with code `background_response_unavailable` and message `Background response is no longer available.`
- Provider authentication and other permanent `4xx` errors preserve the job and use existing safe error contracts.
- Redis failures continue to return the existing safe HTTP `503` contract.
- The first terminal update wins across polling and webhook races.
- Do not log provider response IDs, webhook event IDs, prompts, output, raw exceptions, credentials, headers, or Redis contents.
- Add no dependency, worker, queue, endpoint, or configuration variable.
- Preserve the unrelated untracked `Learning/build_study_guide_pdf.py` and `Learning/interview-study-guide.pdf` files.

## File Map

- Create `app/services/job_reconciliation.py`: provider status mapping, terminal-state constants, per-job reconciliation lease/cooldown, and atomic job reconciliation.
- Create `tests/test_job_reconciliation.py`: unit coverage for mapping, lease ownership, hashed keys, cooldown, TTL preservation, and terminal-state absorption.
- Modify `app/schemas/jobs.py`: add the optional typed public background-job error.
- Modify `app/api/responses.py`: Redis-first polling fallback and approved provider-error behavior.
- Modify `app/api/webhooks.py`: reuse shared transition logic and terminal constants.
- Modify `tests/conftest.py`: emulate only the two new Redis Lua scripts used by production code.
- Modify `tests/test_job_status.py`: endpoint recovery, cooldown, error mapping, correlation, and log-safety coverage.
- Modify `tests/test_webhooks.py`: verify webhook behavior remains unchanged after shared mapping.
- Modify `tests/test_webhook_service.py`: verify webhook/poller terminal races.
- Modify `Learning/api-design.md`: document polling reconciliation and the safe terminal missing-response error.
- Modify `Learning/questions-and-answers.md`: replace the obsolete claim that status polling reads only Redis.

---

### Task 1: Typed Error and Shared Job Transitions

**Files:**
- Create: `app/services/job_reconciliation.py`
- Create: `tests/test_job_reconciliation.py`
- Modify: `app/schemas/jobs.py:19-41`

**Interfaces:**
- Consumes: `JobRecord`, `JobStatus`, `normalize_response(response, correlation_id)`.
- Produces: `TERMINAL_STATUSES: frozenset[JobStatus]`, `apply_job_transition(record, status, provider=None, error=None) -> JobRecord`, and `transition_from_provider(record, provider) -> JobRecord | None`.

- [ ] **Step 1: Write failing schema and transition tests**

Create `tests/test_job_reconciliation.py` with deterministic `JobRecord` and provider fixtures, then add these tests:

```python
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.schemas.jobs import BackgroundJobError, BackgroundJobResponse, JobRecord, JobStatus
from app.services.job_reconciliation import apply_job_transition, transition_from_provider


def record(status=JobStatus.IN_PROGRESS):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id="job_test",
        status=status,
        openai_response_id="resp_private",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        status_url="/v1/responses/job_test",
        correlation_id="corr-original",
    )


def provider(status, *, output_text=None):
    return SimpleNamespace(
        id="resp_private",
        status=status,
        model="gpt-5-mini",
        output_text=output_text,
        usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
    )


def test_background_error_is_typed_and_optional():
    failed = record(JobStatus.FAILED).model_copy(
        update={"error": BackgroundJobError(code="safe", message="Safe message.")}
    )
    public = BackgroundJobResponse.model_validate(failed, from_attributes=True)
    assert public.error.model_dump() == {"code": "safe", "message": "Safe message."}
    assert BackgroundJobResponse.model_validate(record(), from_attributes=True).error is None


def test_completed_provider_is_normalized_into_job():
    updated = transition_from_provider(record(), provider("completed", output_text="done"))
    assert updated is not None
    assert updated.status is JobStatus.COMPLETED
    assert updated.model == "gpt-5-mini"
    assert updated.output_text == "done"
    assert updated.usage.total_tokens == 6
    assert updated.correlation_id == "corr-original"


def test_provider_status_mapping_and_unknown_status():
    expected = {
        "queued": JobStatus.PENDING,
        "in_progress": JobStatus.IN_PROGRESS,
        "failed": JobStatus.FAILED,
        "cancelled": JobStatus.CANCELLED,
        "incomplete": JobStatus.INCOMPLETE,
    }
    for provider_status, local_status in expected.items():
        assert transition_from_provider(record(), provider(provider_status)).status is local_status
    assert transition_from_provider(record(), provider("future_status")) is None


def test_explicit_transition_supports_webhook_terminal_status():
    assert apply_job_transition(record(), JobStatus.FAILED).status is JobStatus.FAILED
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest tests/test_job_reconciliation.py -q`

Expected: collection fails because `BackgroundJobError` and `app.services.job_reconciliation` do not exist.

- [ ] **Step 3: Add the typed optional error**

In `app/schemas/jobs.py`, add the model and the same optional field to both stored and public job models:

```python
class BackgroundJobError(BaseModel):
    code: str
    message: str


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
    error: BackgroundJobError | None = None


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
    error: BackgroundJobError | None = None
```

- [ ] **Step 4: Implement the minimum shared transition service**

Create `app/services/job_reconciliation.py`:

```python
from app.schemas.jobs import BackgroundJobError, JobRecord, JobStatus
from app.services.responses import normalize_response


TERMINAL_STATUSES = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.INCOMPLETE,
        JobStatus.EXPIRED,
    }
)
PROVIDER_STATUSES = {
    "queued": JobStatus.PENDING,
    "in_progress": JobStatus.IN_PROGRESS,
    "completed": JobStatus.COMPLETED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
    "incomplete": JobStatus.INCOMPLETE,
}


def apply_job_transition(
    record: JobRecord,
    status: JobStatus,
    *,
    provider=None,
    error: BackgroundJobError | None = None,
) -> JobRecord:
    updates = {"status": status, "error": error}
    if status is JobStatus.COMPLETED:
        if provider is None or getattr(provider, "status", None) != "completed":
            raise ValueError("Completed transition requires a completed provider response")
        normalized = normalize_response(provider, record.correlation_id)
        updates.update(
            model=normalized.model,
            output_text=normalized.output_text,
            usage=normalized.usage,
        )
    return record.model_copy(update=updates)


def transition_from_provider(record: JobRecord, provider) -> JobRecord | None:
    status = PROVIDER_STATUSES.get(getattr(provider, "status", None))
    if status is None:
        return None
    return apply_job_transition(record, status, provider=provider if status is JobStatus.COMPLETED else None)
```

- [ ] **Step 5: Run focused and existing schema/status tests**

Run: `uv run pytest tests/test_job_reconciliation.py tests/test_job_status.py tests/test_webhooks.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add app/schemas/jobs.py app/services/job_reconciliation.py tests/test_job_reconciliation.py
git commit -m "feat(jobs): share provider transitions"
```

---

### Task 2: Redis Reconciliation Coordination

**Files:**
- Modify: `app/services/job_reconciliation.py`
- Modify: `tests/test_job_reconciliation.py`
- Modify: `tests/conftest.py:70-118`

**Interfaces:**
- Consumes: `job_key(record.id)`, `remaining_ttl(record)`, and the Task 1 transition functions.
- Produces: `reconciliation_key(job_id) -> str`, `claim_reconciliation(redis, job_id, owner_token, ttl_seconds) -> bool`, `finish_reconciliation(redis, job_id, owner_token) -> bool`, `write_reconciled_job(redis, record) -> JobWriteResult`, `RECONCILIATION_COOLDOWN_SECONDS = 5`, and `JobWriteResult` values `MISSING`, `UPDATED`, `ALREADY_TERMINAL`.

- [ ] **Step 1: Add failing lease and atomic-write tests**

Append to `tests/test_job_reconciliation.py`:

```python
import asyncio

from app.services.job_reconciliation import (
    RECONCILIATION_COOLDOWN_SECONDS,
    JobWriteResult,
    claim_reconciliation,
    finish_reconciliation,
    reconciliation_key,
    write_reconciled_job,
)
from app.services.jobs import job_key
from conftest import FakeRedis


def test_reconciliation_lease_is_hashed_owned_and_cooled_down():
    redis = FakeRedis()
    key = reconciliation_key("job_private")
    assert "job_private" not in key
    assert asyncio.run(claim_reconciliation(redis, "job_private", "owner-a", 100)) is True
    assert asyncio.run(claim_reconciliation(redis, "job_private", "owner-b", 100)) is False
    assert asyncio.run(finish_reconciliation(redis, "job_private", "owner-b")) is False
    assert asyncio.run(finish_reconciliation(redis, "job_private", "owner-a")) is True
    assert redis.values[key] == "cooldown"
    assert redis.expirations[key] == RECONCILIATION_COOLDOWN_SECONDS


def test_atomic_reconciliation_preserves_first_terminal_state():
    redis = FakeRedis()
    active = record()
    redis.values[job_key(active.id)] = active.model_dump_json()
    failed = apply_job_transition(active, JobStatus.FAILED)
    completed = apply_job_transition(active, JobStatus.COMPLETED, provider=provider("completed"))

    assert asyncio.run(write_reconciled_job(redis, failed)) is JobWriteResult.UPDATED
    assert asyncio.run(write_reconciled_job(redis, completed)) is JobWriteResult.ALREADY_TERMINAL
    stored = JobRecord.model_validate_json(redis.values[job_key(active.id)])
    assert stored.status is JobStatus.FAILED


def test_atomic_reconciliation_reports_missing_job():
    assert asyncio.run(write_reconciled_job(FakeRedis(), record())) is JobWriteResult.MISSING
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest tests/test_job_reconciliation.py -q`

Expected: import errors for the new coordination interfaces.

- [ ] **Step 3: Implement the lease, cooldown, and terminal-absorbing write**

Add to `app/services/job_reconciliation.py`:

```python
import hashlib
from enum import IntEnum

from app.services.jobs import job_key, remaining_ttl


RECONCILIATION_COOLDOWN_SECONDS = 5
FINISH_RECONCILIATION_SCRIPT = """-- finish-job-reconciliation
if redis.call("GET", KEYS[1]) ~= ARGV[1] then return 0 end
redis.call("SET", KEYS[1], ARGV[2], "EX", tonumber(ARGV[3]))
return 1
"""
WRITE_RECONCILED_JOB_SCRIPT = """-- write-reconciled-job
local current = redis.call("GET", KEYS[1])
if not current then return 0 end
local status = cjson.decode(current)["status"]
if status == "completed" or status == "failed" or status == "cancelled"
   or status == "incomplete" or status == "expired" then return 2 end
redis.call("SET", KEYS[1], ARGV[1], "EX", tonumber(ARGV[2]))
return 1
"""


class JobWriteResult(IntEnum):
    MISSING = 0
    UPDATED = 1
    ALREADY_TERMINAL = 2


def reconciliation_key(job_id: str) -> str:
    digest = hashlib.sha256(job_id.encode()).hexdigest()
    return f"wrapper:job-reconciliation:{digest}"


def _processing_value(owner_token: str) -> str:
    return f"processing:{owner_token}"


async def claim_reconciliation(redis, job_id: str, owner_token: str, ttl_seconds: int) -> bool:
    return bool(
        await redis.set(
            reconciliation_key(job_id),
            _processing_value(owner_token),
            nx=True,
            ex=ttl_seconds,
        )
    )


async def finish_reconciliation(redis, job_id: str, owner_token: str) -> bool:
    result = await redis.eval(
        FINISH_RECONCILIATION_SCRIPT,
        1,
        reconciliation_key(job_id),
        _processing_value(owner_token),
        "cooldown",
        RECONCILIATION_COOLDOWN_SECONDS,
    )
    return bool(result)


async def write_reconciled_job(redis, record: JobRecord) -> JobWriteResult:
    result = await redis.eval(
        WRITE_RECONCILED_JOB_SCRIPT,
        1,
        job_key(record.id),
        record.model_dump_json(),
        remaining_ttl(record),
    )
    return JobWriteResult(result)
```

- [ ] **Step 4: Teach `FakeRedis.eval` only the two production scripts**

In `tests/conftest.py`, add branches matching `-- finish-job-reconciliation` and `-- write-reconciled-job`. Mirror the Lua ownership check, terminal-status set, serialized write, and integer return values exactly. Do not add a generic Lua interpreter.

```python
if script.startswith("-- finish-job-reconciliation"):
    key = keys[0]
    owner, cooldown, cooldown_ttl = values
    if self.values.get(key) != owner:
        return 0
    self.values[key] = cooldown
    self.expirations[key] = int(cooldown_ttl)
    return 1
if script.startswith("-- write-reconciled-job"):
    stored_job_key = keys[0]
    serialized_job, job_ttl = values
    current = self.values.get(stored_job_key)
    if current is None:
        return 0
    if isinstance(current, bytes):
        current = current.decode()
    if json.loads(current)["status"] in {
        "completed", "failed", "cancelled", "incomplete", "expired"
    }:
        return 2
    self.values[stored_job_key] = serialized_job
    self.expirations[stored_job_key] = int(job_ttl)
    return 1
```

- [ ] **Step 5: Run coordination and existing Redis tests**

Run: `uv run pytest tests/test_job_reconciliation.py tests/test_jobs_service.py tests/test_webhook_service.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add app/services/job_reconciliation.py tests/test_job_reconciliation.py tests/conftest.py
git commit -m "feat(jobs): coordinate poll reconciliation"
```

---

### Task 3: Status Poll Recovery Path

**Files:**
- Modify: `app/api/responses.py:225-242`
- Modify: `tests/test_job_status.py`

**Interfaces:**
- Consumes: all Task 2 reconciliation interfaces plus existing `processing_ttl`, `retry_async`, `openai_request_id`, and `get_job`.
- Produces: Redis-first status polling that retrieves OpenAI only while holding the per-job reconciliation lease.

- [ ] **Step 1: Replace the obsolete no-provider-call assertion with failing recovery tests**

Replace the current counter-only `FakeOpenAI` in `tests/test_job_status.py` with these test doubles and helpers:

```python
import asyncio
from types import SimpleNamespace


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    async def retrieve(self, response_id):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeOpenAI:
    def __init__(self, outcomes=()):
        self.responses = FakeResponses(outcomes)

    async def close(self):
        pass


def completed_response():
    return SimpleNamespace(
        id="resp_private",
        _request_id="req_poll",
        status="completed",
        model="gpt-5-mini",
        output_text="finished",
        usage=SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
    )


def install(monkeypatch, redis, openai):
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)
```

Replace `test_active_job_returns_202` with a provider-ID-less cached test and add the recovery and claimed-lease tests:

```python
def test_nonterminal_job_without_provider_id_returns_cached_202(monkeypatch):
    redis = FakeRedis()
    cached = record(JobStatus.PENDING).model_copy(update={"openai_response_id": None})
    redis.values[job_key(JOB_ID)] = cached.model_dump_json()
    openai = FakeOpenAI([])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert openai.responses.calls == 0


def test_poll_recovers_completed_job(monkeypatch):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    openai = FakeOpenAI([completed_response()])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["output_text"] == "finished"
    assert response.json()["usage"]["total_tokens"] == 6
    assert "openai_response_id" not in response.json()
    assert openai.responses.calls == 1


@pytest.mark.parametrize(
    ("provider_status", "local_status"),
    [("queued", "pending"), ("in_progress", "in_progress")],
)
def test_poll_keeps_provider_nonterminal_status_at_202(monkeypatch, provider_status, local_status):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    openai = FakeOpenAI([SimpleNamespace(status=provider_status)])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert response.json()["status"] == local_status


def test_poll_returns_cached_job_when_reconciliation_is_already_claimed(monkeypatch):
    redis = FakeRedis()
    cached = record(JobStatus.IN_PROGRESS)
    redis.values[job_key(JOB_ID)] = cached.model_dump_json()
    asyncio.run(claim_reconciliation(redis, JOB_ID, "other-owner", 100))
    openai = FakeOpenAI([completed_response()])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert openai.responses.calls == 0


def test_terminal_job_does_not_retrieve_provider(monkeypatch):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.COMPLETED).model_dump_json()
    openai = FakeOpenAI([completed_response()])
    install(monkeypatch, redis, openai)
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert openai.responses.calls == 0
```

- [ ] **Step 2: Run recovery tests and confirm RED**

Run: `uv run pytest tests/test_job_status.py -q`

Expected: completed recovery remains `202`, with zero retrieval calls.

- [ ] **Step 3: Add the Redis-first reconciliation helper**

In `app/api/responses.py`, import `secrets`, shared reconciliation functions, `TERMINAL_STATUSES`, and `processing_ttl`. Add a private helper that:

```python
async def _reconcile_background_job(record: JobRecord, request: Request) -> JobRecord:
    if record.status in TERMINAL_STATUSES or record.openai_response_id is None:
        return record
    owner_token = secrets.token_hex(16)
    if not await claim_reconciliation(
        request.app.state.redis,
        record.id,
        owner_token,
        processing_ttl(request.app.state.settings.openai_timeout_seconds),
    ):
        return record
    try:
        log_event(logger, logging.INFO, "openai_request_started", operation="retrieve", retry_count=0)
        provider = await retry_async(
            lambda: request.app.state.openai.responses.retrieve(record.openai_response_id),
            operation_name="retrieve",
        )
        request.state.openai_request_id = openai_request_id(provider)
        candidate = transition_from_provider(record, provider)
        if candidate is not None:
            result = await write_reconciled_job(request.app.state.redis, candidate)
            if candidate.status is JobStatus.COMPLETED and result is JobWriteResult.UPDATED:
                log_event(
                    logger,
                    logging.INFO,
                    "job_completed",
                    correlation_id=record.correlation_id,
                    operation="retrieve",
                    job_id=record.id,
                    openai_request_id=openai_request_id(provider),
                )
    finally:
        await finish_reconciliation(request.app.state.redis, record.id, owner_token)
    return await get_job(request.app.state.redis, record.id) or record
```

Call it after the first Redis read in `get_background_response`. Keep malformed/expired handling before reconciliation, and compute `200` versus `202` from the returned winning record.

- [ ] **Step 4: Run focused status, webhook, and logging tests**

Run: `uv run pytest tests/test_job_status.py tests/test_webhooks.py tests/test_logging.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add app/api/responses.py tests/test_job_status.py
git commit -m "feat(api): reconcile background polls"
```

---

### Task 4: Approved Provider Failure Semantics

**Files:**
- Modify: `app/api/responses.py`
- Modify: `tests/test_job_status.py`

**Interfaces:**
- Consumes: Task 3 `_reconcile_background_job`, `BackgroundJobError`, and existing OpenAI exception-to-HTTP middleware behavior.
- Produces: cached `202` on transient retrieval failure, terminal safe failure on provider `404`, and unchanged safe contracts for other permanent provider errors.

- [ ] **Step 1: Add failing transient, 404, and permanent-error tests**

Add these exact helpers to `tests/test_job_status.py`; the immediate retry wrapper prevents real sleeps while retaining the production three-attempt ceiling:

```python
import json
from types import SimpleNamespace

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.services.retry import retry_async as run_retry


def provider_error(kind, status_code=None):
    if kind in (APIConnectionError, APITimeoutError):
        return kind(request=None)
    response = SimpleNamespace(status_code=status_code, headers={}, request=None)
    return kind(
        message="provider secret: prompt",
        response=response,
        body={"error": "secret"},
    )


def install_active_job(monkeypatch, outcomes):
    redis = FakeRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    openai = FakeOpenAI(outcomes)
    install(monkeypatch, redis, openai)

    async def no_wait(seconds):
        return None

    async def immediate_retry(operation, *, operation_name, max_retries=2):
        return await run_retry(
            operation,
            operation_name=operation_name,
            max_retries=max_retries,
            sleep=no_wait,
            random_value=lambda: 0,
        )

    monkeypatch.setattr("app.api.responses.retry_async", immediate_retry)
    return redis, openai
```

Add the approved error-contract tests:

```python
@pytest.mark.parametrize(
    "error",
    [
        provider_error(APITimeoutError),
        provider_error(APIConnectionError),
        provider_error(RateLimitError, 429),
        provider_error(APIStatusError, 503),
    ],
)
def test_transient_retrieval_failure_returns_cached_202(monkeypatch, error):
    redis, openai = install_active_job(monkeypatch, [error, error, error])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 202
    assert response.json()["status"] == "in_progress"
    assert JobRecord.model_validate_json(redis.values[job_key(JOB_ID)]).status is JobStatus.IN_PROGRESS


def test_provider_404_becomes_safe_terminal_failure(monkeypatch):
    redis, _ = install_active_job(monkeypatch, [provider_error(APIStatusError, 404)])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == {
        "code": "background_response_unavailable",
        "message": "Background response is no longer available.",
    }
    assert "secret" not in response.text


def test_provider_auth_failure_preserves_job_and_returns_503(monkeypatch):
    redis, _ = install_active_job(monkeypatch, [provider_error(AuthenticationError, 401)])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert JobRecord.model_validate_json(redis.values[job_key(JOB_ID)]).status is JobStatus.IN_PROGRESS


def test_permanent_provider_4xx_preserves_job_and_returns_safe_500(monkeypatch):
    redis, _ = install_active_job(monkeypatch, [provider_error(APIStatusError, 400)])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert JobRecord.model_validate_json(redis.values[job_key(JOB_ID)]).status is JobStatus.IN_PROGRESS


def test_reconciliation_redis_failure_returns_503(monkeypatch):
    class EvalErrorRedis(FakeRedis):
        async def eval(self, script, numkeys, *args):
            raise ConnectionError("offline")

    redis = EvalErrorRedis()
    redis.values[job_key(JOB_ID)] = record(JobStatus.IN_PROGRESS).model_dump_json()
    install(monkeypatch, redis, FakeOpenAI([completed_response()]))
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
```

Add an explicit log-safety assertion:

```python
def test_poll_reconciliation_logs_exclude_sensitive_values(monkeypatch, captured_events):
    install_active_job(monkeypatch, [completed_response()])
    with TestClient(create_app()) as client:
        response = client.get(f"/v1/responses/{JOB_ID}", headers=headers())
    assert response.status_code == 200
    serialized = json.dumps(captured_events)
    for forbidden in (
        "resp_private",
        "finished",
        "test-openai-key",
        "test-webhook-secret",
        "test-wrapper-key",
    ):
        assert forbidden not in serialized
```

- [ ] **Step 2: Run the error tests and confirm RED**

Run: `uv run pytest tests/test_job_status.py -q`

Expected: transient errors return current mapped errors instead of cached `202`, and `404` does not store the safe terminal record.

- [ ] **Step 3: Implement exact exception behavior around provider retrieval**

Replace `_reconcile_background_job` with the complete approved error behavior:

```python
async def _reconcile_background_job(record: JobRecord, request: Request) -> JobRecord:
    if record.status in TERMINAL_STATUSES or record.openai_response_id is None:
        return record
    redis = request.app.state.redis
    owner_token = secrets.token_hex(16)
    if not await claim_reconciliation(
        redis,
        record.id,
        owner_token,
        processing_ttl(request.app.state.settings.openai_timeout_seconds),
    ):
        return record
    try:
        log_event(logger, logging.INFO, "openai_request_started", operation="retrieve", retry_count=0)
        provider = await retry_async(
            lambda: request.app.state.openai.responses.retrieve(record.openai_response_id),
            operation_name="retrieve",
        )
        request.state.openai_request_id = openai_request_id(provider)
        candidate = transition_from_provider(record, provider)
        if candidate is not None:
            result = await write_reconciled_job(redis, candidate)
            if candidate.status is JobStatus.COMPLETED and result is JobWriteResult.UPDATED:
                log_event(
                    logger,
                    logging.INFO,
                    "job_completed",
                    correlation_id=record.correlation_id,
                    operation="retrieve",
                    job_id=record.id,
                    openai_request_id=openai_request_id(provider),
                )
    except (APITimeoutError, APIConnectionError, RateLimitError):
        pass
    except AuthenticationError:
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        if error.status_code == 404:
            candidate = apply_job_transition(
                record,
                JobStatus.FAILED,
                error=BackgroundJobError(
                    code="background_response_unavailable",
                    message="Background response is no longer available.",
                ),
            )
            await write_reconciled_job(redis, candidate)
        elif error.status_code >= 500:
            pass
        else:
            raise
    finally:
        await finish_reconciliation(redis, record.id, owner_token)
    updated = await get_job(redis, record.id)
    if updated is None:
        raise JobNotFoundError()
    return updated
```

After the `finally`, re-read Redis. If the job disappeared during reconciliation, raise `JobNotFoundError` rather than returning the stale candidate. Do not catch `RedisError`; the existing outer status-handler mapping must continue returning `503`.

Expand the `try/except RedisError` in `get_background_response` so it includes both the initial `get_job` call and `_reconcile_background_job`. This ensures lease, Lua write, cooldown, and final re-read failures all use the existing `503` response.

- [ ] **Step 4: Run all affected API tests**

Run: `uv run pytest tests/test_job_status.py tests/test_upstream_errors.py tests/test_background_responses.py tests/test_webhooks.py tests/test_logging.py -q`

Expected: all selected tests pass with no real retry sleeps.

- [ ] **Step 5: Commit Task 4**

```bash
git add app/api/responses.py tests/test_job_status.py
git commit -m "fix(api): preserve jobs on poll failures"
```

---

### Task 5: Webhook Reuse, Race Proof, and Contract Documentation

**Files:**
- Modify: `app/api/webhooks.py:17-48,131-167`
- Modify: `tests/test_webhooks.py`
- Modify: `tests/test_webhook_service.py`
- Modify: `Learning/api-design.md:64-124`
- Modify: `Learning/questions-and-answers.md:86-93`

**Interfaces:**
- Consumes: Task 1 `TERMINAL_STATUSES` and `apply_job_transition`; Task 2 `write_reconciled_job` for cross-path race tests.
- Produces: one provider-to-job transition contract shared by polling and webhooks, plus user-facing documentation matching runtime behavior.

- [ ] **Step 1: Add a failing webhook/poller race test**

In `tests/test_webhook_service.py`, exercise both orderings:

```python
def test_poll_and_webhook_finalizers_keep_first_terminal_state():
    for poll_first in (True, False):
        redis = FakeRedis()
        active = record(JobStatus.IN_PROGRESS)
        redis.values[job_key(active.id)] = active.model_dump_json()
        redis.values[event_key("evt-race")] = "processing:webhook-owner"
        polled = active.model_copy(update={"status": JobStatus.FAILED})
        webhook = active.model_copy(update={"status": JobStatus.COMPLETED, "output_text": "done"})

        if poll_first:
            assert asyncio.run(write_reconciled_job(redis, polled)) is JobWriteResult.UPDATED
            assert asyncio.run(finalize_event(redis, "evt-race", "webhook-owner", webhook)) is FinalizationResult.ALREADY_TERMINAL
            expected = JobStatus.FAILED
        else:
            assert asyncio.run(finalize_event(redis, "evt-race", "webhook-owner", webhook)) is FinalizationResult.UPDATED
            assert asyncio.run(write_reconciled_job(redis, polled)) is JobWriteResult.ALREADY_TERMINAL
            expected = JobStatus.COMPLETED
        assert JobRecord.model_validate_json(redis.values[job_key(active.id)]).status is expected
```

- [ ] **Step 2: Run the race and webhook tests before refactoring**

Run: `uv run pytest tests/test_webhook_service.py tests/test_webhooks.py -q`

Expected: the new race test passes after Task 2, establishing the safety net before changing webhook mapping.

- [ ] **Step 3: Replace duplicate webhook transition logic**

In `app/api/webhooks.py`:

- Import `TERMINAL_STATUSES` and `apply_job_transition` from `app.services.job_reconciliation`.
- Delete the local `TERMINAL_STATUSES` definition.
- Keep `EVENT_STATUSES`, signature verification, event claiming, provider retrieval, and atomic `finalize_event` behavior unchanged.
- Replace the completed normalization block and non-completed `model_copy` branch with:

```python
record = apply_job_transition(
    record,
    target_status,
    provider=provider if target_status is JobStatus.COMPLETED else None,
)
```

Remove the now-unused direct `normalize_response` import.

- [ ] **Step 4: Prove existing webhook behavior remains intact**

Run: `uv run pytest tests/test_webhooks.py tests/test_webhook_service.py tests/test_job_reconciliation.py -q`

Expected: all selected tests pass, including duplicate events, out-of-order events, stale ownership, and both race orderings.

- [ ] **Step 5: Update the public learning contract**

In `Learning/api-design.md`, state that a non-terminal status poll may retrieve OpenAI under a Redis per-job cooldown, terminal and provider-ID-less jobs remain Redis-only, transient retrieval failures return cached `202`, and provider `404` returns stored `failed` with the safe optional error object.

In `Learning/questions-and-answers.md`, replace:

```text
Polling reads only Redis, so it does not create more OpenAI work or extend the job TTL.
```

with:

```text
Polling reads Redis first. For a non-terminal job with an OpenAI response ID,
one caller per Redis cooldown may retrieve OpenAI and atomically store the
result; webhooks remain the fast path. Polling never creates a second model
response and does not extend the job's original expiry.
```

Document the roughly ten-minute OpenAI background polling window and the absence of a scheduled reconciler.

- [ ] **Step 6: Run final verification**

Run:

```bash
uv run pytest -q
uv run python -m compileall -q app tests
git diff --check main...HEAD
git status --short
```

Expected:

- Full suite passes.
- Compilation exits zero.
- Diff check emits no errors.
- Status contains only intentional task changes plus the two preserved untracked `Learning/` files.

- [ ] **Step 7: Audit forbidden values in affected logs and responses**

Run:

```bash
rg -n "resp_private|provider secret|test-openai-key|test-webhook-secret|Authorization" app
```

Expected: no matches in `app`; test-only sentinel values may remain under `tests`.

- [ ] **Step 8: Commit Task 5**

```bash
git add app/api/webhooks.py tests/test_webhooks.py tests/test_webhook_service.py Learning/api-design.md Learning/questions-and-answers.md
git commit -m "fix(jobs): unify terminal transitions"
```

- [ ] **Step 9: Request final code review before publishing**

Use `superpowers:requesting-code-review` against `main...HEAD`. Resolve every correctness, security, concurrency, and spec-compliance finding, rerun the full verification commands, then use `superpowers:finishing-a-development-branch` to offer push/PR integration choices.
