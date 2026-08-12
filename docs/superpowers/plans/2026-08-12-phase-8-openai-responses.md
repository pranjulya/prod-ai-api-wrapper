# Phase 8 Synchronous OpenAI Responses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a validated synchronous POST /v1/responses endpoint backed by one shared official AsyncOpenAI client and a stable wrapper response.

**Architecture:** Add request/response schemas and a focused OpenAI client adapter. Create the async provider client in the existing lifespan, register the responses router, and preserve current correlation, authentication, rate limiting, and error middleware. Provider failure translation remains Phase 9.

**Tech Stack:** FastAPI/Pydantic, official openai Python SDK, pytest, fake async provider client.

## Global Constraints

- Use the official openai Python SDK and AsyncOpenAI.
- Create one provider client in lifespan startup and close it in shutdown.
- Reject unknown request fields.
- Validate input 1–50,000 chars, instructions up to 10,000 chars, max_output_tokens 1–16,384, and metadata limits from the spec.
- Resolve omitted models to Settings.default_model; reject non-allowlisted models with 400 unsupported_model.
- Forward only input, instructions, model, max_output_tokens, and metadata when present.
- Return wrapper ID, OpenAI response ID, status, model, output text, usage when available, and correlation ID.
- Do not expose secrets, raw provider exceptions, prompts, or model output in errors.
- Defer idempotency, retries, provider error translation, background work, webhooks, streaming, tools, and live OpenAI tests.

---

### Task 1: SDK dependency and provider lifecycle

**Files:**
- Modify: pyproject.toml
- Modify: uv.lock
- Create: app/clients/openai_client.py
- Modify: app/main.py
- Test: tests/test_openai_lifecycle.py

**Interfaces:**
- Consumes: Settings.openai_api_key and Settings.openai_timeout_seconds.
- Produces: create_openai_client(settings) -> AsyncOpenAI; request.app.state.openai exists during requests and is closed during lifespan shutdown.

- [ ] Step 1: Write failing lifecycle tests

Patch app.main.create_openai_client with a fake client and assert create_app() creates it using configured values and calls await aclose() after the TestClient context exits. Keep Redis patched with the existing fake.

- [ ] Step 2: Run focused tests and verify failure

Run: .venv/bin/python -m pytest -q tests/test_openai_lifecycle.py

Expected: FAIL because the SDK dependency, factory, and lifespan state do not exist.

- [ ] Step 3: Add the SDK and minimal lifecycle

Add openai>=1.0 to project dependencies and refresh uv.lock. Implement create_openai_client(settings) with AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds). In the lifespan, create the OpenAI client after settings and Redis, close it in the shutdown finally block, and preserve cleanup if either client close raises.

- [ ] Step 4: Run focused and regression checks

Run:

    .venv/bin/python -m pytest -q tests/test_openai_lifecycle.py tests/test_readiness.py
    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check

- [ ] Step 5: Commit

    git add pyproject.toml uv.lock app/clients/openai_client.py app/main.py tests/test_openai_lifecycle.py
    git commit -m "feat: add shared openai client"

### Task 2: Request validation and normalized synchronous route

**Files:**
- Create: app/api/responses.py
- Create: app/schemas/responses.py
- Create: app/schemas/__init__.py
- Modify: app/errors.py
- Modify: app/main.py
- Test: tests/test_responses.py

**Interfaces:**
- Consumes: request.app.state.openai, request.app.state.settings, and the existing correlation middleware.
- Produces: POST /v1/responses returning the stable response schema and forwarding only approved fields.

- [ ] Step 1: Write failing route tests

Use a fake async OpenAI client whose responses.create records keyword arguments and returns a fake response. Cover default and explicit models, response normalization, forwarding only supplied optional fields, unknown fields, blank/oversized strings, invalid token limits, metadata limits, unsupported models, authentication, and correlation behavior.

- [ ] Step 2: Run focused tests and verify failure

Run: .venv/bin/python -m pytest -q tests/test_responses.py

Expected: FAIL because the schemas and route do not exist.

- [ ] Step 3: Implement strict schemas and route

Use Pydantic models with extra=forbid, string length constraints, positive bounded integer constraints, and a metadata validator for max 16 entries, key lengths, and value lengths. Resolve the model before provider call. Raise a dedicated HTTP exception or route-level error that maps to 400 unsupported_model; add the mapping without changing existing error envelopes. Build provider kwargs only from non-null optional fields. Return a wrapper ID generated with UUID4 and extract provider id, status, model, output_text, and usage fields safely.

- [ ] Step 4: Run focused, regression, and static checks

Run:

    .venv/bin/python -m pytest -q tests/test_responses.py tests/test_authentication.py tests/test_rate_limiting.py
    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check

- [ ] Step 5: Commit

    git add app/api/responses.py app/schemas app/errors.py app/main.py tests/test_responses.py
    git commit -m "feat: add synchronous responses endpoint"

### Task 3: Learning documentation

**Files:**
- Modify: Learning/learning-path.md
- Modify: Learning/questions-and-answers.md

**Interfaces:**
- Consumes: completed Phase 8 route and validation behavior.
- Produces: learner-facing explanation of SDK isolation, allowlisted models, strict schemas, and response normalization.

- [ ] Step 1: Update the learning path

Mark synchronous responses complete and state that the wrapper forwards a deliberately smaller contract through the official SDK.

- [ ] Step 2: Add Q&A entries

Explain why the provider SDK is isolated behind a client adapter, why unknown fields are rejected, why model allowlists matter, and why the wrapper normalizes provider responses.

- [ ] Step 3: Verify documentation and full suite

Run:

    rg -n "synchronous|SDK|allowlist|unknown|normalize" Learning/learning-path.md Learning/questions-and-answers.md
    .venv/bin/python -m pytest -q
    git diff --check

- [ ] Step 4: Commit

    git add Learning/learning-path.md Learning/questions-and-answers.md
    git commit -m "docs: record synchronous responses milestone"

## Final verification

    .venv/bin/python -m pytest -q
    .venv/bin/python -m compileall -q app
    git diff --check
    git status -sb
