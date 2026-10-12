# Architecture

> Verified against `cadc0d7` (2026-10-13). Update in the same commit as any flow, state, or invariant change. `make docs-check` enforces paths, modules, and Redis keys.

## 1. Shape

- One FastAPI process (`app/main.py`), stateless between requests; any number of replicas can share one Redis.
- Three middlewares wrap every request, outermost first: correlation → authentication → rate limiting.
- Two upstream dependencies: OpenAI Responses API (via the official SDK, retries disabled in the SDK) and Redis 7.
- No background worker or scheduler exists: background jobs advance only through webhooks and client polls.
- The architecture diagram lives in the README; there is deliberately no second copy here.

## 2. Component map

| Module | Owns | Key entry points | May import |
|---|---|---|---|
| `app/main.py` | App assembly, lifespan | `create_app`, `lifespan` | everything under `app/` |
| `app/config.py` | Env parsing | `load_settings`, `Settings`, `ConfigError` | stdlib |
| `app/logging.py` | Log format + safety | `log_event`, `configure_logging`, `JsonFormatter`, `bind_correlation_id` | stdlib |
| `app/errors.py` | Error envelope | `error_response`, `http_exception_handler`, `UnsupportedModelError`, `IdempotencyConflictError`, `JobNotFoundError` | FastAPI/Starlette |
| `app/middleware/correlation.py` | Correlation ID, request log, last-resort 500 | `CorrelationMiddleware` | `app.logging`, `app.errors` |
| `app/middleware/authentication.py` | Bearer auth | `AuthenticationMiddleware`, `EXEMPT_PATHS` | `app.logging`, `app.errors` |
| `app/middleware/rate_limiting.py` | Global limiter | `RateLimitingMiddleware`, `EXEMPT_PATHS` | `app.services.rate_limit` |
| `app/api/health.py` | Probes | `live`, `ready` | — |
| `app/api/responses.py` | Sync, background, poll routes | `create_response`, `create_background_response`, `get_background_response`, `_reconcile_background_job` | `app.services.*`, `app.schemas.*`, `app.errors` |
| `app/api/webhooks.py` | Webhook ingress | `receive_openai_webhook` | `app.services.webhooks`, `app.services.jobs`, `app.services.job_reconciliation`, `app.services.retry` |
| `app/services/idempotency.py` | Idempotency records | `claim`, `store`, `delete`, `request_hash`, `redis_key` | stdlib |
| `app/services/jobs.py` | Job records | `create_job`, `update_job_with_response_id`, `get_job`, `get_job_id_by_response_id`, `delete_job` | `app.schemas.jobs` |
| `app/services/job_reconciliation.py` | Job state machine | `TERMINAL_STATUSES`, `transition_from_provider`, `apply_job_transition`, `claim_reconciliation`, `finish_reconciliation`, `write_reconciled_job` | `app.services.jobs`, `app.services.responses` |
| `app/services/webhooks.py` | Event dedupe | `processing_ttl`, `claim_event`, `release_event`, `mark_processed`, `finalize_event` | `app.services.jobs`, `app.services.retry` |
| `app/services/rate_limit.py` | Window counter | `check_rate_limit` | stdlib |
| `app/services/retry.py` | Retry policy | `retry_async`, `openai_request_id`, `openai_error_category`, `MAX_RETRY_DELAY_SECONDS` | `openai`, `app.logging` |
| `app/services/responses.py` | SDK normalization | `normalize_response` | `app.schemas.responses` |
| `app/schemas/responses.py`, `app/schemas/jobs.py` | Pydantic contracts | `ResponsesRequest`, `ResponsesResponse`, `JobStatus`, `JobRecord`, `BackgroundJobResponse` | pydantic |
| `app/clients/openai_client.py`, `app/clients/redis_client.py` | Client factories | `create_openai_client`, `create_redis` | SDKs |

## 3. Sync flow — `POST /v1/responses`

1. `app/middleware/correlation.py` — accept `X-Correlation-ID` if it matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, else generate a UUID; echo it on the response.
2. `app/middleware/authentication.py` — `Authorization: Bearer <WRAPPER_API_KEY>` via `hmac.compare_digest`; failure → `401 authentication_failed`.
3. `app/middleware/rate_limiting.py` → `check_rate_limit` — pipelined `INCR` + `EXPIRE NX`; over limit → `429 rate_limit_exceeded` + `Retry-After`; Redis down → `503`.
4. `create_response` — missing/blank `Idempotency-Key` → `422`; model not in `OPENAI_ALLOWED_MODELS` → `400 unsupported_model` (no Redis write yet).
5. `claim` — `SET NX EX processing_ttl` with state `in_progress` and the request fingerprint. Existing record: different fingerprint → `409 idempotency_key_reused`; still in progress → `409 idempotency_in_progress`; completed → replay stored body, no provider call.
6. `retry_async(responses.create)` — see the error map for failures.
7. `normalize_response` → `store` **only if `status == "completed"`** (TTL `IDEMPOTENCY_TTL_SECONDS`); any other status deletes the claim so the client can retry with different parameters.
8. A Redis failure while storing is logged and the response is still returned; the `in_progress` claim then expires after `processing_ttl`, which blocks duplicate billing in the meantime.

