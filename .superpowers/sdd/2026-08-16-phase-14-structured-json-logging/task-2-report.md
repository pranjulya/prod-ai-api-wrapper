# Phase 14 Task 2 report

Status: complete

Commit: `5b461b31d02ae4e61fb1f238a4e0ac9900209715` (`feat: log request security events`)

Files changed:

- `app/middleware/correlation.py`
- `app/middleware/authentication.py`
- `app/middleware/rate_limiting.py`
- `app/errors.py`
- `tests/test_logging.py`
- `tests/test_authentication.py`
- `tests/test_rate_limiting.py`

What changed:

- Replaced plain correlation completion/failure logs with structured `request_started`, `request_completed`, and `request_failed` events.
- Added structured `authentication_failed` and `rate_limit_rejected` events at the existing rejection points.
- Tagged validation failures with `request.state.error_category = "validation"` so 400/422 completion events serialize the category.
- Extended focused tests to assert correlation IDs, status codes, durations, retry-after values, and redaction of bearer sentinels from captured JSON events.

Red/green evidence:

1. Added failing tests first in:
   - `tests/test_logging.py`
   - `tests/test_authentication.py`
   - `tests/test_rate_limiting.py`
2. Verified red:

   ```bash
   uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py -q
   ```

   First attempt failed before pytest ran because sandboxed `uv` could not open its cache:

   - `Failed to initialize cache at /Users/pranjulyabajpai/.cache/uv`
   - `Operation not permitted`

   Reran with approval; pytest then failed for the expected missing events:

   - `7 failed, 21 passed in 0.64s`
   - failures were `IndexError` lookups for absent `request_started`, `request_completed`, `request_failed`, `authentication_failed`, and `rate_limit_rejected` events

3. Verified green after the middleware/error changes:

   ```bash
   uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py -q
   ```

   Result:

   - `28 passed in 0.57s`

4. Verified the broader existing error-path slice from the brief:

   ```bash
   uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py tests/test_responses.py -q
   ```

   Result:

   - `47 passed in 0.48s`

Exact commands run and results:

```bash
sed -n '1,260p' .superpowers/sdd/2026-08-16-phase-14-structured-json-logging/task-2-brief.md
```

- Read task brief and exact required event names/fields.

```bash
git status --short
```

- Confirmed only the owned task files were modified before commit.

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py -q
```

- Initial sandbox failure on uv cache access.

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py -q
```

- Red run after approval: `7 failed, 21 passed in 0.64s`

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py -q
```

- Green run after implementation: `28 passed in 0.57s`

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py tests/test_responses.py -q
```

- Broader green run: `47 passed in 0.48s`

```bash
git diff --check -- app/middleware/correlation.py app/middleware/authentication.py app/middleware/rate_limiting.py app/errors.py tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py
```

- No whitespace or patch-format issues.

```bash
git add app/middleware/correlation.py app/middleware/authentication.py app/middleware/rate_limiting.py app/errors.py tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py
git commit -m "feat: log request security events"
```

- Commit created successfully: `5b461b31d02ae4e61fb1f238a4e0ac9900209715`

```bash
git rev-parse HEAD
git status --short
```

- Verified committed head and clean worktree.

Self-review:

- Kept the diff inside the seven owned files only.
- Preserved middleware order, response codes/bodies/headers, Redis behavior, and existing auth/rate-limit branches.
- Used only approved structured fields (`method`, `route`, `status_code`, `duration_ms`, `retry_after`, `openai_request_id`, `error_category`, `correlation_id`).
- Did not log credentials, headers, exception text, exception args, tracebacks, Redis values, or limiter keys.
- Reset the correlation context in a `finally` block so request-scoped logging does not leak across requests.

Concerns:

- `APIRoute.path` is relative for router-prefixed static routes here (for example `/live` under `/health`), so `_route()` logs `request.url.path` for static routes and falls back to the route template only when path params are present. That keeps `/health/live` correct for current coverage, but if later tasks require fully templated prefixed dynamic paths, `_route()` may need a follow-up refinement once there is an authoritative source for the full prefixed template.

## Fix Round 1

Status: complete

Files changed:

- `app/middleware/correlation.py`
- `tests/test_logging.py`

What changed:

- Added a regression test for the current prefixed dynamic route `/v1/responses/{job_id}`.
- Updated `_route()` to prefer `request.scope["fastapi"]["effective_route_context"]` `path_format`/`path`, then fall back to `scope["route"]`, then `request.url.path`.
- Kept response behavior and redaction behavior unchanged.

Red/green evidence:

1. Added the failing regression in `tests/test_logging.py`.
2. Verified red:

   ```bash
   uv run python -m pytest tests/test_logging.py -q
   ```

   Result:

   - `1 failed, 9 passed in 0.62s`
   - failure: logged route was `/responses/{job_id}` instead of `/v1/responses/{job_id}`

3. Verified green after the helper fix:

   ```bash
   uv run python -m pytest tests/test_logging.py -q
   ```

   Result:

   - `10 passed in 0.65s`

4. Verified the requested covering slice:

   ```bash
   uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py tests/test_responses.py -q
   ```

   Result:

   - `48 passed in 0.80s`

5. Verified the full suite:

   ```bash
   uv run python -m pytest -q
   ```

   Result:

   - `148 passed in 1.91s`

Exact commands run and results:

```bash
sed -n '1,220p' app/middleware/correlation.py
sed -n '1,260p' tests/test_logging.py
sed -n '1,260p' .superpowers/sdd/2026-08-16-phase-14-structured-json-logging/task-2-report.md
git status --short
```

- Reviewed the current helper, logging tests, prior report, and worktree state.

```bash
uv run python -m pytest tests/test_logging.py -q
```

- Red run after adding the regression: `1 failed, 9 passed in 0.62s`

```bash
uv run python -m pytest tests/test_logging.py -q
```

- Green run after the helper fix: `10 passed in 0.65s`

```bash
uv run python -m pytest tests/test_logging.py tests/test_authentication.py tests/test_rate_limiting.py tests/test_responses.py -q
```

- Requested covering slice: `48 passed in 0.80s`

```bash
uv run python -m pytest -q
```

- Full suite: `148 passed in 1.91s`

```bash
git diff --check -- app/middleware/correlation.py tests/test_logging.py .superpowers/sdd/2026-08-16-phase-14-structured-json-logging/task-2-report.md
```

- No whitespace or patch-format issues.

```bash
git add app/middleware/correlation.py tests/test_logging.py .superpowers/sdd/2026-08-16-phase-14-structured-json-logging/task-2-report.md
git commit -m "fix: log full prefixed route templates"
git rev-parse HEAD
git status --short
```

- Commit hash recorded below; worktree verified clean after commit.

Commit: `171d84ac99f04a7509862d9084f4668410b528ff` (`fix: log full prefixed route templates`)

Self-review:

- Kept the code diff surgical to the route helper and its regression test.
- Matched the human ruling by preferring FastAPI’s effective route context over the earlier helper plan.
- Preserved secret safety: no credentials, headers, bodies, or exception text were added to logs.
- Left all middleware ordering, status codes, headers, and request lifecycle event names unchanged.

Concerns:

- The helper now trusts FastAPI’s `effective_route_context` when present. If a future FastAPI upgrade changes that scope shape, the fallback chain should still preserve behavior, but this route-template guarantee depends first on that framework-provided context.
