# Phase 6 Redis Integration and Readiness Design

## Scope

Create one async Redis client per FastAPI process, close it during shutdown,
and expose a dependency-aware readiness endpoint without making liveness
depend on Redis.

## Design

`app.clients.redis_client` creates an `redis.asyncio.Redis` client from the
validated `Settings.redis_url`. The FastAPI lifespan stores it on
`app.state.redis` and closes it in a `finally` block. Startup does not ping
Redis, so a Redis outage cannot prevent the process from serving liveness.

`GET /health/ready` pings the shared client. It returns `200` with
`{"status":"ready"}` on success and the standard correlated `503
upstream_unavailable` error on connection failure. The route remains protected
by Phase 5 bearer authentication and never contacts OpenAI.

## Testing

Tests inject a small fake async Redis client and verify creation, shutdown
cleanup, successful readiness, unavailable readiness, and liveness while Redis
is unavailable. No real Redis service is required for the test suite.

## Deliberate Deferrals

Redis-backed rate limiting, idempotency, job records, webhook event records,
and Docker Compose are implemented in their roadmap phases.