## 4. Background flow

**Create — `POST /v1/responses/background`:** same auth, limit, key, and allowlist checks → `claim` (fingerprint includes `background: true`) → `create_job` writes a `pending` record → `responses.create(background=True)` → `update_job_with_response_id` writes the `in_progress` record **and** the response-ID reverse index in one pipeline → `store` the public job body → `202`.

**Poll — `GET /v1/responses/{job_id}`:** validate `job_<uuid4>` (else `404 job_not_found`) → `get_job` (missing or `expired` → `404`) → if non-terminal and it has a response ID: `claim_reconciliation` (`SET NX`, owner token) → `responses.retrieve` → `transition_from_provider` → `write_reconciled_job` (Lua CAS; never overwrites a terminal record) → `finish_reconciliation` converts the claim into a 5 s cooldown. Returns `202` while `pending`/`in_progress`, otherwise `200`.

**Webhook — `POST /webhooks/openai`:** require the three `webhook-*` headers → stream the body with a 1 MiB cap (`413 request_too_large`) → `openai.webhooks.unwrap` verifies the signature (`401 invalid_webhook_signature`) → ignore event types outside `response.{completed,failed,cancelled,incomplete}` → `claim_event` (processed → `200`; another worker processing → `503` so OpenAI retries) → resolve the job through the reverse index → for `completed`, `retrieve` the response and require provider status `completed` → `finalize_event` (Lua CAS: writes the job and marks the event processed for 72 h atomically).

## 5. Invariants

| ID | Invariant | Enforced in |
|---|---|---|
| I1 | One retry layer: the SDK has `max_retries=0`; `retry_async` retries only connection, timeout, rate-limit, and 5xx errors, at most twice, with each delay ≤ `MAX_RETRY_DELAY_SECONDS` | `app/clients/openai_client.py`, `app/services/retry.py` |
| I2 | Authentication runs before rate limiting, so unauthenticated traffic cannot consume the shared quota | `app/main.py` |
| I3 | `/health/live`, `/health/ready`, and `/webhooks/openai` are exempt from bearer auth **and** rate limiting (both `EXEMPT_PATHS` sets must match) | both middlewares |
| I4 | Readiness pings Redis; liveness performs no I/O | `app/api/health.py` |
| I5 | Logs contain only `ALLOWED_FIELDS`; uvicorn/third-party records are reduced to static messages plus, for uvicorn errors, the exception class name | `app/logging.py` |
| I6 | Webhook body size is capped at 1 MiB **before** signature verification | `app/api/webhooks.py` |
| I7 | Correlation IDs match the regex in §3, otherwise they are replaced | `app/middleware/correlation.py` |
| I8 | Provider 4xx (other than 401/404/429 handling noted in §8) surfaces as `500 internal_error`; this is deliberate, so client-visible codes stay wrapper-owned | `app/middleware/correlation.py` |
| I9 | Terminal job statuses (`completed`, `failed`, `cancelled`, `incomplete`, `expired`) are never overwritten | `WRITE_RECONCILED_JOB_SCRIPT`, `FINALIZE_EVENT_SCRIPT` |
| I10 | Claim TTL `processing_ttl = max(60, 3·OPENAI_TIMEOUT_SECONDS + 2·MAX_RETRY_DELAY_SECONDS + 10)` outlives the worst-case provider call | `app/services/webhooks.py` |
| I11 | Webhook dedupe TTL (72 h) outlives the default job TTL (24 h) | `app/services/webhooks.py`, `app/config.py` |
| I12 | Only `completed` sync responses are stored for replay | `app/api/responses.py` |

## 6. Redis state inventory

| Prefix | Owner module | Value | TTL | Written by |
|---|---|---|---|---|
| `wrapper:idempotency:` + sha256(key) | `app/services/idempotency.py` | JSON `{request_hash, state, correlation_id, response}` | `processing_ttl` while in progress, then `IDEMPOTENCY_TTL_SECONDS` | `claim`, `store` |
| `wrapper:job:` + job ID | `app/services/jobs.py` | `JobRecord` JSON | `JOB_TTL_SECONDS` (remaining TTL is preserved on update) | `create_job`, `update_job_with_response_id`, Lua CAS writers |
| `wrapper:openai-response-job:` + sha256(response ID) | `app/services/jobs.py` | job ID | same as the job | `update_job_with_response_id` (same pipeline as the job) |
| `wrapper:job-reconciliation:` + sha256(job ID) | `app/services/job_reconciliation.py` | `processing:<token>`, then `cooldown` | `processing_ttl`, then 5 s | `claim_reconciliation`, `finish_reconciliation` |
| `wrapper:webhook:event:` + sha256(event ID) | `app/services/webhooks.py` | `processing:<token>` or processed marker | `processing_ttl`, then 72 h | `claim_event`, `mark_processed`, `finalize_event` |
| `wrapper:rate-limit:` + window index | `app/services/rate_limit.py` | integer counter | `RATE_LIMIT_WINDOW_SECONDS` (`EXPIRE NX`) | `check_rate_limit` |

