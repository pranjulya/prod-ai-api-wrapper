# Remaining Blockers and Phase 16 Local Operations

**Date:** 2026-08-20
**Status:** Approved

## Goal

Close the remaining production holes in billing, probes, and local startup, then ship a one-command Docker Compose stack on Redis 7.

## Already in place (out of scope)

- Redis failure after OpenAI success returns `200`/`202` and keeps the claim.
- `GET /v1/responses/{job_id}` reconciles non-terminal jobs via OpenAI retrieve.
- Structured JSON logging.

## Remaining blockers

### 1. Short idempotency claim TTL

`claim` currently uses `IDEMPOTENCY_TTL_SECONDS` (default 86400) for `in_progress`. A crash leaves retries at `409 idempotency_in_progress` for a day.

Use the existing `processing_ttl(openai_timeout_seconds)` (`max(60, 3 * timeout + 10)`) for the initial `SET NX` claim. `store` still writes the completed replay with `IDEMPOTENCY_TTL_SECONDS`.

A crash then expires the lock in about one to two minutes (default timeout 30s → 100s), after which a retry may claim again. That is the same trade-off as webhook processing claims.

### 2. Keep the claim on provider timeout

After `responses.create` has been sent, `APITimeoutError` must not `delete` the claim (sync) and must not `_release_background` (background). Return `504` as today. A same-key retry during the claim TTL is `409 idempotency_in_progress`, not a second OpenAI create.

Connection errors, auth failures, rate limits, and exhausted 5xx retries still release pre-completion state as they do today.

### 3. Unauthenticated health probes

Exempt normalized paths `/health/live` and `/health/ready` from wrapper bearer auth. Business routes stay authenticated. Liveness stays dependency-free. Readiness still pings Redis.

Normalize paths with `rstrip("/")` so `/webhooks/openai/` is treated as the webhook path (signature verification, not wrapper bearer).

### 4. Missing idempotency key error code

`HTTPException(422)` must map to `validation_error` with message `Request validation failed.`, matching `Learning/api-design.md`.

### 5. Pytest collection

`tests/test_rate_limiting.py` must import `FakeRedis` the same way as the other test modules (`from conftest import FakeRedis`) so `pytest` collects the full suite.

### 6. Environment loading

Do not add `python-dotenv`. Local run is `uvicorn app.main:app --env-file .env`. Compose uses `env_file`.

## Phase 16 — Local operations

- `Dockerfile`: Python 3.12 slim, install the project, non-root user, do not copy `.env`, `uvicorn` on `0.0.0.0:8000`, health check against unauthenticated `GET /health/live`.
- `docker-compose.yml`: `redis:7-alpine` plus the API. API `REDIS_URL=redis://redis:6379/0`. Depend on Redis becoming healthy. Pass secrets via `.env`.
- `README.md`: copy `.env.example`, set keys, `docker compose up --build`, or local uvicorn with `--env-file`. Document Redis 7 because `EXPIRE NX` requires it.

## Tests

- Claim records the processing TTL on `SET NX`, not the 24h replay TTL.
- Sync timeout keeps the Redis claim; retry does not call OpenAI again.
- `/health/live` and `/health/ready` succeed without `Authorization`.
- `/webhooks/openai/` without a bearer key is a webhook signature error, not `authentication_failed`.
- Missing `Idempotency-Key` returns `422` / `validation_error`.
- `pytest` collects `tests/test_rate_limiting.py`.

## Non-goals

- Per-client API keys, workers, metrics, log shipping.
- Changing the fixed-window limiter implementation.
- Live OpenAI in CI.
