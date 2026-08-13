# Phase 10 Redis-Backed Idempotency Design

## Goal

Prevent duplicate billable synchronous OpenAI requests when the internal
application retries with the same idempotency key.

## Scope

- Require `Idempotency-Key` on `POST /v1/responses`.
- Reject blank or malformed keys with the existing validation error contract.
- Hash the already validated request payload deterministically, including the
  effective model and all approved request fields.
- Atomically claim a Redis record with `SET key value NX EX` before calling
  OpenAI.
- Store the request hash, `in_progress` state, and correlation ID in the record.
- Same key and same hash while processing returns `409 idempotency_in_progress`.
- Same key with a different hash returns `409 idempotency_key_reused`.
- After success, store the normalized wrapper response and replay it for the
  same key until `IDEMPOTENCY_TTL_SECONDS` expires.
- On provider failure, delete the in-progress record so a later retry can
  safely attempt the request again.
- Redis failures return the existing correlated `503 upstream_unavailable`.
- Ensure concurrent requests result in at most one OpenAI creation call.

## Data and flow

The Redis key is namespaced and includes a digest of the idempotency key so the
raw client key is not exposed in logs or unrelated key scans. The JSON value is
small and contains `request_hash`, `state`, and, after success, `response`.

The route validates the body and resolves the effective model first. It then
computes the request hash, attempts the atomic claim, and branches on the
existing record. Only the claimant calls OpenAI. The successful normalized
response is written back with the configured TTL before returning.

## Testing

Use a fake async Redis implementation supporting `set(..., nx=True, ex=...)`,
`get`, and `delete`, plus a fake OpenAI client. Cover first use, same-key
replay, mismatched payload, in-progress state, expiry, concurrent claims,
provider failure cleanup, Redis failure, required-key validation, and full
regression tests. No live Redis or OpenAI service is required.

## Deliberate deferrals

Background idempotency, webhook deduplication, cross-region coordination,
long-running lock renewal, and idempotency response compression remain out of
scope.
