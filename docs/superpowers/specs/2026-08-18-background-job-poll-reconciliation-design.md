# Background Job Poll Reconciliation Design

**Date:** 2026-08-18
**Status:** Approved for planning
**Scope:** Recover background jobs when an OpenAI webhook is missing or delayed

## Problem

`GET /v1/responses/{job_id}` currently reads only Redis. A background job reaches a terminal local state only when `POST /webhooks/openai` processes a terminal event. If that webhook is not delivered or cannot be verified, Redis continues to report `pending` or `in_progress` until the job expires, even when OpenAI has already completed the paid request.

OpenAI supports retrieving a response by ID, and background-mode response data used for polling is retained for roughly ten minutes. Status polling must therefore be a recovery path while webhooks remain the normal fast path.

## Goals

- Reconcile a non-terminal local job with OpenAI during status polling.
- Return a recovered terminal result from the same `GET` request.
- Prevent concurrent polls from creating an upstream request stampede.
- Preserve the first terminal state when polling and webhook delivery race.
- Keep transient OpenAI failures from making the cached status unavailable.
- Preserve a useful terminal record when OpenAI permanently reports the response missing.

## Non-goals

- No scheduled worker or queue-based reconciler.
- No guarantee when neither a webhook nor a client poll occurs during OpenAI's retrieval window.
- No new dependency or public endpoint.
- No change to background-response creation or webhook authentication.

## Selected Approach

Use hybrid reconciliation:

1. Webhooks remain the fast path.
2. `GET /v1/responses/{job_id}` first reads Redis as it does today.
3. Terminal jobs, expired jobs, and jobs without `openai_response_id` never contact OpenAI.
4. For a non-terminal job with an OpenAI response ID, acquire a per-job Redis reconciliation lease.
5. If another request owns the lease or the job is cooling down, return the cached job with HTTP `202`.
6. The lease owner retrieves the response from OpenAI and reconciles Redis.
7. The request reads the winning Redis record after reconciliation and returns `200` for a terminal state or `202` for a non-terminal state.

The existing authentication middleware and global Redis rate limiter continue to apply to the status endpoint. The per-job lease adds stampede protection; it does not replace the global client-facing rate limit.

## Reconciliation Lease

Use a hashed, namespaced Redis key so neither the local job ID nor provider response ID appears in the key. Acquisition uses `SET NX EX` with an opaque owner token and a processing TTL long enough to cover all bounded OpenAI attempts.

When the owner finishes, an owner-checked Lua operation changes the lease to a short cooldown state. Competing requests do not wait; they immediately return the cached job. A stale owner cannot replace a newer lease.

The implementation will use fixed internal timing values rather than add configuration that has no demonstrated operational need. Tests will assert ownership, expiry, and cooldown behavior.

## Provider Status Mapping

A shared job-record helper will be used by both the webhook and polling paths:

| OpenAI status | Local status | Stored result |
|---|---|---|
| `queued` | `pending` | Existing public fields |
| `in_progress` | `in_progress` | Existing public fields |
| `completed` | `completed` | Normalized model, output text, and usage |
| `failed` | `failed` | Terminal status |
| `cancelled` | `cancelled` | Terminal status |
| `incomplete` | `incomplete` | Terminal status |

An unknown provider status does not mutate the job and the cached non-terminal result is returned.

## Missing Provider Response

If OpenAI returns HTTP `404`, atomically finalize the job as `failed` and store this safe public error:

```json
{
  "code": "background_response_unavailable",
  "message": "Background response is no longer available."
}
```

`JobRecord` and `BackgroundJobResponse` gain an optional typed `error` field. Existing responses are unchanged because null fields remain excluded.

## Failure Semantics

- Timeout, connection failure, `429`, or provider `5xx`: log the safe error category, do not mutate the job, enter cooldown, and return the cached record with HTTP `202`.
- Provider authentication failure: preserve the job and use the existing safe HTTP `503` contract.
- Other provider `4xx`: preserve the job and use the existing safe error mapping.
- Redis failure: use the existing HTTP `503` contract.
- Unexpected exception: use the existing correlated HTTP `500` contract.

No provider exception text, response ID, job provider ID, output, or secret may be logged.

## Concurrency and Atomicity

Polling finalization uses a Redis Lua compare-and-set operation:

- Read the current job record.
- If it is already terminal, return it unchanged.
- Otherwise write the candidate record with the remaining original TTL.

The existing webhook finalizer retains its atomic event-plus-job update. Both finalizers treat terminal states as absorbing, so the first terminal update wins and a late webhook or poll cannot overwrite it.

Non-terminal reconciliation updates may be skipped if another path already made the job terminal. The response always re-reads Redis after an attempted update rather than returning an uncommitted candidate.

## Observability

Reuse the existing structured OpenAI request and failure events with operation `retrieve`. Successful poll recovery emits the existing safe job-completion fields and sets the request-scoped OpenAI request ID when available. Reconciliation lease contention is normal and does not require warning-level logging.

## Testing

Tests will verify:

- Terminal jobs and jobs without a provider ID do not call OpenAI.
- A completed provider response is normalized, atomically stored, and returned as HTTP `200`.
- Provider non-terminal statuses remain HTTP `202`.
- Timeout, connection, `429`, and `5xx` return the cached HTTP `202` record.
- Provider `404` becomes a stored terminal failure with the safe error.
- Authentication and other permanent provider errors preserve the job and follow existing safe errors.
- A per-job lease prevents concurrent retrieval and enforces cooldown ownership.
- Polling and webhook finalization races preserve the first terminal state.
- Redis failures remain safe and correlated.
- Logs contain no provider response IDs, output, exception text, or secrets.
- The full automated test suite remains green.

## Operational Limitation

This design repairs the polling contract but is client-driven. OpenAI documents that background-mode response data used for polling is stored for roughly ten minutes. If both webhook delivery and client polling are absent throughout that interval, recovery is not guaranteed. Add a scheduled reconciler only if that stronger guarantee becomes a requirement.

## References

- [OpenAI Responses: retrieve a response](https://developers.openai.com/api/reference/resources/responses/methods/retrieve)
- [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint)
- [OpenAI webhook events](https://developers.openai.com/api/reference/resources/webhooks)
