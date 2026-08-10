# Phase 7 Redis-Backed Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce one shared atomic fixed-window request limit through Redis while preserving health checks, authentication, correlation IDs, and the existing error contract.

**Architecture:** Add a small async rate-limit service that uses the existing Redis client pipeline. Install it as middleware inside authentication, exempt liveness/readiness/webhook paths, and map limit/dependency failures through the existing correlated error handler.

**Tech Stack:** FastAPI, Starlette middleware, `redis.asyncio`, pytest, existing fake-Redis test pattern.

## Global Constraints

- Use `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS` already validated by `app.config.Settings`.
- Use the shared async Redis client created and closed by the Phase 6 lifespan.
- Make increment and first-hit expiry one Redis transaction.
- Exempt `/health/live`, `/health/ready`, and `/webhooks/openai`.
- Never log authorization credentials or other request secrets.
- Preserve `X-Correlation-ID` and the existing JSON error envelope.
- Do not add Lua scripts, per-user quotas, sliding windows, token buckets, or live-Redis integration tests.

---

### Task 1: Atomic Redis rate-limit service

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/rate_limit.py`
- Test: `tests/test_rate_limit_service.py`

**Interfaces:**
- Consumes: `Settings.rate_limit_requests`, `Settings.rate_limit_window_seconds`, and an async Redis client exposing `pipeline(transaction=True)`, `incr`, and `expire`.
- Produces: `RateLimitResult(allowed: bool, retry_after: int)` and `check_rate_limit(redis, *, limit: int, window_seconds: int, now: float | None = None) -> RateLimitResult`.

- [ ] **Step 1: Write failing service tests**

Cover a first request, a request at the configured limit, an over-limit request, window-key rollover, and Redis command failure. Use a fake async pipeline that records commands and executes them atomically against a shared dictionary.

```python
async def test_rejects_after_limit_and_reports_retry_after():
    redis = FakeRedis()
    assert (await check_rate_limit(redis, limit=2, window_seconds=60, now=120)).allowed
    assert (await check_rate_limit(redis, limit=2, window_seconds=60, now=121)).allowed
    result = await check_rate_limit(redis, limit=2, window_seconds=60, now=122)
    assert not result.allowed
    assert result.retry_after == 58
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_rate_limit_service.py`

Expected: FAIL because `app.services.rate_limit` does not exist.

- [ ] **Step 3: Write minimal implementation**

Use a key such as `wrapper:rate-limit:<window_index>`, where `window_index = int(now // window_seconds)`. In one `pipeline(transaction=True)`, call `incr(key)` and `expire(key, window_seconds)` only when the increment result is `1`. Return `allowed = count <= limit`; compute `retry_after = max(1, ((window_index + 1) * window_seconds) - int(now))`.

- [ ] **Step 4: Run focused tests and full regression suite**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_rate_limit_service.py
.venv/bin/python -m pytest -q
```

Expected: focused tests and all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services tests/test_rate_limit_service.py
git commit -m "feat: add atomic redis rate limiter"
```

### Task 2: Middleware and error-contract integration

**Files:**
- Create: `app/middleware/rate_limiting.py`
- Modify: `app/main.py`
- Modify: `app/errors.py`
- Test: `tests/test_rate_limiting.py`

**Interfaces:**
- Consumes: `check_rate_limit` from Task 1, `request.app.state.redis`, and `request.app.state.settings`.
- Produces: authenticated non-exempt requests are limited; limit responses are `429` with `Retry-After`; Redis failures are correlated `503` responses.

- [ ] **Step 1: Write failing middleware tests**

Add a fake Redis shared by requests and mount a small test route on `create_app()`. Verify health paths bypass the counter, invalid authentication is rejected without Redis calls, allowed requests reach the route, the first rejected request returns the expected envelope/header, Redis failures return `503`, and concurrent requests share one counter.

```python
def test_rejected_request_has_retry_after_and_stable_error(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)
    with TestClient(create_app()) as client:
        assert client.get("/health/live", headers=auth_headers()).status_code == 200
        assert client.get("/test-route", headers=auth_headers()).status_code == 200
        response = client.get("/test-route", headers=auth_headers())
    assert response.status_code == 429
    assert response.headers["Retry-After"].isdigit()
    assert response.json()["error"]["code"] == "rate_limit_exceeded"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest -q tests/test_rate_limiting.py`

Expected: FAIL because the middleware and 429 error mapping do not exist.

- [ ] **Step 3: Write minimal implementation**

Create `RateLimitingMiddleware` with exempt paths, call `check_rate_limit`, return `error_response(429, "rate_limit_exceeded", "Rate limit exceeded.", correlation_id, headers={"Retry-After": str(result.retry_after)})` when denied, and raise `HTTPException(503, detail="Redis unavailable")` on `RedisError`. Register the middleware so authentication runs before rate limiting and correlation remains the outer wrapper. Add `429: "rate_limit_exceeded"` to the shared handler and preserve `Retry-After` headers.

- [ ] **Step 4: Run focused tests, regression checks, and static checks**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_rate_limiting.py tests/test_authentication.py tests/test_readiness.py
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app
git diff --check
```

Expected: all tests and checks pass.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/errors.py app/middleware/rate_limiting.py tests/test_rate_limiting.py
git commit -m "feat: enforce redis rate limits"
```

### Task 3: Learning documentation

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

**Interfaces:**
- Consumes: completed rate-limiting behavior from Tasks 1–2.
- Produces: learner-facing explanation of shared Redis counters, atomicity, fixed windows, and retry recovery.

- [ ] **Step 1: Update the learning path**

Mark the rate-limiting milestone complete and state that the implementation uses an atomic Redis fixed-window counter shared across instances.

- [ ] **Step 2: Add Q&A entries**

Explain why in-memory counters fail across workers/restarts, why `INCR` and expiry must be transactional, why health routes are exempt, and how callers use `Retry-After`.

- [ ] **Step 3: Verify documentation and full suite**

Run:

```bash
rg -n "rate.limit|Retry-After|fixed.window|atomic|in.memory" Learning/learning-path.md Learning/questions-and-answers.md
.venv/bin/python -m pytest -q
git diff --check
```

- [ ] **Step 4: Commit**

```bash
git add Learning/learning-path.md Learning/questions-and-answers.md
git commit -m "docs: record rate limiting milestone"
```

## Final verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app
git diff --check
git status -sb
```

