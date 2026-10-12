# AGENTS.md

Entry point for AI agents and new contributors. Read this first; open other files only when a branch below tells you to.

## Identity

- FastAPI gateway in front of the OpenAI Responses API: bearer auth, shared rate limiting, idempotent sync calls, background jobs, verified webhooks, safe JSON logs.
- Single source root `app/`; Python 3.12 managed with `uv`; Redis holds **all** coordination state (no in-process state survives a request).
- `tests/` is the behavioral contract (no Redis, no network, never bills). `scripts/smoke_test.py` is the only thing that calls OpenAI for real.

## Working rule

Treat `docs/architecture.md` as the current map. Open `app/` source only for the file you are changing. `Learning/*.pdf`, `Learning/build_study_guide_pdf.py`, `lessons/*.html`, and `reference/` are human study artifacts — ignore them for code work.

## Read by branch

| Branch | Read |
|---|---|
| Changing a flow, state model, Redis key, or invariant | `docs/architecture.md` |
| New capability / changed requirement | `docs/requirements.md` (follow its change protocol) |
| "Why is it built this way?" | `docs/decisions.md` |
| API surface change (endpoint, field, status, error code) | `Learning/api-design.md`, then the README API sections |
| Historical design intent | `docs/superpowers/specs/<date>-<topic>-design.md` (indexed in `docs/decisions.md`) |

## Module map

| Path | Owns |
|---|---|
| `app/main.py` | `create_app` factory; middleware order **Correlation → Authentication → RateLimiting** (added in reverse); lifespan builds settings, Redis, OpenAI client |
| `app/config.py` | Frozen `Settings`, fail-fast env validation, every env var name |
| `app/logging.py` | `JsonFormatter`, `ALLOWED_FIELDS` allowlist, `log_event`, correlation contextvar, third-party/uvicorn scrubbing |
| `app/errors.py` | Error envelope `{"error":{code,message,correlation_id}}`, HTTP→code map, typed wrapper exceptions |
| `app/api/health.py` | `/health/live` (no I/O) and `/health/ready` (Redis `PING`) |
| `app/api/responses.py` | `POST /v1/responses`, `POST /v1/responses/background`, `GET /v1/responses/{job_id}` (+ poll-time reconciliation) |
| `app/api/webhooks.py` | `POST /webhooks/openai`: 1 MiB cap, signature verify, event dedupe, terminal job update |
| `app/clients/openai_client.py` | `AsyncOpenAI` factory with `max_retries=0` and configured timeout |
| `app/clients/redis_client.py` | `redis.asyncio` factory |
| `app/middleware/correlation.py` | Validates/generates `X-Correlation-ID`, request log, converts unhandled errors to `500 internal_error` |
| `app/middleware/authentication.py` | Bearer check via `hmac.compare_digest`; exempt health + webhook paths |
| `app/middleware/rate_limiting.py` | Global fixed-window limit, `429` + `Retry-After`; same exempt paths |
| `app/schemas/responses.py` | `ResponsesRequest` (extra=forbid, size limits), `ResponsesResponse`, `Usage` |
| `app/schemas/jobs.py` | `JobStatus`, `JobRecord` (internal), `BackgroundJobResponse` (public) |
| `app/services/idempotency.py` | Claim (`SET NX EX`), store, delete, request fingerprint |
| `app/services/jobs.py` | Job record CRUD + response-ID reverse index (pipelines) |
| `app/services/job_reconciliation.py` | `TERMINAL_STATUSES`, provider→job mapping, poll claim/cooldown, CAS write (Lua) |
| `app/services/rate_limit.py` | `check_rate_limit`: pipelined `INCR` + `EXPIRE NX` |
| `app/services/responses.py` | `normalize_response`: SDK object → `ResponsesResponse` |
| `app/services/retry.py` | `retry_async` (≤2 retries, transient only, capped backoff), error categories, request-ID extraction |
| `app/services/webhooks.py` | `processing_ttl`, event claim/release/mark/finalize (Lua CAS), 72 h dedupe TTL |
| `tests/conftest.py` | `FakeRedis` mirroring every Lua script branch; autouse `valid_environment` + `fake_redis` fixtures |
| `scripts/smoke_test.py` | Live end-to-end check — 2 billable calls (sync + background create). Never in CI |
| `scripts/check_docs.py` | Doc drift checker run by `make docs-check` and CI |

## Conventions (non-obvious only)

- **TDD:** failing test first, capture the RED output, then implement. No production code without a red test.
- **Fakes over mocks:** no `unittest.mock`. Monkeypatch only `app.main.create_redis`, `app.main.create_openai_client`, `app.api.responses.retry_async`, `app.api.webhooks.retry_async`. `FakeRedis.eval` must mirror each Lua branch and return code exactly.
- **Logging:** only `log_event(...)` with fields in `ALLOWED_FIELDS`. Never log prompts, outputs, headers, bodies, secrets, or Redis contents.
- **Redis:** every key starts `wrapper:`; every multi-key mutation is a pipeline or Lua `EVAL`; ownership via per-request `secrets.token_hex(16)`.
- **State:** claim before the provider call; terminal job statuses are immutable; only release state that has not reached completion.
- **Dependencies:** stdlib first; no new runtime dependencies without a `docs/decisions.md` row.
- **Commits:** Conventional Commits with scope, one task = one commit; docs change in the same commit as the code they describe.

## Verify ladder

```bash
uv run pytest tests/test_<area>.py -q        # focused
uv run pytest -v --tb=short                  # full suite (no Redis, no billing)
uv run ruff check app tests scripts
make docs-check                              # when docs, paths, modules, or Redis keys change
uv run python -m compileall app && git diff --check
```

Live check (bills OpenAI, needs Redis + `.env`): `make run`, then `uv run python scripts/smoke_test.py`.

## Artifacts

Task briefs and reports go in `.superpowers/sdd/<date>-<topic>/` (gitignored). Plans for repo-level changes go in `docs/plans/`.
