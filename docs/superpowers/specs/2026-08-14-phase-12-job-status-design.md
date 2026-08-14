# Phase 12 Background Job Status Design

## Goal

Add an authenticated polling endpoint that reads durable background-job state
from Redis and returns a stable public representation.

## Endpoint

`GET /v1/responses/{job_id}` requires the existing wrapper bearer key,
correlation middleware, and rate limiting. It does not require an
`Idempotency-Key` and never contacts OpenAI.

Wrapper job IDs must match the generated `job_<uuid4>` format. Malformed IDs,
unknown records, expired Redis records, and records explicitly marked
`expired` all return the same `404 job_not_found` response.

## Status responses

- `pending` and `in_progress`: HTTP `202 Accepted`.
- `completed`, `failed`, `cancelled`, and `incomplete`: HTTP `200 OK`.
- `expired`, missing, or malformed: HTTP `404 job_not_found`.
- Redis failure: HTTP `503 upstream_unavailable`.

The response uses `BackgroundJobResponse`: wrapper job ID, controlled status,
creation and expiry timestamps, wrapper status URL, and correlation ID. It
never exposes the Redis key or OpenAI response ID.

## Storage behavior

Add a `get_job(redis, job_id)` helper that reads the existing namespaced Redis
key and validates the stored JSON as `JobRecord`. The endpoint performs no
writes and does not extend the job TTL.

## Testing

Use fake Redis records. Cover every controlled state, missing and malformed
IDs, expired state, Redis TTL disappearance, Redis failure, authentication,
correlation headers, public-field filtering, and proof that OpenAI is not
called. Run the full regression suite.

## Deliberate deferrals

Terminal output retrieval, webhook updates, event deduplication, cancellation,
and live Redis/OpenAI integration tests remain outside this phase.
