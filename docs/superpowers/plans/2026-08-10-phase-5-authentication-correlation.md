# Phase 5 Authentication and Correlation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require the wrapper bearer key for internal requests and return a safe correlation ID for every response and error.

**Architecture:** Correlation middleware resolves or creates the request ID before authentication middleware evaluates the bearer credential. A shared `error_response()` function supplies the documented error shape so both middleware paths return the same safe body.

**Tech Stack:** Python 3.12+, FastAPI, Starlette middleware, pytest, standard library (`hmac`, `logging`, `re`, `uuid`).

## Global Constraints

- Protect every route except the exact `/webhooks/openai` path.
- Compare `WRAPPER_API_KEY` with `hmac.compare_digest`.
- Accept supplied correlation IDs only when they match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.
- Generate UUID4 correlation IDs for omitted or malformed identifiers.
- Return correlation IDs in `X-Correlation-ID` and in every error body.
- Never log authorization headers, wrapper keys, or other secrets.
- Do not add JWTs, user storage, webhook verification, or structured JSON logging.

---

### Task 1: Add authenticated, correlation-aware request handling

**Files:**
- Create: `app/errors.py`
- Create: `app/middleware/__init__.py`
- Create: `app/middleware/authentication.py`
- Create: `app/middleware/correlation.py`
- Modify: `app/main.py`
- Modify: `tests/test_health.py`
- Create: `tests/test_authentication.py`

**Interfaces:**
- Consumes: `request.app.state.settings.wrapper_api_key` and request headers.
- Produces: `error_response(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse`, `AuthenticationMiddleware`, and `CorrelationMiddleware`.

- [ ] **Step 1: Write failing middleware boundary tests**

```python
def test_missing_bearer_key_returns_correlated_error():
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]


def test_valid_client_correlation_id_is_returned():
    headers = {"Authorization": "Bearer test-wrapper-key", "X-Correlation-ID": "client.request-1"}
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers=headers)

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "client.request-1"
```

- [ ] **Step 2: Run the test to verify the missing authentication behavior**

Run: `.venv/bin/python -m pytest tests/test_authentication.py -q`

Expected: FAIL because unauthenticated liveness currently returns `200`.

- [ ] **Step 3: Implement common errors and middleware**

```python
def error_response(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
    )
```

```python
if request.url.path == "/webhooks/openai":
    return await call_next(request)
scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
if scheme != "Bearer" or not credential or not hmac.compare_digest(credential, request.app.state.settings.wrapper_api_key):
    return error_response(401, "authentication_failed", "Authentication required.", request.state.correlation_id)
```

Register authentication first and correlation second in `create_app()` so correlation wraps authentication. Correlation middleware stores the ID in `request.state`, returns `400 invalid_correlation_id` for malformed supplied values with a generated ID, adds `X-Correlation-ID` to all responses, and logs only the correlation ID and status code after the response.

- [ ] **Step 4: Add all auth and correlation scenarios**

```python
@pytest.mark.parametrize("authorization", ["Basic test-wrapper-key", "Bearer wrong-key"])
def test_invalid_bearer_key_is_rejected(authorization):
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"Authorization": authorization})
    assert response.status_code == 401


def test_malformed_correlation_id_returns_generated_correlated_error():
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"X-Correlation-ID": "bad id"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_correlation_id"
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]
```

Update liveness and OpenAPI tests to send the valid test bearer key. Capture correlation logs and assert the wrapper key and authorization header do not appear.

Run: `.venv/bin/python -m pytest tests/test_authentication.py tests/test_health.py -q`

Expected: PASS with authentication, correlation, and existing health coverage green.

- [ ] **Step 5: Commit**

Run: `git add app/errors.py app/middleware app/main.py tests/test_authentication.py tests/test_health.py && git commit -m "feat: add request authentication"`

### Task 2: Record the authentication milestone

**Files:**
- Modify: `Learning/learning-path.md`
- Modify: `Learning/questions-and-answers.md`

**Interfaces:**
- Consumes: The bearer and correlation behavior from Task 1.
- Produces: Learner-facing explanation that bearer authentication and correlation IDs are separate controls.

- [ ] **Step 1: Update the learning documents**

```markdown
6. **Authentication and correlation (complete)** — require the internal bearer key and trace every response with a correlation ID.
```

Add one question and answer explaining that bearer authentication controls access, while a correlation ID only traces a request and does not authorize it.

- [ ] **Step 2: Verify documentation and the full suite**

Run: `rg -q 'Authentication and correlation \(complete\)' Learning/learning-path.md && .venv/bin/python -m pytest -q && .venv/bin/python -m compileall -q app && git diff --check`

Expected: exit status `0` and all tests pass.

- [ ] **Step 3: Commit**

Run: `git add Learning/learning-path.md Learning/questions-and-answers.md && git commit -m "docs: record authentication milestone"`
