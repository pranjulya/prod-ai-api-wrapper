# Phase 13: OpenAI Webhook Verification Design

## Goal

Accept OpenAI background-response terminal events only after signature
verification, update the matching Redis job exactly once, and make completed
output available through the existing job-status endpoint.

The endpoint processes events inline. It returns success only after Redis holds
the terminal job state and the event is durably marked as processed. Temporary
failures return a non-2xx response so OpenAI retries delivery.

## Scope

- Add `POST /webhooks/openai`.
- Verify the raw body and request headers with the official OpenAI Python SDK.
- Handle `response.completed`, `response.failed`, `response.cancelled`, and
  `response.incomplete`.
- Deduplicate verified events across API instances with Redis.
- Resolve an OpenAI response ID to the existing wrapper job without scanning
  Redis.
- Retrieve and normalize the final OpenAI response for completed events.
- Preserve safe correlated errors and the existing authentication/rate-limit
  exemptions for the exact webhook path.

## Non-goals

- A separate queue or worker process.
- FastAPI in-process background tasks.
- OpenAI dashboard configuration, public tunneling, or live webhook tests.
- Streaming, response cancellation endpoints, or structured JSON logging.
- Storing or returning the raw webhook body or raw OpenAI response.

## Public contract

`POST /webhooks/openai` does not accept the wrapper bearer key. A successfully
verified and processed event returns:

```json
{"received": true}
```

Missing or invalid signatures return the standard correlated error with HTTP
`401` and code `invalid_webhook_signature`. Unsupported but validly signed event
types return `200 {"received": true}` without changing job state.

`GET /v1/responses/{job_id}` keeps its existing status-code behavior. Completed
jobs additionally return optional top-level `model`, `output_text`, and `usage`
fields. Active and non-completed terminal jobs omit those fields.

## Components

### OpenAI client

Pass `OPENAI_WEBHOOK_SECRET` to the existing `AsyncOpenAI` client as
`webhook_secret`. Keep SDK retries disabled; the wrapper's existing retry policy
remains the only provider retry layer.

### Webhook route

Add a small router dedicated to `POST /webhooks/openai`. The handler streams at
most 1 MiB into memory, then calls
`request.app.state.openai.webhooks.unwrap(raw_body, request.headers)`. Larger
bodies return `413 request_too_large`. No JSON parsing or Redis access occurs
before `unwrap` succeeds.

The route translates `InvalidWebhookSignatureError` into the stable webhook
authentication error. Other processing is delegated to a webhook service.

### Redis webhook service

Use hashed, namespaced Redis keys so raw event and provider response IDs do not
appear in Redis key names:

```text
webhook:event:<sha256(event_id)>
openai-response-job:<sha256(openai_response_id)>
```

The event key has two values:

- `processing:<random-owner-token>`: temporary ownership of the event.
- `processed`: durable deduplication marker.

Claim an event with `SET key processing:<random-owner-token> NX EX
<processing_ttl>`. Derive the processing TTL as `max(60, 3 *
OPENAI_TIMEOUT_SECONDS + 10)` so it covers the maximum three provider attempts
allowed by the existing two-retry policy. Release and finalization use atomic
compare-by-token Redis scripts, so an expired owner cannot delete or complete a
new owner's claim. A process crash leaves a temporary claim that expires and
permits a later delivery to retry.

After success, replace the value with `processed` and retain it for at least
259,200 seconds, matching OpenAI's documented delivery retry window of up to 72
hours. A duplicate with `processed` returns success immediately. A concurrent
duplicate that observes `processing` returns `503`, ensuring delivery is retried
if the current owner fails.

### Job lookup and result storage

When background creation receives the OpenAI response ID, store the updated job
and its reverse mapping in one Redis transaction. Give the reverse mapping the
same remaining TTL as the job. This avoids Redis scans and ensures the mapping
does not outlive the job.

Extend the internal and public job schemas with optional `model`, `output_text`,
and `usage` fields. Reuse the synchronous response normalization rules for
completed output rather than storing the provider object.

## Processing flow

1. Read the raw request body.
2. Verify and parse it with `webhooks.unwrap`.
3. Return success immediately for unsupported verified event types.
4. Atomically claim the verified event ID.
5. Return success if the event is already processed; return retryable `503` if
   another instance is processing it.
