# Requirements

This file owns **behavior obligations** and **how requirement changes are recorded**. It does not restate the wire contract (endpoints, fields, status codes, error codes); `Learning/api-design.md` owns that. Structure and invariants live in `docs/architecture.md`.

## Requirement register

Status: `done` = implemented and tested · `limited` = implemented with a documented limit (see `docs/architecture.md` §11).

### Ingress & auth

| ID | Requirement | Source of truth | Tests | Status |
|---|---|---|---|---|
| R1 | Business routes require `Authorization: Bearer <WRAPPER_API_KEY>`, compared in constant time | `app/middleware/authentication.py` | `tests/test_authentication.py` | done |
| R2 | Health and webhook routes are reachable without the bearer key | `app/middleware/authentication.py`, `app/middleware/rate_limiting.py` | `tests/test_authentication.py`, `tests/test_rate_limiting.py` | done |
| R3 | Every response carries a valid correlation ID (client-supplied if valid, generated otherwise) | `app/middleware/correlation.py` | `tests/test_authentication.py` | done |
| R4 | Every error uses the envelope `{"error":{code,message,correlation_id}}` with no internal detail | `app/errors.py`, `app/middleware/correlation.py` | `tests/test_upstream_errors.py` | done |
| R5 | Request bodies are validated strictly (unknown fields rejected, size limits on input, instructions, metadata, token budget) | `app/schemas/responses.py` | `tests/test_responses.py` | done |

### Limits & cost safety

| ID | Requirement | Source of truth | Tests | Status |
|---|---|---|---|---|
| R6 | Requests above `RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS` get `429` with `Retry-After`, shared across replicas | `app/services/rate_limit.py` | `tests/test_rate_limit_service.py`, `tests/test_rate_limiting.py` | limited (global, not per client) |
| R7 | Only models listed in `OPENAI_ALLOWED_MODELS` reach OpenAI | `app/api/responses.py`, `app/config.py` | `tests/test_responses.py` | done |
| R8 | Automated tests never call OpenAI or need Redis | `tests/conftest.py` | whole suite | done |

### Sync responses

| ID | Requirement | Source of truth | Tests | Status |
|---|---|---|---|---|
| R9 | `POST /v1/responses` requires an `Idempotency-Key` | `app/api/responses.py` | `tests/test_idempotency.py` | done |
| R10 | A matching replay returns the stored completed response with no provider call | `app/services/idempotency.py`, `app/api/responses.py` | `tests/test_idempotency.py` | done |
| R11 | Reusing a key with a different body returns `409`; a concurrent duplicate returns `409` while the first is in flight | `app/api/responses.py` | `tests/test_idempotency.py`, `tests/test_responses.py` | done |
| R12 | A provider timeout keeps the claim so a retry cannot double-bill | `app/api/responses.py` | `tests/test_idempotency.py` | done |
| R13 | Non-completed responses (e.g. `incomplete`) are not replayed; the key is released | `app/api/responses.py` | `tests/test_idempotency.py` | done |
| R14 | Transient provider failures are retried at most twice with capped backoff; permanent ones are not retried | `app/services/retry.py` | `tests/test_retry.py`, `tests/test_upstream_errors.py` | done |

### Async & webhooks

| ID | Requirement | Source of truth | Tests | Status |
|---|---|---|---|---|
| R15 | `POST /v1/responses/background` is idempotent and returns `202` with a job ID and status URL | `app/api/responses.py`, `app/services/jobs.py` | `tests/test_background_responses.py` | done |
| R16 | `GET /v1/responses/{job_id}` returns current job state; non-terminal jobs are reconciled with OpenAI at most once per 5 s | `app/api/responses.py`, `app/services/job_reconciliation.py` | `tests/test_job_status.py`, `tests/test_job_reconciliation.py` | limited (no scheduler) |
| R17 | Terminal job states are written at most once | `app/services/job_reconciliation.py`, `app/services/webhooks.py` | `tests/test_job_reconciliation.py`, `tests/test_webhook_service.py` | done |
| R18 | Webhooks are accepted only with a valid OpenAI signature and a body ≤ 1 MiB | `app/api/webhooks.py` | `tests/test_webhooks.py` | done |
| R19 | Each webhook event is applied at most once, even under concurrent or repeated delivery | `app/services/webhooks.py` | `tests/test_webhook_service.py`, `tests/test_webhooks.py` | done |

### Observability & operations

| ID | Requirement | Source of truth | Tests | Status |
|---|---|---|---|---|
| R20 | Logs are one JSON object per line and never contain prompts, outputs, headers, bodies, or secrets | `app/logging.py` | `tests/test_logging.py` | done |
| R21 | `/health/live` performs no I/O; `/health/ready` fails when Redis is unreachable | `app/api/health.py` | `tests/test_health.py`, `tests/test_readiness.py` | done |
| R22 | Startup fails fast on missing or invalid configuration | `app/config.py` | `tests/test_config.py` | done |
| R23 | Agent/contributor docs stay consistent with code | `scripts/check_docs.py` | `tests/test_doc_drift.py` | done |

## Out of scope

Reject or escalate a request that needs any of these; each requires a new decision first: per-client API keys or quotas · background workers or schedulers · metrics/tracing export · log shipping · streaming responses · tool/function calling · live OpenAI calls in CI · `python-dotenv` or other config loaders.

## Change protocol

1. Add or edit the R row (new IDs are appended; retired rows get status `retired`, never reused).
2. If a flow, state model, Redis key, or invariant moves → update `docs/architecture.md` and its "Verified against" stamp.
3. If the wire contract moves → update `Learning/api-design.md`, the README API tables, and tests.
4. If the change introduces a trade-off that is hard to reverse, surprising, **and** a real trade-off → add a row to `docs/decisions.md` (promote to `docs/adr/NNNN-<slug>.md` only when all three hold and the row cannot hold the rationale).
5. Run the verify ladder in `AGENTS.md`, including `make docs-check`.
6. One task = one commit; docs change in the same commit as the code.

Tests need not embed R-IDs; the `Tests` column is the traceability link.
