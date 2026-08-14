# Phase 12 Background Job Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authenticated clients poll Redis-backed background jobs through a stable status endpoint.

**Architecture:** Extend the existing job service with read support, add a dynamic-status FastAPI route, and map missing/expired jobs through a dedicated safe error.

**Tech Stack:** FastAPI, Pydantic, async Redis, pytest fake clients.

## Global Constraints

- Endpoint: `GET /v1/responses/{job_id}`.
- Require bearer authentication and rate limiting; do not require idempotency.
- Never contact OpenAI from the status endpoint.
- Return `202` for pending/in-progress and `200` for completed/failed/cancelled/incomplete.
- Return `404 job_not_found` for malformed, missing, TTL-expired, or explicitly expired jobs.
- Return correlated `503 upstream_unavailable` for Redis failures.
- Never expose Redis keys, OpenAI response IDs, secrets, prompts, output, or raw exceptions.
- Do not extend job TTL while polling.

---

### Task 1: Job retrieval helper

**Files:**
- Modify: `app/services/jobs.py`
- Test: `tests/test_jobs_service.py`

- [ ] Write failing tests for stored JSON retrieval, missing keys, invalid records, Redis errors, and proof that reads do not write or extend TTL.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_jobs_service.py` and verify failure.
- [ ] Implement `async get_job(redis, job_id) -> JobRecord | None` using the existing namespaced key and Pydantic validation.
- [ ] Run focused tests, full suite, compileall, and `git diff --check`.
- [ ] Commit `feat: read background jobs from redis`.

### Task 2: Status endpoint and error contract

**Files:**
- Modify: `app/api/responses.py`
- Modify: `app/errors.py`
- Test: `tests/test_job_status.py`

- [ ] Write failing tests for all controlled statuses, malformed IDs, missing/expired jobs, Redis failure, authentication, correlation, public-field filtering, and no OpenAI calls.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_job_status.py` and verify failure.
- [ ] Add strict `job_<uuid4>` validation, `JobNotFoundError`, Redis retrieval, dynamic `202`/`200`, and public response normalization.
- [ ] Preserve existing synchronous/background creation routes and middleware behavior.
- [ ] Run focused job/background/auth/rate-limit suites, full suite, compileall, and diff checks.
- [ ] Commit `feat: add background job status endpoint`.

### Task 3: Learning documentation

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

- [ ] Mark job status polling complete.
- [ ] Explain polling status codes, TTL expiry, safe not-found behavior, and why polling does not call OpenAI.
- [ ] Run marker search, full tests, and `git diff --check`.
- [ ] Commit `docs: record job status milestone`.

## Final verification

    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check
    git status -sb
