# Phase 11 Background Response Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create durable, idempotent OpenAI background jobs and immediately return a stable `202 Accepted` response.

**Architecture:** Add a small Redis job-record service, then add a background route beside the synchronous response route. Reuse existing request validation, model selection, idempotency, retry/error mapping, and middleware.

**Tech Stack:** FastAPI, Pydantic, async Redis, official OpenAI SDK, pytest fake clients.

## Global Constraints

- Endpoint: `POST /v1/responses/background`.
- Require the existing bearer authentication and `Idempotency-Key`.
- Forward only approved request fields plus `background=True`.
- Store job records with `JOB_TTL_SECONDS` before calling OpenAI.
- Transition stored jobs from `pending` to `in_progress` and save the OpenAI response ID.
- Return `202` with wrapper job ID, status, timestamps, status URL, and correlation ID.
- Replay the same job response for identical idempotent retries.
- Delete the job and release idempotency after provider failure.
- Preserve safe correlated errors; do not expose Redis keys, secrets, prompts, output, or provider bodies.
- Defer job polling, terminal states, webhooks, cancellation, and live integration tests.

---

### Task 1: Redis job-record service

**Files:**
- Create: `app/services/jobs.py`
- Create: `app/schemas/jobs.py`
- Test: `tests/test_jobs_service.py`

**Interfaces:**
- Produces: controlled job status values, `JobRecord`, public `BackgroundJobResponse`, namespaced job keys, and async create/update/delete helpers.
- Consumes: Redis client, wrapper job ID, correlation ID, timestamps, and `JOB_TTL_SECONDS`.

- [ ] Write failing tests for namespaced keys, pending creation, configured TTL, in-progress update preserving TTL, serialization, and delete behavior.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_jobs_service.py` and verify failure.
- [ ] Implement minimal Pydantic schemas and Redis JSON helpers using timezone-aware UTC timestamps.
- [ ] Run focused tests, full suite, compileall, and `git diff --check`.
- [ ] Commit `feat: add background job storage`.

### Task 2: Background response endpoint

**Files:**
- Modify: `app/api/responses.py`
- Modify: `app/errors.py` only if an existing stable mapping is insufficient.
- Test: `tests/test_background_responses.py`

**Interfaces:**
- Consumes: Task 1 job helpers, existing idempotency helpers, response request schema, retry helper, settings, Redis, and OpenAI client.
- Produces: authenticated/idempotent `POST /v1/responses/background` returning `202 BackgroundJobResponse`.

- [ ] Write failing tests for successful creation, exact `background=True` forwarding, pending/in-progress storage, configured TTL, response shape, same-key replay, mismatch/in-progress conflict, validation/model failures, initial Redis failure, provider failure cleanup, update failure, authentication, and correlation.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_background_responses.py` and verify failure.
- [ ] Implement the route with shared request-kwargs/model helpers only if duplication is otherwise unavoidable. Claim idempotency, create pending job, call OpenAI with retry behavior, update the job, store the public response in idempotency, and return `202`.
- [ ] Preserve Phase 9 provider error mappings and Phase 10 conflict/error behavior.
- [ ] Run focused background/idempotency/upstream/response suites, full suite, compileall, and diff checks.
- [ ] Commit `feat: add background response creation`.

### Task 3: Learning documentation

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

- [ ] Mark background creation complete in the learning path.
- [ ] Explain why no worker is needed, why Redis stores the wrapper job, why `202` is returned, and why polling/webhooks remain separate phases.
- [ ] Run marker search, full tests, and `git diff --check`.
- [ ] Commit `docs: record background creation milestone`.

## Final verification

    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check
    git status -sb
