# Phase 14 Structured JSON Logging Design

## Goal

Emit one machine-parseable JSON object per log line so a developer can trace a
wrapper request across HTTP handling, authentication, rate limiting,
idempotency, OpenAI calls, background jobs, and webhooks using its correlation
ID.

The phase covers application logs plus Uvicorn server and access logs. It does
not add log shipping, distributed tracing, metrics, dashboards, or an external
observability dependency.

## Constraints

- Use Python's standard `logging` package and standard-library JSON support.
- Keep existing API status codes, response bodies, and correlation headers.
- Apply the validated `LOG_LEVEL` to application and Uvicorn loggers.
- Emit only explicitly approved fields from application events.
- Logging must not trigger OpenAI calls, Redis calls, or billable work.
- Logging failure must not change request handling.
- Tests use captured records or streams; no external logging service is needed.

## Architecture

Add `app/logging.py` with three responsibilities:

1. `JsonFormatter` converts a `LogRecord` into one compact JSON object.
2. `configure_logging(level)` applies the formatter and level to the root,
   application, `uvicorn`, `uvicorn.error`, and `uvicorn.access` handlers.
3. `log_event(logger, level, event, **fields)` emits an application event after
   discarding unknown, absent, or non-primitive fields.

`JsonFormatter` always returns valid JSON. If it receives a malformed record,
it falls back to the four common fields with `event="logging_error"` rather
than raising. `log_event` never enables `exc_info` or `stack_info` and suppresses
an unexpected logging-infrastructure exception so observability cannot change
the API result.

The module also owns a correlation-ID `ContextVar`. `CorrelationMiddleware`
binds the request correlation ID before downstream processing and resets it in
a `finally` block. `log_event` adds the bound correlation ID when the caller
does not provide one. This keeps retry and service-layer events correlated
without passing the request object into those layers.

Configure logging once when `app.main` is imported so Uvicorn handlers already
created by its CLI receive the JSON formatter before server and access records
are emitted. Use a safe `INFO` fallback during this bootstrap. The application
lifespan then reapplies the validated settings value; an invalid `LOG_LEVEL`
still fails startup through the existing configuration error.

Configuration is idempotent. It updates existing handlers rather than stacking
new ones. Application and Uvicorn records use managed stdout stream handlers;
stderr is not used by the configured loggers. Test-only capture handlers remain
attachable without becoming production handlers.

## Common record contract

Every record contains:

| Field | Format |
| --- | --- |
| `timestamp` | UTC ISO-8601 with a trailing `Z` |
| `level` | Lowercase logging level |
| `event` | Stable snake-case event name |
| `logger` | Source logger name |

Application events may additionally contain only these fields:

| Field | Meaning |
| --- | --- |
| `correlation_id` | Validated or generated wrapper correlation ID |
| `method` | HTTP method |
| `route` | Resolved route template when available; otherwise path without query string |
| `status_code` | HTTP response status |
| `duration_ms` | Non-negative elapsed milliseconds from a monotonic clock |
| `job_id` | Wrapper background-job ID, never the provider response ID |
| `retry_count` | Retries already made: `0` initial attempt, `1` first retry, `2` second retry |
| `openai_request_id` | OpenAI diagnostic request ID when the SDK exposes one |
| `error_category` | Stable safe category from the table below |
| `operation` | Bounded operation name such as `create`, `background_create`, or `retrieve` |
| `retry_after` | Integer delay returned for a rate-limit rejection |
| `webhook_type` | Verified OpenAI event type from the supported or ignored event set |

No field is emitted with a null value. Booleans, strings, integers, and finite
floats are accepted. Enums are converted to their string values. Other values
are omitted rather than stringified.

## Request lifecycle

`CorrelationMiddleware` remains the outer middleware. It performs this flow:

1. Validate or generate the correlation ID and bind it to request state and the
   logging context.
2. Record a monotonic start time.
3. Emit `request_started` with correlation ID and method. A route is included
   only if Starlette has already resolved one.
4. Preserve the existing invalid-correlation and exception handling behavior;
   an invalid correlation ID sets `error_category="validation"` on its
   completion event.
5. Resolve the route template from `request.scope["route"].path` after
   downstream handling, falling back to the URL path without its query string.
6. Emit `request_completed` with method, route, status code, and duration.
   A successful synchronous response also includes the diagnostic OpenAI
   request ID placed on request state by the route when the SDK exposes one.
7. Add the response correlation header and reset the logging context.

Unexpected exceptions also emit `request_failed` at error level with
`error_category="internal"`. They do not include the exception message,
arguments, traceback, request body, or headers. The existing correlated 500
response remains unchanged.

## Domain events

Each event is emitted at the existing decision point after the stated outcome
is known:

| Event | Emission point | Required event fields |
| --- | --- | --- |
| `authentication_failed` | Bearer authentication rejects the request | method, route, status 401, category `authentication` |
| `rate_limit_rejected` | Shared Redis limiter rejects the request | method, route, status 429, retry_after, category `rate_limit` |
| `idempotency_replayed` | A completed synchronous or background result is replayed | operation; job_id for background replay |
| `openai_request_started` | Immediately before the wrapper retry loop | operation, retry_count 0 |
| `openai_request_failed` | After each failed provider attempt | operation, retry_count, category; diagnostic request ID if available |
| `background_job_created` | Job, reverse mapping, and idempotency result are durable | job_id, operation `background_create`; request ID if available |
| `webhook_verified` | SDK signature verification and parsing succeed | webhook_type |
| `webhook_rejected` | Required signature headers are absent, verification fails, or body exceeds 1 MiB | status code and category `webhook_signature` or `request_too_large` |
| `job_completed` | Redis confirms a completed event won terminal finalization | original job correlation ID, job_id, operation `retrieve`; request ID if available |

`openai_request_failed` records the attempt that failed. An initial attempt has
`retry_count=0`; the two allowed retry attempts have `1` and `2`. Permanent
errors produce one failure event. Transient errors produce one event per failed
attempt. Error mapping and retry behavior do not change.

The existing retry service owns the single OpenAI-exception classification
function and emits the per-attempt failure event. Callers provide the bounded
operation name. Response routes emit the start event before entering the retry
service and copy a successful SDK diagnostic request ID into request state or
their durable outcome event. OpenAI response IDs are never used as diagnostic
request IDs.

The webhook finalization result must distinguish "job updated" from "job was
already terminal." This prevents a racing completed event from emitting
`job_completed` when a failed, cancelled, incomplete, or expired event actually
won. The Redis mutation remains atomic and terminal states remain absorbing.
`job_completed` explicitly overrides the webhook delivery context with the
correlation ID stored on the background job, linking creation and completion.

## Error categories

Use this fixed vocabulary:

| Category | Situation |
| --- | --- |
| `authentication` | Missing or invalid wrapper bearer credential |
| `rate_limit` | Wrapper rate limit rejected the request |
| `validation` | Correlation ID or request validation failed |
| `redis` | Redis operation unavailable |
| `openai_timeout` | OpenAI timeout |
| `openai_connection` | OpenAI connection failure |
| `openai_rate_limit` | OpenAI returned rate limiting |
| `openai_authentication` | OpenAI authentication failed |
| `openai_4xx` | Other permanent OpenAI 4xx response |
| `openai_5xx` | OpenAI server response |
| `webhook_signature` | Missing or invalid OpenAI webhook signature |
| `request_too_large` | Webhook body exceeds 1 MiB |
| `internal` | Unexpected wrapper failure |

Categories describe the boundary failure, not raw exception text.

## Uvicorn records

- `uvicorn.access` records use `event="uvicorn_access"` and extract method,
  route/path, and status code from the documented access-log arguments. Query
  strings are removed.
- `uvicorn` and `uvicorn.error` records use `event="uvicorn_server"` and the
  static safe message `"Uvicorn server record."`; raw messages and arguments
  are never rendered.
- Other third-party records use `event="third_party_log"` and a static safe
  message. Their original formatted message, arguments, exception information,
  and stack information are not serialized.

Uvicorn access logging may duplicate the wrapper's `request_completed` event.
Both are retained because the former describes the server boundary and the
latter carries the wrapper correlation and resolved route template.

## Sensitive-data policy

Never serialize:

- OpenAI API keys, wrapper API keys, or webhook secrets.
- Authorization or webhook signature headers.
- Idempotency keys.
- Request or webhook bodies.
- Prompts, input items, model output, or full response objects.
- Redis keys or stored Redis values.
- OpenAI response IDs or webhook event IDs.
- Query strings.
- Raw exception messages, exception arguments, tracebacks, or object dumps.

Model names and token usage are also omitted in this phase because the roadmap
does not require them for request tracing.

## Tests

Tests must prove:

- The formatter emits exactly one valid JSON object per record with UTC time,
  lowercase level, stable event, and logger.
- Configuration is idempotent and applies `LOG_LEVEL` to application and
  Uvicorn loggers without duplicate handlers.
- Uvicorn server and access records are JSON; server records use the static
  safe message and access records exclude query strings.
- A normal request emits correlated start and completion records with method,
  resolved route template, status, and non-negative duration.
- Invalid correlation IDs and unexpected failures preserve existing responses
  and emit safe records. Invalid correlation completion uses category
  `validation`; unexpected failure uses category `internal`.
- Authentication, rate limiting, idempotency replay, OpenAI attempts,
  background creation, webhook verification/rejection, and completed jobs emit
  their specified events at the correct decision points.
- Retry counts are `0`, `1`, and `2`, with no extra provider attempt.
- A racing late completed event does not emit `job_completed` when another
  terminal state already won.
- Known credential, header, key, prompt, output, webhook, Redis, query-string,
  and exception-message sentinels do not appear in serialized logs.
- All existing tests remain green and no test uses real credentials, Redis, or
  OpenAI requests.

## Completion check

Given a correlation ID, a developer can find the request lifecycle and every
related wrapper event in JSON logs. All stdout records owned by the application
or Uvicorn are machine parseable, and sensitive request/provider data is absent.
