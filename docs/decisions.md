# Architectural Decisions & Rationale Index

Decisions recorded here represent binding architectural constraints. A full Architectural Decision Record (ADR) is created under `docs/adr/NNNN-*.md` only when a decision is hard to reverse, surprising, and involves a major trade-off. Index rows first; promote lazily.

## Decision Index

| Decision | Status | Rationale source | Consequence / limit |
|---|---|---|---|
| Redis over in-process memory | Accepted | `docs/superpowers/specs/2026-08-15-phase-13-openai-webhooks-design.md` | Any replica can handle any request; zero in-process state survives a request. Requires running Redis 7. |
| Official SDK with `max_retries=0` | Accepted | `docs/superpowers/specs/2026-08-12-phase-8-openai-responses-design.md` | Single unified retry layer in `app/services/retry.py`; prevents hidden SDK amplification loops. |
| Atomic fixed-window rate limiter | Accepted | `docs/superpowers/specs/2026-08-10-phase-7-rate-limiting-design.md` | Pipelined `INCR` + `EXPIRE NX`; boundary bursts up to 2× quota possible across window resets. |
| Single global bearer wrapper key | Accepted | `docs/superpowers/specs/2026-08-10-phase-5-authentication-correlation-design.md` | Evaluated in constant time (`hmac.compare_digest`). No per-client tenant segregation or quota. |
| Client idempotency key + SHA-256 fingerprint | Accepted | `docs/superpowers/specs/2026-08-13-phase-10-idempotency-design.md` | Distinguishes identical replays from payload mutations on repeated key submissions. |
| Claim TTL = `processing_ttl` | Accepted | `docs/superpowers/specs/2026-08-15-phase-13-openai-webhooks-design.md` | Crash recovery occurs automatically after `max(60, 3·timeout + 2·MAX_RETRY_DELAY + 10)`. |
| Keep claim on provider timeout | Accepted | `docs/superpowers/specs/2026-08-13-phase-9-upstream-errors-design.md` | Provider may still bill or process in-flight call; immediate retry blocked to avoid double-billing. |
| Lua CAS + owner tokens for terminal writes | Accepted | `docs/superpowers/specs/2026-08-15-phase-13-openai-webhooks-design.md` | Prevents race conditions between webhook callbacks and manual polling reconciliation. |
| Webhook event deduplication TTL = 72 h | Accepted | `docs/superpowers/specs/2026-08-15-phase-13-openai-webhooks-design.md` | Outlives the 24 h `JOB_TTL_SECONDS` to ensure delayed re-deliveries from OpenAI are ignored. |
| Poll-driven reconciliation with 5 s cooldown | Accepted | `docs/superpowers/specs/2026-08-18-background-job-poll-reconciliation-design.md` | Avoids standalone background worker/daemon processes; limits redundant upstream polling. |
| Allowlist logging + third-party scrubbing | Accepted | `docs/superpowers/specs/2026-08-16-phase-14-structured-json-logging-design.md` | Zero prompt, output, secret, or header leakage in production JSON logs. |
| No `python-dotenv` dependency | Accepted | `docs/superpowers/specs/2026-08-20-blockers-and-local-operations-design.md` | Runtime environment injected by container orchestrator or process supervisor; keeps runtime lean. |
| Non-root `python:3.12-slim` Docker image | Accepted | `docs/superpowers/specs/2026-08-20-blockers-and-local-operations-design.md` | Runs as unprivileged `appuser` with multi-stage build; minimal attack surface. |

## Historical Spec Corpus Index

Historical phase specs preserved in `docs/superpowers/specs/` and corresponding execution plans in `docs/superpowers/plans/`:

