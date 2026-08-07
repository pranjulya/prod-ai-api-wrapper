# Production API Wrapper — Complete Roadmap

## 1. Project goal

Build a production-style FastAPI service that sits between an internal application and the OpenAI Responses API.

The wrapper will:

- Protect the OpenAI API key.
- Authenticate the internal application.
- Validate incoming requests.
- Support synchronous responses.
- Support background responses.
- Receive and verify OpenAI webhooks.
- Store background-job state in Redis.
- Prevent duplicate billable requests.
- Apply rate limits.
- Return consistent errors.
- Produce structured logs and correlation IDs.
- Run locally through Docker Compose.
- Include automated tests and learning documentation.

## 2. Final architecture

```text
Internal application
        |
        | Bearer API key
        | Idempotency-Key
        v
FastAPI wrapper
        |
        |-- Authentication
        |-- Request validation
        |-- Correlation ID
        |-- Rate limiting
        |-- Idempotency handling
        |-- Error translation
        |
        +----------> OpenAI Responses API
        |
        +----------> Redis
                         |
                         |-- Rate-limit counters
                         |-- Idempotency records
                         |-- Background-job state
                         |-- Processed webhook events

OpenAI
   |
   | Signed webhook
   v
FastAPI webhook endpoint
   |
   +----------> Verify and update Redis

Internal application
   |
   | Poll job-status endpoint
   v
FastAPI wrapper
```

## 3. Planned folder structure

Everything should remain inside `Production-API-Wrapper`.

```text
Production-API-Wrapper/
├── README.md
├── ROADMAP.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   │
│   ├── api/
│   │   ├── responses.py
│   │   ├── webhooks.py
│   │   └── health.py
│   │
│   ├── schemas/
│   │   ├── requests.py
│   │   ├── responses.py
│   │   └── errors.py
│   │
│   ├── services/
│   │   ├── response_service.py
│   │   ├── idempotency_service.py
│   │   └── rate_limit_service.py
│   │
│   ├── clients/
│   │   ├── openai_client.py
│   │   └── redis_client.py
│   │
│   └── middleware/
│       ├── authentication.py
│       ├── correlation.py
│       └── logging.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── conftest.py
│
├── Learning/
│   ├── README.md
│   ├── learning-path.md
│   ├── architecture.md
│   ├── api-design.md
│   ├── redis-and-rate-limiting.md
│   ├── idempotency.md
│   ├── background-processing.md
│   ├── webhooks.md
│   ├── error-handling.md
│   ├── observability.md
│   ├── testing-strategy.md
│   ├── production-scenarios.md
│   └── questions-and-answers.md
│
└── scripts/
    └── smoke_test.py
```

Do not create every empty file immediately. Add files only when their phase begins.

# Implementation phases

## Phase 0 — Create and prepare the project

### Tasks

1. Open `/Users/PranjulyaBajpai/src` as the Codex workspace.
2. Create `Production-API-Wrapper`.
3. Initialize Git inside that folder.
4. Create a Python project.
5. Add `.gitignore`.
6. Add `.env.example`.
7. Confirm secrets will never be committed.

### Environment variables

Plan for:

```text
OPENAI_API_KEY
OPENAI_WEBHOOK_SECRET
WRAPPER_API_KEY
REDIS_URL
OPENAI_ALLOWED_MODELS
OPENAI_DEFAULT_MODEL
OPENAI_TIMEOUT_SECONDS
RATE_LIMIT_REQUESTS
RATE_LIMIT_WINDOW_SECONDS
JOB_TTL_SECONDS
IDEMPOTENCY_TTL_SECONDS
LOG_LEVEL
```

### Completion check

- Project opens correctly in Codex.
- Git is initialized.
- No real API keys are stored in tracked files.
- All future work will stay inside the project folder.

---

## Phase 1 — Write the learning documentation foundation

Create:

```text
Learning/README.md
Learning/learning-path.md
Learning/questions-and-answers.md
```

### Document

- What the project proves.
- Prerequisite knowledge.
- Learning objectives.
- Project phases.
- Important vocabulary.
- Questions encountered during implementation.
- Answers explaining why each decision was made.

### Completion check

A learner can read `Learning/README.md` and understand what will be built and why.

---

## Phase 2 — Define the API contract

Design the API before implementing behavior.

### Endpoints

```text
POST /v1/responses
POST /v1/responses/background
GET  /v1/responses/{job_id}
POST /webhooks/openai
GET  /health/live
GET  /health/ready
```

### Limited creation request

Support only:

- `input`
- `instructions`
- `model`
- `max_output_tokens`
- `metadata`

Do not expose every OpenAI parameter.

### Standard headers

```text
Authorization: Bearer <wrapper-api-key>
Idempotency-Key: <unique-client-key>
X-Correlation-ID: <optional-client-correlation-id>
```

If the client does not provide a correlation ID, the wrapper creates one.

### Standard error shape

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Request limit exceeded.",
    "correlation_id": "..."
  }
}
```

### Completion check

- Every endpoint has a documented request and response.
- Status codes are documented.
- Validation rules are explicit.
- No endpoint behavior is ambiguous.

---

## Phase 3 — Create the smallest FastAPI application

### Tasks

- Create the FastAPI application.
- Register the routes.
- Add configuration loading.
- Add startup and shutdown lifecycle handling.
- Add the liveness endpoint.

### Liveness behavior

`GET /health/live` answers:

> Is the FastAPI process running?

It should not depend on OpenAI or Redis.

### Completion check

- The application starts.
- OpenAPI documentation loads.
- `/health/live` returns success.
- Invalid environment configuration fails clearly during startup.

---

## Phase 4 — Configuration and secret management

### Tasks

- Load settings from environment variables.
- Validate required settings.
- Parse the model allowlist.
- Add safe defaults for non-secret settings.
- Prevent secret values from appearing in logs or errors.

### Important scenarios

- Missing OpenAI key.
- Missing wrapper API key.
- Invalid Redis URL.
- Empty model allowlist.
- Invalid timeout or TTL value.

### Completion check

The service refuses to start with unsafe or incomplete configuration and never prints secrets.

---

## Phase 5 — Authentication and correlation IDs

### Authentication

Require a static bearer API key on all internal endpoints.

Do not use wrapper authentication on the OpenAI webhook endpoint. That endpoint uses OpenAI webhook-signature verification instead.

### Correlation IDs

For every request:

1. Accept a valid client correlation ID or create one.
2. Include it in logs.
3. Return it in the response header.
4. Include it in errors.
5. Attach it to background-job metadata.

### Important scenarios

- Missing authorization header.
- Invalid authorization scheme.
- Incorrect API key.
- Missing correlation ID.
- Malformed correlation ID.
- Secret accidentally included in logs.

### Completion check

Unauthorized requests cannot reach OpenAI or Redis-backed business operations.

---

## Phase 6 — Redis integration and readiness

### Redis responsibilities

Redis will store:

- Rate-limit counters.
- Idempotency records.
- Background-job records.
- Processed webhook event IDs.

### Readiness behavior

`GET /health/ready` answers:

> Can this instance serve requests correctly?

It should verify critical dependencies such as Redis.

Avoid calling OpenAI on every readiness check.

### Completion check

- Redis connections are created and closed correctly.
- Readiness fails when Redis is unavailable.
- Liveness continues working when Redis is unavailable.

---

## Phase 7 — Redis-backed rate limiting

Start with a simple fixed-window limit for the single internal API key.

### Expected behavior

- Count requests within a configured time window.
- Perform the increment and expiry atomically.
- Reject requests exceeding the limit.
- Return HTTP `429`.
- Include a `Retry-After` header.
- Log the rejection without logging request secrets.

### Important scenarios

- First request in a new window.
- Final allowed request.
- First rejected request.
- Counter expiration.
- Redis unavailable.
- Concurrent requests.
- Multiple FastAPI workers sharing the same limit.

### Learning outcome

Understand why in-memory rate limits fail across multiple processes and restarts.

### Completion check

Two wrapper instances using the same Redis instance enforce one shared limit.

---

## Phase 8 — Synchronous OpenAI Responses API integration

### Request flow

1. Authenticate the wrapper API key.
2. Assign a correlation ID.
3. Validate the request.
4. Validate the selected model against the allowlist.
5. Apply rate limiting.
6. Check idempotency.
7. Call the OpenAI Responses API.
8. Normalize the result.
9. Store the idempotency result.
10. Return the response.

### Response contents

Return only the fields the internal application needs, such as:

- Wrapper request ID.
- OpenAI response ID.
- Status.
- Model.
- Output text.
- Usage data when available.
- Correlation ID.

### Important scenarios

- Successful response.
- Unsupported model.
- Empty input.
- Input exceeding the wrapper’s limit.
- OpenAI authentication failure.
- OpenAI rate limit.
- OpenAI server error.
- OpenAI timeout.
- Network failure.
- Incomplete model response.

### Completion check

The internal application receives a stable wrapper response instead of depending directly on the complete OpenAI response format.

---

## Phase 9 — Upstream error handling, timeouts, and retries

### Error translation

Map upstream failures into stable wrapper errors.

Examples:

| Situation | Wrapper response |
|---|---|
| Invalid client request | `400` or `422` |
| Invalid wrapper key | `401` |
| Unsupported model | `400` |
| Wrapper rate limit | `429` |
| OpenAI rate limit | `503` or documented `429` policy |
| OpenAI timeout | `504` |
| OpenAI unavailable | `503` |
| Unexpected wrapper failure | `500` |

### Retry rules

Retry only transient failures:

- Connection errors.
- Selected timeout conditions.
- Selected upstream `5xx` responses.
- Possibly upstream `429`, respecting retry information.

Do not retry:

- Authentication errors.
- Validation errors.
- Unsupported models.
- Permanent client errors.

Use a small retry count with exponential backoff and jitter.

### Completion check

Every expected failure produces a consistent, safe response with a correlation ID.

---

## Phase 10 — Idempotency

Idempotency prevents a client retry from creating another billable OpenAI request.

### Required behavior

When receiving an `Idempotency-Key`:

1. Create a stable hash of the validated request.
2. Check Redis for an existing record.
3. If the same key and same request exist, return the stored result.
4. If the same key is used with different content, return `409 Conflict`.
5. If processing is already underway, return a documented in-progress response.
6. Store successful results for the configured TTL.
7. Clear or safely finalize failed in-progress records.

### Important scenarios

- First use of a key.
- Retry after success.
- Retry while processing.
- Same key with a different body.
- Two simultaneous requests using the same key.
- Client timeout after OpenAI completed.
- Redis record expiry.

### Completion check

Concurrent duplicate requests result in at most one OpenAI creation request.

---

## Phase 11 — Background-response creation

### Request flow

1. Authenticate and validate.
2. Apply rate limiting.
3. Apply idempotency.
4. Generate a wrapper job ID.
5. Store a pending job in Redis.
6. Create an OpenAI response using background mode.
7. Store the OpenAI response ID.
8. Return HTTP `202 Accepted`.
9. Include the job-status URL.

### Initial job response

Return:

- Wrapper job ID.
- Status.
- Creation time.
- Expiration time.
- Status URL.
- Correlation ID.

### Job states

Use a controlled set:

```text
pending
in_progress
completed
failed
cancelled
incomplete
expired
```

### Completion check

A background request immediately returns a wrapper job ID without waiting for model completion.

---

## Phase 12 — Background-job status endpoint

### Status flow

`GET /v1/responses/{job_id}` reads the Redis job record.

### Expected responses

- `202` while pending or in progress.
- `200` when completed.
- A documented terminal response for failed, cancelled, or incomplete work.
- `404` when the job does not exist or has expired.

### Security

- Require the wrapper bearer key.
- Do not expose internal Redis keys.
- Do not expose secrets or raw upstream exceptions.

### Completion check

The internal application can poll until it receives a terminal job state.

---

## Phase 13 — OpenAI webhook verification

OpenAI sends webhook events for terminal background-response states. The wrapper must verify the webhook before trusting it.

### Webhook flow

1. Read the raw request body.
2. Verify the webhook signature using the webhook secret.
3. Parse the verified event.
4. Check whether the event ID was already processed.
5. Find the associated background job.
6. Retrieve the final OpenAI response when required.
7. Update the Redis job record.
8. Store the processed event ID.
9. Return success quickly.

### Important events

Handle terminal response events such as:

- Completed.
- Failed.
- Cancelled.
- Incomplete.

### Important scenarios

- Valid webhook.
- Invalid signature.
- Missing signature.
- Duplicate webhook.
- Webhooks delivered out of order.
- Unknown OpenAI response ID.
- Redis temporarily unavailable.
- OpenAI retrieval failure.
- Completed job receives a duplicate terminal event.
- Webhook arrives before local job metadata is fully stored.

### Completion check

Invalid webhooks cannot alter job state, and duplicate webhooks are harmless.

---

## Phase 14 — Structured JSON logging

Every log entry should contain useful searchable fields.

### Suggested fields

- Timestamp.
- Log level.
- Event name.
- Correlation ID.
- Wrapper request or job ID.
- HTTP method.
- Route.
- Status code.
- Duration.
- Retry count.
- OpenAI request ID when available.
- Error category.

### Never log

- OpenAI API keys.
- Wrapper API keys.
- Webhook secrets.
- Authorization headers.
- Full sensitive prompts by default.
- Full model outputs by default.

### Useful event names

```text
request_started
request_completed
authentication_failed
rate_limit_rejected
idempotency_replayed
openai_request_started
openai_request_failed
background_job_created
webhook_verified
webhook_rejected
job_completed
```

### Completion check

A developer can follow one request across the wrapper using its correlation ID.

---

## Phase 15 — Automated testing

Tests should use mocked OpenAI behavior by default.

### Unit tests

Test:

- Request validation.
- Model allowlisting.
- Error mapping.
- Rate-limit calculations.
- Idempotency decisions.
- Job-state transitions.
- Correlation-ID handling.

### Integration tests

Test FastAPI with Redis and a mocked OpenAI gateway:

- Authentication.
- Synchronous success.
- Background creation.
- Status polling.
- Webhook processing.
- Duplicate webhooks.
- Duplicate creation requests.
- Redis failure.
- Upstream timeout.
- Rate-limit rejection.

### Contract tests

Verify that the project’s expected OpenAI request and response shapes match the integration boundary.

### Optional live smoke test

Provide a manually triggered test requiring a real OpenAI key.

It must not run automatically.

### Completion check

The normal test suite:

- Requires no real OpenAI key.
- Creates no billable OpenAI requests.
- Produces deterministic results.
- Covers happy paths and important failures.

---

## Phase 16 — Docker and Docker Compose

### Containers

Use:

- FastAPI wrapper.
- Redis.

Do not add a separate worker because OpenAI performs the background processing.

### Docker requirements

- Run as a non-root user when practical.
- Use a small Python base image.
- Install only required packages.
- Do not copy `.env` or secrets into the image.
- Add a container health check.
- Handle shutdown signals correctly.

### Docker Compose requirements

- Start FastAPI and Redis together.
- Provide Redis networking.
- Provide environment configuration.
- Add Redis and API health checks.
- Avoid embedding real secrets in the Compose file.

### Completion check

One command starts the complete local system, and readiness becomes successful after Redis is available.

---

## Phase 17 — Production scenario exercises

Demonstrate each scenario deliberately.

### Successful scenarios

1. Successful synchronous response.
2. Successful background submission.
3. Background polling before completion.
4. Verified webhook completion.
5. Completed result retrieved through polling.
6. Repeated idempotent request returns the original result.

### Client-error scenarios

7. Missing bearer key.
8. Incorrect bearer key.
9. Missing idempotency key.
10. Invalid request body.
11. Unsupported model.
12. Same idempotency key with different request content.
13. Unknown or expired background job.

### Dependency-failure scenarios

14. Redis unavailable.
15. OpenAI request timeout.
16. OpenAI rate limit.
17. OpenAI temporary server error.
18. OpenAI permanent client error.
19. Network connection failure.

### Webhook scenarios

20. Invalid webhook signature.
21. Duplicate webhook delivery.
22. Unknown response ID.
23. Out-of-order webhook.
24. Webhook processing interrupted and retried.
25. Final result retrieval temporarily fails.

### Concurrency scenarios

26. Concurrent requests under the rate limit.
27. Concurrent requests exceeding the rate limit.
28. Concurrent requests using the same idempotency key.
29. Multiple API instances sharing Redis state.

### Privacy and security scenarios

30. Confirm secrets never appear in logs.
31. Confirm prompts and model output are not logged by default.
32. Confirm unauthorized requests never call OpenAI.
33. Confirm expired Redis results disappear after 24 hours.

---

## Phase 18 — Questions and answers document

Create `Learning/questions-and-answers.md`.

Include questions such as:

1. Why put a wrapper in front of OpenAI?
2. Why should the frontend never receive the OpenAI API key?
3. Why use a limited request schema?
4. Why not pass every OpenAI field through?
5. Why use Redis for rate limiting?
6. Why does in-memory rate limiting fail with multiple workers?
7. What is idempotency?
8. How does idempotency prevent duplicate billing?
9. What should happen when one key is reused with a different request?
10. What is the difference between retries and idempotency?
11. Which failures should be retried?
12. Why should authentication errors not be retried?
13. What is exponential backoff?
14. Why add jitter?
15. What is a correlation ID?
16. How is a correlation ID different from an idempotency key?
17. What is background mode?
18. Why use webhooks instead of continuous OpenAI polling?
19. Why must webhook signatures be verified?
20. Why can webhook events be duplicated?
21. How should out-of-order events be handled?
22. What is the difference between liveness and readiness?
23. Why should readiness check Redis but not constantly call OpenAI?
24. Why avoid logging prompts and outputs?
25. How do mocked tests differ from live integration tests?
26. Why is there no separate task worker?
27. Why retain completed jobs for only 24 hours?
28. What happens after a job expires?
29. How does the system work across multiple FastAPI workers?
30. What would need to change for multiple internal clients?
31. What would need to change for multi-region deployment?
32. What belongs in Project 9 instead of this project?

Add new questions whenever a confusing issue appears during implementation.

---

## Phase 19 — Documentation and portfolio presentation

### Root README

Include:

- Problem statement.
- Business value.
- Architecture diagram.
- Features.
- API examples.
- Local setup.
- Environment variables.
- Testing instructions.
- Production scenarios.
- Security decisions.
- Known limitations.
- Future improvements.

### Learning documentation

Explain:

- What was learned.
- Why each production feature exists.
- Alternative approaches.
- Trade-offs.
- Common mistakes.
- Interview questions.
- Debugging exercises.

### Portfolio demonstration

Demonstrate:

1. A successful synchronous request.
2. A successful background request.
3. Polling before and after webhook completion.
4. An idempotent retry.
5. A rejected duplicate key with changed content.
6. A rate-limit rejection.
7. A rejected forged webhook.
8. A controlled upstream timeout.
9. Correlated JSON logs.

---

## Phase 20 — Final review

### Functional review

- Synchronous requests work.
- Background requests work.
- Webhooks update background jobs.
- Status polling works.
- Idempotency prevents duplicates.
- Rate limiting works across workers.
- Health endpoints behave correctly.

### Security review

- API keys are not committed.
- Secrets are not logged.
- Webhook signatures are verified.
- Request sizes are limited.
- Models are allowlisted.
- Error responses do not reveal internal details.
- Docker does not contain secrets.

### Reliability review

- Timeouts are configured.
- Retries are bounded.
- Retry backoff includes jitter.
- Duplicate webhooks are safe.
- Out-of-order events cannot overwrite newer states.
- Redis keys have TTLs.
- Graceful shutdown works.

### Documentation review

- No `TODO` or `TBD` remains.
- All environment variables are documented.
- Every endpoint is documented.
- Production scenarios are documented.
- `questions-and-answers.md` is complete.
- Architecture matches the actual implementation.

# Recommended implementation order

Follow this exact order:

1. Create the project folder.
2. Initialize Git and Python.
3. Create initial learning documents.
4. Define the API contract.
5. Build the FastAPI skeleton.
6. Add configuration validation.
7. Add bearer authentication.
8. Add correlation IDs and JSON logging.
9. Connect Redis.
10. Add liveness and readiness.
11. Implement Redis-backed rate limiting.
12. Implement synchronous OpenAI requests.
13. Add upstream error mapping and retries.
14. Implement idempotency.
15. Implement background-response creation.
16. Implement job-status polling.
17. Implement verified webhooks.
18. Test duplicate and out-of-order webhooks.
19. Complete automated tests.
20. Add Docker and Docker Compose.
21. Run all production scenarios.
22. Complete learning documentation.
23. Complete `questions-and-answers.md`.
24. Record the portfolio demonstration.
25. Perform the final review.

# How to work with Codex on each phase

Give Codex only one phase at a time.

Use this prompt pattern:

> We are working on Phase [number] of the Production API Wrapper roadmap. First inspect the current repository and relevant documentation. Explain what this phase teaches and propose the smallest suitable design. Do not implement anything until I approve the design. After approval, implement only this phase, add proportionate tests, run verification, and update the relevant Learning documentation. Do not begin the next phase.

At the end of every phase, ask Codex to report:

- What was implemented.
- What files changed.
- What was learned.
- What tests were run.
- Whether all tests passed.
- What was deliberately left for later.
- Which learning document was updated.
- Whether the phase completion criteria were satisfied.

# Final definition of done

The project is complete only when:

- All six endpoints work.
- Authentication is enforced.
- Model selection is allowlisted.
- Rate limiting is shared through Redis.
- Idempotency prevents duplicate OpenAI requests.
- Background jobs can be polled.
- Webhooks are verified and deduplicated.
- Results expire after 24 hours.
- Errors use one consistent format.
- Logs use correlation IDs and exclude secrets.
- Tests are deterministic and mocked by default.
- Docker Compose starts the complete system.
- Important production failures are demonstrated.
- All learning documents are complete.
- `questions-and-answers.md` contains the major design and interview questions.
- The README explains the project’s business value and technical decisions.