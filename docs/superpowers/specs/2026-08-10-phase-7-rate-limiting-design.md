# Phase 7 Redis-Backed Rate Limiting Design

## Goal

Add a shared fixed-window rate limiter backed by the existing Redis client.
The limiter protects internal business routes before billable work exists and
keeps health checks usable for monitoring.

## Scope

- Limit the single configured internal API key with `RATE_LIMIT_REQUESTS` per
  `RATE_LIMIT_WINDOW_SECONDS`.
- Use the shared async Redis client created by the Phase 6 lifespan.
- Increment the window counter and establish its expiry atomically with one
  Redis transaction.
- Return HTTP 429 when the configured limit is exceeded.
- Include a `Retry-After` header containing seconds until the next fixed-window
  boundary.
- Return the existing correlated error envelope with code
  `rate_limit_exceeded`.
- Return the existing correlated `503 upstream_unavailable` envelope when
  Redis cannot serve the counter operation.
- Exempt `/health/live`, `/health/ready`, and `/webhooks/openai` so monitoring
  and signed provider events are not consumed by the internal API quota.
- Keep secrets and authorization credentials out of logs.

## Request flow

The middleware stack remains correlation outside authentication, with rate
limiting inside authentication. Authentication rejects invalid callers before
rate-limit state is touched. Authenticated non-exempt requests then derive a
fixed-window Redis key, increment it, and set expiry on the first increment.
The request continues when the resulting count is at or below the limit; an
over-limit request is rejected before its route handler runs.

The key includes the fixed-window index and a stable wrapper namespace. Since
this phase supports one internal API key, no credential value is included in
the key or logs.

## Atomic Redis operation

Use `pipeline(transaction=True)` with `INCR` and conditional `EXPIRE`. The
transaction is atomic across FastAPI workers sharing Redis. The first request
in a window sets the TTL; subsequent requests only increment the existing
counter. The implementation must preserve the existing async Redis client and
close it through the Phase 6 lifespan.

## Errors and headers

- Limit exceeded: status `429`, error code `rate_limit_exceeded`, generic
  message `Rate limit exceeded.`, `Retry-After: <positive integer>`.
- Redis command failure: status `503`, error code `upstream_unavailable`,
  generic message from the shared error handler, and the normal correlation
  response header.
- Successful requests do not need rate-limit response headers in this phase.

## Testing

Tests use a fake async Redis implementation; they do not require a live Redis
service. Cover the first allowed request, final allowed request, first rejected
request, window expiry, concurrent calls sharing one counter, Redis failure,
health-route exemptions, and authentication occurring before rate limiting.
Run the full existing suite to prevent regressions.

## Learning documentation

Update the learning path and Q&A with why in-memory limits fail across
processes/restarts, why Redis atomicity matters, and how `Retry-After` helps a
caller recover.

## Deliberate deferrals

Per-user or per-tenant quotas, sliding windows, token buckets, distributed
locks, rate-limit response metadata, and production Redis integration tests are
outside this phase.