6. Resolve `event.data.id` through the hashed reverse mapping and load the job.
7. If the mapping or job is absent, release the event claim and return `503`.
   This covers a webhook arriving before background-creation metadata is stored.
8. If the job is already terminal, do not overwrite it. Atomically mark the new
   event processed and return success.
9. For `response.completed`, retrieve the OpenAI response using the existing
   wrapper retry policy. Require a terminal completed response, normalize its
   model, output text, and usage, and set the job to `completed`.
10. Map the other supported event types directly to `failed`, `cancelled`, or
    `incomplete`.
11. In one Redis transaction, update the job with its remaining TTL and replace
    the event claim with the long-lived `processed` marker.
12. Return `200 {"received": true}`.

Terminal job states are absorbing. The first successfully processed terminal
event wins; later duplicate or out-of-order terminal events are acknowledged but
cannot overwrite the stored terminal state or completed result.

## Failure behavior

| Situation | Response | State effect |
| --- | --- | --- |
| Missing or invalid signature | `401 invalid_webhook_signature` | No Redis or response retrieval |
| Body larger than 1 MiB | `413 request_too_large` | No signature verification, Redis, or response retrieval |
| Unsupported verified event | `200` | No job mutation |
| Previously processed event | `200` | No job mutation |
| Concurrent processing | `503 upstream_unavailable` | Existing owner continues |
| Unknown response mapping or missing job | `503 upstream_unavailable` | Claim released for retry |
| Redis unavailable | `503 upstream_unavailable` | Event remains retryable |
| OpenAI timeout during completed retrieval | `504 upstream_timeout` | Claim released for retry |
| Transient OpenAI retrieval failure | `503 upstream_unavailable` | Claim released for retry |
| Unexpected failure | `500 internal_error` | Claim is released when Redis is available |

All failures use the existing correlation middleware and safe error shape. Never
log the signing secret, signature headers, authorization headers, raw body,
prompt, model output, Redis values, or raw upstream exceptions.

## Atomicity and concurrency

Redis is the coordination authority across API instances. Event claiming uses
`SET NX`; token-aware Lua scripts release or finalize only the current owner's
claim. Finalization atomically checks that the stored job is still non-terminal,
updates it, and marks the event processed. This makes terminal states absorbing
even when different terminal events race. Background creation stores the
provider-to-job mapping with the updated job in one transaction.

The design deliberately avoids acknowledging an event before durable completion.
OpenAI performs the model work; this wrapper does not need a second worker merely
to move the webhook update into another process.

## Tests

Tests use fake Redis and fake OpenAI clients; they never require real credentials
or create billable requests.

- The client is configured with the webhook secret and SDK retries remain off.
- The raw body and headers reach `webhooks.unwrap` unchanged.
- Missing and invalid signatures return safe correlated `401` errors before any
  Redis or OpenAI response operation.
- Fixed-length and chunked bodies larger than 1 MiB return safe correlated `413`
  errors without signature verification or state access.
- Each supported terminal event produces the expected state.
- A completed event retrieves once, stores normalized output, and exposes it via
  authenticated polling.
- Unsupported verified events return success without mutations.
- Sequential and concurrent duplicate deliveries do not repeat retrieval or
  overwrite state.
- Later out-of-order terminal events cannot replace an existing terminal state.
- An expired owner cannot release or finalize a replacement owner's claim.
- Unknown response IDs and the metadata race return retryable `503`; a later
  delivery succeeds after the mapping appears.
- Redis errors, OpenAI timeouts, and transient OpenAI failures leave the event
  retryable.
- Event and reverse-index keys contain hashes rather than raw IDs and use the
  required TTLs.
- The webhook path remains exempt from wrapper authentication and rate limiting.
- The full existing test suite stays green.

## Documentation basis

The official OpenAI webhook guide documents raw-body SDK verification with
`webhooks.unwrap`, duplicate delivery, successful `2xx` acknowledgement, and
delivery retries for up to 72 hours:

<https://developers.openai.com/api/docs/guides/webhooks>

The webhook event reference defines the four terminal background-response event
shapes used here:

<https://developers.openai.com/api/reference/resources/webhooks>
