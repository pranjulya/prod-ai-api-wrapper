# API Contract

This is the wrapper's public contract. Clients use only the fields and endpoints below; arbitrary OpenAI Responses API parameters are rejected.

## Common rules

All request and response bodies are JSON. Unknown request fields are rejected. All authenticated endpoints require:

```http
Authorization: Bearer <wrapper-api-key>
X-Correlation-ID: <optional-client-id>
```

Creation endpoints also require `Idempotency-Key: <unique-client-key>`.

`X-Correlation-ID` must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. If omitted, the wrapper generates one and returns it in the response header. `/webhooks/openai` does not use wrapper bearer authentication; it accepts only a valid OpenAI webhook signature.

## Response creation request

`POST /v1/responses` and `POST /v1/responses/background` accept the same body:

```json
{
  "input": "Summarize this incident report.",
  "instructions": "Use three bullet points.",
  "model": "gpt-5-mini",
  "max_output_tokens": 500,
  "metadata": {"ticket_id": "INC-123"}
}
```

| Field | Required | Validation |
| --- | --- | --- |
| `input` | Yes | Non-blank string of 1–50,000 characters. |
| `instructions` | No | Non-blank string of at most 10,000 characters when present. |
| `model` | No | A model in `OPENAI_ALLOWED_MODELS`; omitted uses `OPENAI_DEFAULT_MODEL`. |
| `max_output_tokens` | No | Integer from 1 to 16,384. |
| `metadata` | No | Object with at most 16 string key/value pairs; keys are 1–64 characters and values are at most 512 characters. |

The wrapper sends only these fields to OpenAI. It never accepts client-supplied API keys, tools, streaming options, callbacks, or arbitrary upstream fields.

## Endpoints

| Endpoint | Authentication | Success | Purpose |
| --- | --- | --- | --- |
| `POST /v1/responses` | Bearer key + idempotency key | `200` | Create and wait for a response. |
| `POST /v1/responses/background` | Bearer key + idempotency key | `202` | Create a background response and return a wrapper job. |
| `GET /v1/responses/{job_id}` | Bearer key | `202` or `200` | Read a background job. |
| `POST /webhooks/openai` | OpenAI signature | `200` | Accept a verified OpenAI event. |
| `GET /health/live` | Bearer key | `200` | Confirm the FastAPI process is running. |
| `GET /health/ready` | Bearer key | `200` or `503` | Confirm required dependencies are available. |

### Synchronous response

`POST /v1/responses` returns `200 OK`:

```json
{
  "id": "wrp_resp_01H...",
  "openai_response_id": "resp_01H...",
  "status": "completed",
  "model": "gpt-5-mini",
  "output_text": "- Item one\\n- Item two\\n- Item three",
  "usage": {"input_tokens": 42, "output_tokens": 18, "total_tokens": 60},
  "correlation_id": "request-123"
}
```

### Background response and job status

`POST /v1/responses/background` returns `202 Accepted`:

```json
{
  "id": "job_01H...",
  "status": "pending",
  "created_at": "2026-08-07T10:00:00Z",
  "expires_at": "2026-08-08T10:00:00Z",
  "status_url": "/v1/responses/job_01H...",
  "correlation_id": "request-123"
}
```

`GET /v1/responses/{job_id}` returns `202 Accepted` for `pending` or `in_progress`, `200 OK` for `completed`, `404 Not Found` after expiry or for an unknown job, and `200 OK` with a terminal `failed`, `cancelled`, or `incomplete` status for other completed work.

### Health and webhook responses

`GET /health/live` returns `200` with `{"status":"live"}` without contacting Redis or OpenAI. `GET /health/ready` returns `200` with `{"status":"ready"}` only when Redis is reachable; otherwise it returns `503` with the standard error shape. A verified webhook returns `200` with `{"received":true}`. Invalid webhook signatures return `401`.

## Errors

Every error uses this shape:

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Request limit exceeded.",
    "correlation_id": "request-123"
  }
}
```

| Status | Code | Meaning |
| --- | --- | --- |
| `400` | `invalid_request` or `unsupported_model` | The JSON is syntactically valid but violates this contract. |
| `401` | `authentication_failed` or `invalid_webhook_signature` | Authentication or signature verification failed. |
| `404` | `job_not_found` | The requested job does not exist or has expired. |
| `409` | `idempotency_key_reused` | An idempotency key was reused with a different request. |
| `422` | `validation_error` | A field fails type, presence, or size validation. |
| `429` | `rate_limit_exceeded` | The wrapper rate limit was exceeded. |
| `500` | `internal_error` | An unexpected wrapper error occurred. |
| `503` | `upstream_unavailable` | Redis or OpenAI cannot serve the request. |
| `504` | `upstream_timeout` | OpenAI did not respond before the configured timeout. |

Error messages never contain API keys, authorization headers, webhook secrets, raw upstream exceptions, prompts, or model output.
