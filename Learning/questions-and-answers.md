# Questions and Answers

Add questions here as implementation reveals trade-offs. These initial answers
explain the roadmap decisions already made.

## Why use a wrapper instead of letting the internal application call OpenAI?

The wrapper keeps the OpenAI API key in one service and gives the internal
application a stable, deliberately smaller API contract. It also centralizes
controls such as authentication, rate limiting, retries, and logs.

## Why expose only a limited set of response-creation fields?

A limited contract is easier to validate, document, test, and evolve. The
wrapper can add a field when there is a real internal use case instead of
coupling clients to every upstream option.

## Why is Redis required?

Rate-limit counters, idempotency records, job state, and processed webhook
events must be shared by all API instances and survive an individual process
restart. In-memory state cannot provide that.

## Why not use an in-memory rate-limit counter?

Workers and instances would each see a different counter, and a process
restart would erase its history. A shared Redis counter keeps the limit
consistent across workers and restarts.

## Why must the counter increment and expiry be atomic?

`INCR` and the first-hit expiry are sent in one Redis transaction. This avoids
two requests racing to initialize the same fixed-window key without an expiry,
which could leave a counter that never resets.

## Why are health routes exempt from rate limiting?

Liveness and readiness probes must remain observable during traffic spikes or
upstream incidents. They still have their own authentication rules where
required, but should not consume the business request budget.

## How should callers handle a rate-limit response?

A rejected request returns HTTP 429 and a `Retry-After` header. Callers should
wait at least that many seconds before retrying, then retry with backoff rather
than issuing a tight loop.

## Why do background responses need both Redis and webhooks?

Redis gives the internal application a durable job record to poll. Verified
webhooks allow the wrapper to update that record promptly when OpenAI reports
a terminal state.

## Why verify a webhook before parsing or updating Redis?

The signature covers the raw body and delivery headers. Verifying first prevents
a forged request from selecting a job, triggering OpenAI retrieval, or changing
shared state.

## Why keep processed webhook event IDs in Redis?

OpenAI can deliver the same event more than once. A shared atomic Redis claim
makes duplicate delivery harmless across workers and API instances, while a
short processing state allows recovery after an interrupted attempt. Each claim
contains a random owner token, and atomic compare-by-token updates prevent an
expired worker from releasing or finalizing a newer worker's claim.

## Why return an error instead of acknowledging temporary webhook failures?

A successful response tells OpenAI that delivery is complete. Returning a safe
non-2xx response when Redis or retrieval is unavailable preserves OpenAI's retry
mechanism and prevents accepted events from being lost.

## Why does background creation not need a separate worker?

OpenAI performs the model work when the wrapper sends `background=True`. The
wrapper only persists a durable Redis job, returns `202 Accepted`, and later
uses polling and verified webhooks to observe terminal state.

## Why store a wrapper job instead of returning only the OpenAI response ID?

The wrapper job keeps provider identifiers internal and gives clients a stable
status URL, expiry, correlation ID, and controlled state model independent of
the complete OpenAI response format.

## How should clients poll a background job?

The status endpoint returns `202` while a job is pending or in progress and
`200` for terminal states. Polling reads Redis first. For a non-terminal job with an OpenAI response ID,
one caller per Redis cooldown may retrieve OpenAI and atomically store the
result; webhooks remain the fast path. Polling never creates a second model
response and does not extend the job's original expiry. OpenAI retains background responses for roughly
ten minutes; this wrapper does not enforce that retention as a polling cutoff and has no scheduled
reconciler. If both webhook delivery and client polling are absent, the wrapper has no scheduled worker
to observe or store terminal state.

## Why do unknown and expired jobs return the same error?

Both return `404 job_not_found`. This keeps the public contract simple and
avoids revealing whether a particular internal job identifier previously
existed. Once Redis removes an expired record, it is no longer available.

## Why require an idempotency key for billable work?

Networks and clients retry. An idempotency key lets the wrapper recognize a
repeat of the same validated request and return the saved result instead of
creating another upstream request.

## How does Redis idempotency prevent duplicate requests?

The wrapper hashes the validated request and atomically claims the key with
Redis `SET NX EX` before calling OpenAI. Only the claimant may create billable
work; later requests replay the completed response, reject a different payload
with a conflict, or report that the original request is still running.

## What happens when the provider call fails?

The in-progress record is deleted after the final provider failure, allowing a
later retry to claim the key safely instead of leaving a permanent lock.

## Why use correlation IDs?

They connect the client response, structured logs, retries, background job
metadata, and errors, making a single request diagnosable without recording
sensitive prompts or credentials.

## Why use structured JSON instead of formatted log sentences?

Stable event and field names let log tools filter by correlation ID, route,
status, retry count, or error category without parsing human prose. A strict
field allowlist also makes the sensitive-data boundary testable.

## Why omit raw exception messages and request bodies?

Those values can contain credentials, prompts, model output, or upstream data.
The wrapper records a stable category and diagnostic request ID instead, which
supports investigation without copying sensitive content into logs.

## Do correlation IDs authorize a request?

No. Bearer authentication controls access by proving that the caller has the
required internal key. A correlation ID only identifies a request for tracing;
it does not authorize the caller or grant access.

## Why can readiness fail while liveness remains successful?

Liveness only shows that the process and HTTP server are running. Readiness
also checks whether Redis is reachable with `PING`, so a Redis outage can make
the instance unable to serve work while it remains alive and able to recover.

## Why isolate the OpenAI SDK behind a client adapter?

The route should own the wrapper contract, not provider-specific client details.
An adapter keeps SDK construction and calls in one place, makes fake clients
easy to use in tests, and lets the provider integration change without
spreading SDK types through the API layer.

## Why reject unknown request fields?

Unknown fields are rejected so callers cannot silently depend on behavior the
wrapper has not documented or tested. This keeps the internal contract small
and makes accidental typos fail at the boundary.

## Why does the wrapper enforce a model allowlist?

The allowlist prevents callers from selecting arbitrary models, which protects
cost, capability, and policy boundaries. A request may use only a configured
model, with the configured default used when the model is omitted.

## Why normalize provider responses?

The provider response contains more detail than internal callers need and may
change as the SDK evolves. Returning a stable normalized shape keeps clients
decoupled from provider response objects and gives the wrapper a clear place to
control which output is exposed.

## Which upstream failures should be retried?

Transient failures such as connection errors, timeouts, and provider 5xx
responses may succeed when attempted again. Permanent failures such as invalid
credentials, malformed requests, and unsupported models should be translated
and returned immediately; retrying them only adds latency and load.

## Why are retries bounded and jittered?

The wrapper makes only a small, fixed number of retry attempts with exponential
backoff and jitter. A bound prevents one request from consuming resources
indefinitely, while jitter spreads simultaneous retries so a provider incident
does not create a synchronized retry storm.

## Why translate upstream errors instead of returning them directly?

The wrapper returns stable error codes and correlated responses while hiding
provider details, credentials, and raw exception text. This keeps the internal
contract predictable and prevents sensitive implementation details from
leaking to callers.
