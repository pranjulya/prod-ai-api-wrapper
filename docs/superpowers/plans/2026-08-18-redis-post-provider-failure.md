# Redis Post-Provider Failure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Redis failures after OpenAI success from causing a second provider call for the same idempotency key.

**Architecture:** Keep pre-provider failure behavior unchanged. Once OpenAI returns successfully, return the available sync or background result even if Redis persistence fails, while retaining the idempotency claim. Extend job deletion so a stored OpenAI-response reverse index is deleted transactionally with its job.

**Tech Stack:** Python 3.12, FastAPI, redis-py asyncio API, pytest, Starlette TestClient

## Global Constraints

- Do not add dependencies.
- Do not change Redis or provider failure behavior before OpenAI accepts the request.
- Do not delete an idempotency claim after OpenAI succeeds.
- Log post-provider Redis failures without including exception text or request data.
- Keep changes limited to response creation, job cleanup, and their tests.

---

### Task 1: Preserve synchronous success after Redis storage failure

**Files:**
- Modify: `tests/test_responses.py`
- Modify: `app/api/responses.py`

**Interfaces:**
- Consumes: `create_response(payload, request, idempotency_key)` and `store(redis, key=..., request_hash_value=..., response=..., ttl_seconds=...)`
- Produces: a `200` response after provider success even if `store` raises `RedisError`; the existing claim remains and blocks another provider call.

- [ ] **Step 1: Write the failing route test**

Add a Redis fake whose first `SET NX` claim succeeds but whose completed idempotency `SET` raises `ConnectionError`. Send the request twice with the same key and assert the first response is `200`, the second is `409` with `idempotency_in_progress`, and `fake_openai.responses.calls` has length one.

```python
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
```

- [ ] **Step 2: Run the test and verify the current bug**

Run: `pytest tests/test_responses.py::test_response_store_failure_returns_result_without_second_provider_call -v`

Expected: FAIL because the first request returns `503` and deletes the claim, allowing the second request to call OpenAI.

- [ ] **Step 3: Make post-provider Redis storage best-effort**

In the `store` exception block of `create_response`, remove the claim deletion and the `503`. Keep `_log_redis_failure("create")`, then fall through to `return normalized`.

```python
    except RedisError:
        _log_redis_failure("create")
    return normalized
```

- [ ] **Step 4: Run the focused test**

Run: `pytest tests/test_responses.py::test_response_store_failure_returns_result_without_second_provider_call -v`

Expected: PASS.

- [ ] **Step 5: Commit the sync fix**

```bash
git add app/api/responses.py tests/test_responses.py
git commit -m "fix: retain claim after sync provider success"
```

### Task 2: Preserve background acceptance after Redis persistence failure

**Files:**
- Modify: `tests/test_background_responses.py`
- Modify: `app/api/responses.py`

**Interfaces:**
- Consumes: `create_background_response(payload, request, idempotency_key)`, `update_job_with_response_id(redis, record)`, and `store(...)`
- Produces: a `202` response after provider acceptance even if either post-provider persistence step raises `RedisError`; the claim remains and blocks another provider call.

- [ ] **Step 1: Write failing tests for each post-provider Redis boundary**

Add one fake that raises from `pipeline.execute()` during `update_job_with_response_id`, and one fake that lets that transaction succeed but raises when the completed idempotency record is stored. For each fake, send the same request twice and assert the first response is `202`, the second is `409` with `idempotency_in_progress`, and OpenAI is called once. For the idempotency-store case, also assert the job and hashed reverse index remain present.

```python
class ExecuteErrorPipeline:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def set(self, *args, **kwargs):
        self.pipeline.set(*args, **kwargs)

    async def execute(self):
        raise ConnectionError("pipeline failed")


class ProviderIdErrorRedis(FakeRedis):
    def pipeline(self, transaction=True):
        return ExecuteErrorPipeline(super().pipeline(transaction=transaction))


class IdempotencyStoreErrorRedis(FakeRedis):
    async def set(self, key, value, nx=False, ex=None):
        if key.startswith("wrapper:idempotency:") and not nx:
            raise ConnectionError("store failed")
        return await super().set(key, value, nx=nx, ex=ex)
```

Use `jobs_service.job_key(first.json()["id"])` and `jobs_service.response_job_key("resp_background")` for the persistence assertions.

- [ ] **Step 2: Run the new tests and verify the current bug**

Run: `pytest tests/test_background_responses.py -k "post_provider or idempotency_store" -v`

Expected: FAIL because the first request returns `503`, and the idempotency-store path deletes the claim while leaving the job and reverse index.

- [ ] **Step 3: Make background post-provider persistence best-effort**

In the post-provider `except RedisError` block, remove `_release_background(...)` and the `503`. Keep `_log_redis_failure("background_create")`, then fall through to `return public`.

```python
    except RedisError:
        _log_redis_failure("background_create")
    return public
```

- [ ] **Step 4: Run the focused background tests**

Run: `pytest tests/test_background_responses.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the background fix**

```bash
git add app/api/responses.py tests/test_background_responses.py
git commit -m "fix: retain claim after background acceptance"
```

### Task 3: Delete jobs and reverse indexes transactionally

**Files:**
- Modify: `app/services/jobs.py`
- Modify: `tests/test_jobs_service.py`

**Interfaces:**
- Consumes: `delete_job(redis, job_id: str) -> None`, `get_job(redis, job_id)`, `job_key(job_id)`, and `response_job_key(openai_response_id)`
- Produces: the same `delete_job` signature, now deleting the job and any known reverse index in one transactional pipeline.

- [ ] **Step 1: Write the failing service test**

Extend the job storage exercise so the stored record has `openai_response_id="resp_123"`, create its reverse index with `update_job_with_response_id`, call `delete_job`, and assert both keys are absent and one additional transactional pipeline was executed.

```python
    await jobs_service.update_job_with_response_id(redis, updated)
    pipelines_before_delete = redis.pipeline_calls
    await delete_job(redis, record.id)
    assert job_key(record.id) not in redis.values
    assert jobs_service.response_job_key("resp_123") not in redis.values
    assert redis.pipeline_calls == pipelines_before_delete + 1
```

- [ ] **Step 2: Run the service test and verify the missing cleanup**

Run: `pytest tests/test_jobs_service.py::test_job_create_update_delete -v`

Expected: FAIL because the current `delete_job` removes only `wrapper:job:*` and does not use a transaction.

- [ ] **Step 3: Implement transactional deletion**

Read the job record first, derive the optional reverse-index key, queue both deletions on `redis.pipeline(transaction=True)`, and execute once.

```python
async def delete_job(redis, job_id: str) -> None:
    record = await get_job(redis, job_id)
    pipeline = redis.pipeline(transaction=True)
    pipeline.delete(job_key(job_id))
    if record is not None and record.openai_response_id is not None:
        pipeline.delete(response_job_key(record.openai_response_id))
    await pipeline.execute()
```

- [ ] **Step 4: Run service and route tests**

Run: `pytest tests/test_jobs_service.py tests/test_background_responses.py tests/test_responses.py -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`

Expected: all tests PASS with no unexpected warnings or errors.

- [ ] **Step 6: Commit transactional cleanup**

```bash
git add app/services/jobs.py tests/test_jobs_service.py
git commit -m "fix: delete response job index atomically"
```
