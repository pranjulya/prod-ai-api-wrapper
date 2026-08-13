# Phase 9 Upstream Errors, Timeouts, and Retries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retry transient OpenAI failures and return safe, correlated wrapper errors for exhausted provider failures.

**Architecture:** Add a small retry helper with injectable sleep/random behavior. Call it from the synchronous response route, translate final SDK exceptions through stable HTTP errors, and document the policy.

**Tech Stack:** FastAPI, official OpenAI SDK exception types, asyncio, pytest.

## Global Constraints

- Allow at most two retries after the initial provider call.
- Retry connection errors, timeouts, provider 5xx, and provider 429.
- Honor 429 retry metadata when available; otherwise use 0.1s and 0.2s exponential delays plus jitter.
- Never retry authentication, validation, unsupported-model, or permanent 4xx failures.
- Keep provider secrets, prompts, output, raw exceptions, and response bodies out of errors/logs.
- Preserve the existing correlated error envelope.
- Defer idempotency, background jobs, webhooks, streaming, and live OpenAI tests.

---

### Task 1: Retry helper

**Files:**
- Create: `app/services/retry.py`
- Test: `tests/test_retry.py`

**Interfaces:**
- Produces: `async retry_async(operation, *, max_retries=2, sleep=asyncio.sleep, random_value=random.random) -> result`.
- Raises: the final provider exception after retry exhaustion.

- [ ] Write failing tests for transient retry success, exhaustion, non-retryable exceptions, 429 retry metadata, and injected timing.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_retry.py` and verify failure.
- [ ] Implement exception classification and bounded exponential backoff with injected dependencies; never sleep after the final attempt.
- [ ] Run focused tests, full suite, compileall, and `git diff --check`.
- [ ] Commit `feat: add provider retry helper`.

### Task 2: Provider error mapping and route integration

**Files:**
- Modify: `app/api/responses.py`
- Modify: `app/errors.py`
- Test: `tests/test_upstream_errors.py`

**Interfaces:**
- Consumes: Task 1 retry helper and `request.app.state.openai.responses.create`.
- Produces: stable 503/504/500 errors with correlation IDs and generic messages.

- [ ] Write failing tests for transient retry success, timeout → 504, exhausted connection/5xx/429 → 503, provider authentication/permanent 4xx → 503 or 500 without retries, and secret-safe correlated envelopes.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_upstream_errors.py` and verify failure.
- [ ] Wrap only the provider call with `retry_async`; map final SDK exceptions using official exception classes/status codes. Preserve validation and unsupported-model behavior before the provider call.
- [ ] Run focused upstream, response, authentication, and rate-limit tests, then full suite, compileall, and diff checks.
- [ ] Commit `feat: map upstream response errors`.

### Task 3: Learning documentation

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

- [ ] Mark upstream error handling complete in the learning path.
- [ ] Add Q&A explaining transient versus permanent failures, bounded retries, jitter, and safe error translation.
- [ ] Run marker search, full tests, and `git diff --check`.
- [ ] Commit `docs: record upstream error handling milestone`.

## Final verification

    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check
    git status -sb