| Date | Spec File | Plan File | Core Subject & Outcome |
|---|---|---|---|
| 2026-08-07 | `docs/superpowers/specs/2026-08-07-phase-0-project-setup-design.md` | `docs/superpowers/plans/2026-08-07-phase-0-project-setup.md` | Initial repo scaffolding, uv configuration, and toolchain setup. |
| 2026-08-09 | `docs/superpowers/specs/2026-08-09-phase-4-configuration-design.md` | `docs/superpowers/plans/2026-08-09-phase-4-configuration.md` | Typed immutable `Settings` dataclass and fail-fast environment parsing. |
| 2026-08-10 | `docs/superpowers/specs/2026-08-10-phase-5-authentication-correlation-design.md` | `docs/superpowers/plans/2026-08-10-phase-5-authentication-correlation.md` | Bearer authentication middleware and correlation ID propagation. |
| 2026-08-10 | `docs/superpowers/specs/2026-08-10-phase-6-redis-readiness-design.md` | `docs/superpowers/plans/2026-08-10-phase-6-redis-readiness.md` | Redis connection factory and `/health/ready` probe integration. |
| 2026-08-10 | `docs/superpowers/specs/2026-08-10-phase-7-rate-limiting-design.md` | `docs/superpowers/plans/2026-08-10-phase-7-rate-limiting.md` | Distributed fixed-window rate limiting middleware using atomic pipeline. |
| 2026-08-12 | `docs/superpowers/specs/2026-08-12-phase-8-openai-responses-design.md` | `docs/superpowers/plans/2026-08-12-phase-8-openai-responses.md` | Synchronous responses endpoint schema, normalization, and SDK client wiring. |
| 2026-08-13 | `docs/superpowers/specs/2026-08-13-phase-9-upstream-errors-design.md` | `docs/superpowers/plans/2026-08-13-phase-9-upstream-errors.md` | Upstream OpenAI error taxonomy, safe status mapping, and retry backoff. |
| 2026-08-13 | `docs/superpowers/specs/2026-08-13-phase-10-idempotency-design.md` | `docs/superpowers/plans/2026-08-13-phase-10-idempotency.md` | Two-phase distributed idempotency locking with request payload hashing. |
| 2026-08-14 | `docs/superpowers/specs/2026-08-14-phase-11-background-responses-design.md` | `docs/superpowers/plans/2026-08-14-phase-11-background-responses.md` | Background job initiation (`POST /v1/responses/background`) and initial record storage. |
| 2026-08-14 | `docs/superpowers/specs/2026-08-14-phase-12-job-status-design.md` | `docs/superpowers/plans/2026-08-14-phase-12-job-status.md` | Polling endpoint (`GET /v1/responses/{job_id}`) for job state observation. |
| 2026-08-15 | `docs/superpowers/specs/2026-08-15-phase-13-openai-webhooks-design.md` | `docs/superpowers/plans/2026-08-15-phase-13-openai-webhooks.md` | Cryptographic signature verification, event deduplication, and atomic updates. |
| 2026-08-16 | `docs/superpowers/specs/2026-08-16-phase-14-structured-json-logging-design.md` | `docs/superpowers/plans/2026-08-16-phase-14-structured-json-logging.md` | Zero-PII JSON logging formatter, allowed fields allowlist, and Uvicorn log sanitization. |
| 2026-08-18 | `docs/superpowers/specs/2026-08-18-background-job-poll-reconciliation-design.md` | `docs/superpowers/plans/2026-08-18-background-job-poll-reconciliation.md` | Active polling reconciliation for non-terminal jobs with 5 s cooldown mutex. |
| 2026-08-18 | `docs/superpowers/specs/2026-08-18-redis-post-provider-failure-design.md` | `docs/superpowers/plans/2026-08-18-redis-post-provider-failure.md` | Resilience strategy when Redis operations fail following successful provider completion. |
| 2026-08-20 | `docs/superpowers/specs/2026-08-20-blockers-and-local-operations-design.md` | `docs/superpowers/plans/2026-08-20-blockers-and-local-operations.md` | Final production readiness, probe alignment, and Docker Compose deployment. |
