# Phase 6 Redis Integration and Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one async Redis client per FastAPI process and expose a correlated readiness check without making liveness depend on Redis.

**Architecture:** `app.clients.redis_client` owns Redis client creation. The FastAPI lifespan stores the client on `app.state.redis` and closes it in `finally`; the readiness route pings that shared client and translates connection failures into the existing correlated 503 error handler.

**Tech Stack:** Python 3.12+, FastAPI, `redis.asyncio`, pytest, standard library.

## Global Constraints

- Create and close one async Redis client per FastAPI process.
- Do not ping Redis during startup.
- `GET /health/ready` returns `200 {"status":"ready"}` after a successful ping.
- Redis failure returns the standard correlated `503 upstream_unavailable` error.
- Liveness continues to return success when Redis is unavailable.
- Do not add rate limiting, idempotency, job storage, webhook storage, or Docker Compose.

---

### Task 1: Add Redis lifecycle and readiness endpoint

**Files:**
- Modify: `pyproject.toml`
- Create: `app/clients/__init__.py`
- Create: `app/clients/redis_client.py`
- Modify: `app/main.py`
- Modify: `app/api/health.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_readiness.py`

**Interfaces:**
- Consumes: `Settings.redis_url` and the existing middleware/error handlers.
- Produces: `create_redis(url: str)`, `app.state.redis`, and `GET /health/ready`.

- [ ] **Step 1: Add the Redis dependency and failing readiness tests**

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "redis>=5",
]
```

```python
class FakeRedis:
    def __init__(self, ping_error=None):
        self.ping_error = ping_error
        self.closed = False

    async def ping(self):
        if self.ping_error:
            raise self.ping_error
        return True

    async def aclose(self):
        self.closed = True


def auth_headers():
    return {"Authorization": "Bearer test-wrapper-key"}


def test_readiness_reports_ready_and_closes_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)
    with TestClient(create_app()) as client:
        response = client.get("/health/ready", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert fake.closed


def test_readiness_fails_but_liveness_stays_live(monkeypatch):
    fake = FakeRedis(redis.exceptions.ConnectionError("offline"))
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)
    with TestClient(create_app()) as client:
        ready = client.get("/health/ready", headers=auth_headers())
        live = client.get("/health/live", headers=auth_headers())
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "upstream_unavailable"
    assert live.status_code == 200
```

- [ ] **Step 2: Run the new tests to verify the missing Redis behavior**

Run: `.venv/bin/python -m pytest tests/test_readiness.py -q`

Expected: FAIL because Redis dependency, client factory, and readiness route do not exist.

- [ ] **Step 3: Implement the smallest Redis client and lifecycle**

```python
# app/clients/redis_client.py
from redis import asyncio as redis


def create_redis(url: str):
    return redis.from_url(url, decode_responses=True)
```

In `lifespan`, create the client after `load_settings()`, assign
`app.state.redis`, yield, and `await app.state.redis.aclose()` in `finally`.
The readiness route awaits `request.app.state.redis.ping()` and raises
`HTTPException(status_code=503, detail="Redis unavailable")` on
`redis.exceptions.RedisError`; existing exception handling supplies the
correlated error envelope.

- [ ] **Step 4: Verify all readiness and lifecycle scenarios**

Run: `.venv/bin/python -m pytest tests/test_readiness.py tests/test_health.py -q`

Expected: PASS, including readiness success, Redis failure, cleanup, and liveness.

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m compileall -q app && git diff --check`

Expected: exit status `0`.

Commit: `git add pyproject.toml uv.lock app tests && git commit -m "feat: add redis readiness"`

### Task 2: Record the Redis learning milestone

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

**Interfaces:**
- Consumes: Redis lifecycle and readiness behavior from Task 1.
- Produces: Learner-facing explanation of liveness versus readiness.

- [ ] **Step 1: Update the learning documents**

```markdown
7. **Redis integration and readiness (complete)** — create and close shared Redis clients, check readiness with `PING`, and keep liveness independent.
```

Add a Q&A explaining why readiness may fail while liveness remains successful.

- [ ] **Step 2: Verify the milestone and full suite**

Run: `rg -q 'Redis integration and readiness \(complete\)' Learning/learning-path.md && .venv/bin/python -m pytest -q && git diff --check`

Expected: exit status `0` and all tests pass.

- [ ] **Step 3: Commit**

Run: `git add Learning/learning-path.md Learning/questions-and-answers.md && git commit -m "docs: record redis readiness milestone"`
