# Phase 11 Background Response Creation Design

## Goal

Add an authenticated, idempotent `POST /v1/responses/background` endpoint that
creates an OpenAI background response, persists a durable wrapper job in Redis,
and immediately returns `202 Accepted`.

## Request contract

The endpoint accepts the existing strict `ResponsesRequest` body and requires
`Idempotency-Key`. It reuses authentication, correlation IDs, model allowlist
validation, rate limiting, provider retry/error handling, and the Phase 10
idempotency behavior.

Only approved request fields are forwarded to OpenAI. The provider call adds
`background=True` and does not enable streaming or tools.

## Job record

Before the provider call, create a wrapper job ID in the form `job_<uuid>` and
store a Redis record with `JOB_TTL_SECONDS`:

```json
{
  "id": "job_<uuid>",
  "status": "pending",
  "openai_response_id": null,
  "created_at": "2026-08-14T10:00:00Z",
  "expires_at": "2026-08-15T10:00:00Z",
  "status_url": "/v1/responses/job_<uuid>",
  "correlation_id": "request-123"
}
```

Redis keys use a wrapper namespace and never expose the raw idempotency key.
After OpenAI accepts the background request, update the job to `in_progress`
and store the provider response ID while preserving the original expiry.

## Response and idempotency

Return the public job fields with HTTP `202`. Store that normalized response in
the idempotency record. A retry with the same key and request replays the same
job response without another provider call or job creation. Reusing the key
with different content and concurrent in-progress retries use the existing
Phase 10 conflict behavior.

## Failure behavior

If job storage fails, do not call OpenAI. If the provider call ultimately
fails, delete the pending job record and release the idempotency claim. If the
provider accepted the response but the job update fails, return a correlated
`503 upstream_unavailable`; the idempotency record is released, while the
pending job expires automatically. Error responses never expose Redis keys,
provider bodies, prompts, API keys, or raw exceptions.

## Testing

Use fake async Redis and OpenAI clients. Cover successful creation, exact
`background=True` forwarding, pending-to-in-progress persistence, configured
TTL, `202` response shape, idempotent replay, mismatched and in-progress keys,
initial Redis failure, provider failure cleanup, update failure, authentication,
validation, model allowlist, correlation IDs, and full regression tests.

## Deliberate deferrals

Job polling, terminal status mapping, result retrieval, webhook verification,
webhook deduplication, cancellation, and live Redis/OpenAI integration tests are
reserved for later phases.
