# Phase 9 Upstream Errors, Timeouts, and Retries

## Goal

Translate OpenAI SDK failures into safe, correlated wrapper errors and retry
only transient provider failures.

## Retry policy

- Make at most two retries after the initial provider request.
- Retry connection errors, timeouts, provider HTTP 5xx responses, and provider
  HTTP 429 responses.
- Honor provider retry metadata for 429 responses when available.
- Otherwise use exponential backoff of 0.1 seconds and 0.2 seconds with small
  random jitter.
- Never retry authentication failures, validation failures, unsupported models,
  or other permanent 4xx responses.
- Inject the sleep and random source so tests never wait in real time.

## Error mapping

| Provider failure | Wrapper status | Code |
| --- | ---: | --- |
| Timeout after retries | 504 | `upstream_timeout` |
| Connection/5xx/429 exhausted | 503 | `upstream_unavailable` |
| Provider authentication failure | 503 | `upstream_unavailable` |
| Unexpected provider failure | 500 | `internal_error` |

Every response uses the existing correlated error envelope. Messages remain
generic and never include API keys, prompts, model output, raw exceptions, or
provider response bodies.

## Request flow

The existing request validation, model allowlist, authentication, correlation,
and Redis rate limiting run before the provider call. The route delegates the
provider call to a retry helper, then maps the final exception through the
shared error handler. Validation and unsupported-model failures happen before
the helper and are never retried.

## Testing

Use fake async OpenAI clients and injected sleep/random functions. Cover a
successful first attempt, transient failure followed by success, retry
exhaustion, timeout mapping, connection/5xx/429 mapping, non-retryable
authentication and permanent 4xx failures, retry metadata, correlation IDs,
safe messages, and no secret leakage. Run the full existing suite.

## Deliberate deferrals

Idempotency, background jobs, webhook processing, streaming, provider-specific
business error bodies, and live OpenAI integration tests remain deferred.
