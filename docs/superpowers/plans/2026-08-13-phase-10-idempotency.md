# Phase 10 Redis-Backed Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate synchronous OpenAI requests by atomically claiming and replaying idempotency records in Redis.

**Architecture:** Add a small Redis idempotency service for deterministic hashing and claim/read/store/delete operations. Integrate it around the existing validated response route, then document the behavior.

**Tech Stack:** FastAPI, async Redis, JSON/hashlib, pytest fake clients.

## Global Constraints

- Require `Idempotency-Key` on `POST /v1/responses`.
- Hash the validated request and effective model deterministically.
- Claim with atomic Redis `SET(..., nx=True, ex=...)`.
- Same key/hash in progress returns `409 idempotency_in_progress`.
- Same key/different hash returns `409 idempotency_key_reused`.
- Successful responses replay until `IDEMPOTENCY_TTL_SECONDS` expires.
- Delete failed in-progress records.
- Redis failures return correlated `503 upstream_unavailable`.
- No live Redis/OpenAI tests; do not implement background idempotency or webhook deduplication.

---

### Task 1: Idempotency service

**Files:**
- Create: `app/services/idempotency.py`
- Test: `tests/test_idempotency_service.py`

**Interfaces:**
- Produces: deterministic `request_hash(payload, effective_model)`, namespaced key creation, async claim/get/store/delete helpers, and typed claim outcomes.

- [ ] Write failing tests for deterministic hashes, atomic first claim, same-key reads, TTL storage, delete, and Redis failure propagation.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_idempotency_service.py` and verify failure.
- [ ] Implement JSON records and `SET NX EX` claim with the configured TTL; never log raw keys or payloads.
- [ ] Run focused tests, full suite, compileall, and `git diff --check`.
- [ ] Commit `feat: add redis idempotency service`.

### Task 2: Response route integration

**Files:**
- Modify: `app/api/responses.py`
- Modify: `app/errors.py`
- Test: `tests/test_idempotency.py`

**Interfaces:**
- Consumes: Task 1 service, validated `ResponsesRequest`, effective model, existing retry-wrapped provider call, and `IDEMPOTENCY_TTL_SECONDS`.
- Produces: required-key validation, replay/mismatch/in-progress behavior, failure cleanup, and correlated Redis errors.

- [ ] Write failing tests for missing/blank key, first claim, same-key replay without a second provider call, mismatched payload `409`, in-progress `409`, provider failure cleanup, Redis failure, and concurrent duplicate calls.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_idempotency.py` and verify failure.
- [ ] Require and validate the header, compute the effective request hash, claim before OpenAI, branch on existing records, store normalized success, and delete on final provider failure. Preserve rate limiting, validation, model errors, retries, and correlation IDs.
- [ ] Add stable `409` codes and preserve `Retry-After` or other existing headers where applicable.
- [ ] Run focused idempotency/response/upstream suites, full suite, compileall, and diff checks.
- [ ] Commit `feat: prevent duplicate response requests`.

### Task 3: Learning documentation

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

- [ ] Mark idempotency complete in the learning path.
- [ ] Add Q&A explaining request fingerprints, atomic claims, replay, mismatch conflicts, and failed-record cleanup.
- [ ] Run marker search, full tests, and `git diff --check`.
- [ ] Commit `docs: record idempotency milestone`.

## Final verification

    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check
    git status -sb