## 7. Lua scripts

Each script's first line is a `-- name` comment that `tests/conftest.py` dispatches on. Changing a script means changing `FakeRedis.eval` in the same commit.

| Script | Module | Returns |
|---|---|---|
| `-- finish-job-reconciliation` | `app/services/job_reconciliation.py` | 1 owner matched / 0 not owner |
| `-- write-reconciled-job` | `app/services/job_reconciliation.py` | 1 updated / 0 job missing / 2 already terminal |
| `-- release-webhook-event` | `app/services/webhooks.py` | 1 released / 0 not owner |
| `-- mark-webhook-event-processed` | `app/services/webhooks.py` | 1 marked / 0 not owner |
| `-- finalize-webhook-event` | `app/services/webhooks.py` | 1 updated / 0 stale owner or missing job / 2 already terminal (event still marked processed) |

## 8. Error map

| Failure | Sync create | Background create | Poll | Webhook |
|---|---|---|---|---|
| Redis error | `503`, claim left as-is | `503`, job + claim released | `503` | `503`, event claim released |
| Provider timeout | `504`, **claim kept** (in-flight call may still bill) | `504`, claim + pending job kept | ignored, current record returned | `504`, event released |
| Connection / rate limit | `503`, claim deleted | `503`, released | ignored | `503`, released |
| Provider auth (401) | `503`, claim deleted | `503`, released | `503` | `503`, released |
| Provider 5xx | `503`, claim deleted | `503`, released | ignored | `503`, released |
| Provider 404 | `500 internal_error`, claim deleted | `500`, released | job → `failed` / `background_response_unavailable` | `500`, released |
| Other provider 4xx | `500 internal_error`, claim deleted | `500`, released | `500` | `500`, released |
| Redis error after provider success | logged, `200` returned | logged, `202` returned | — | — |

## 9. Test map

| Test file | Covers | Protects |
|---|---|---|
| `tests/test_authentication.py` | auth + correlation middleware | bearer rules, exempt paths, correlation regex |
| `tests/test_rate_limiting.py`, `tests/test_rate_limit_service.py` | limiter middleware + service | window math, `Retry-After`, Redis-down `503` |
| `tests/test_config.py` | `app/config.py` | fail-fast validation, defaults |
| `tests/test_health.py`, `tests/test_readiness.py` | `app/api/health.py` | I4 |
| `tests/test_responses.py` | sync route, normalization | request validation, response shape, logging redaction |
| `tests/test_idempotency.py`, `tests/test_idempotency_service.py` | idempotency route + service | replay, conflicts, timeout keeps claim, I12 |
| `tests/test_upstream_errors.py` | sync error map | §8 sync column, I8 |
| `tests/test_retry.py` | `app/services/retry.py` | I1 |
| `tests/test_background_responses.py` | background create | idempotent create, release paths, post-provider Redis failure |
| `tests/test_job_status.py`, `tests/test_job_reconciliation.py`, `tests/test_jobs_service.py` | poll + state machine + job CRUD | I9, cooldown, 404 → failed |
| `tests/test_webhooks.py`, `tests/test_webhook_service.py` | webhook route + Lua CAS | I6, I9, I11, dedupe |
| `tests/test_logging.py` | `app/logging.py` | I5 |
| `tests/test_openai_lifecycle.py` | lifespan + OpenAI client | client close, `max_retries=0` |
| `tests/test_doc_drift.py` | `scripts/check_docs.py` | this document stays true |

## 10. Extension guide

- **New endpoint:** schema in `app/schemas/` → service in `app/services/` → route in `app/api/` → decide exemption and update **both** `EXEMPT_PATHS` sets if public → tests → `Learning/api-design.md` + README → `docs/requirements.md` row.
- **New job status:** `JobStatus` **and** the terminal literals inside `WRITE_RECONCILED_JOB_SCRIPT` and `FINALIZE_EVENT_SCRIPT` **and** `TERMINAL_STATUSES` **and** the matching branches in `tests/conftest.py`.
- **New Redis key:** use the `wrapper:` prefix, add a row to §6 (the drift check fails otherwise), mutate multi-key state only through a pipeline or Lua.
- **New env var:** `app/config.py` + `.env.example` + the README configuration table + `tests/test_config.py`.
- **New log field:** add to `ALLOWED_FIELDS` only if it can never carry user content or secrets.

## 11. Known limits

- No scheduled reconciler: a job advances only when a webhook arrives or a client polls.
- A background create that times out keeps a `pending` job without a response ID; it stays `pending` until `JOB_TTL_SECONDS` expires.
- The rate limiter is one global fixed window, not per client; bursts of up to 2× the limit are possible across a window boundary.
- One shared `WRAPPER_API_KEY`; no per-client identity.
- No metrics or log shipping; logs go to stdout only.
- OpenAI may stop serving a background response before the 24 h job TTL; polls then mark the job `failed` / `background_response_unavailable`.
- `app/services/jobs.py::update_job` is used only by tests (dead in production code).
