# Phase 8 Synchronous OpenAI Responses Design

## Goal

Expose a controlled synchronous `POST /v1/responses` endpoint that validates
internal requests, calls OpenAI through the official async SDK, and returns a
stable wrapper response.

## Scope

- Add the official `openai` Python SDK dependency.
- Create one shared `AsyncOpenAI` client during FastAPI lifespan startup and
  close it during shutdown.
- Require the existing wrapper bearer authentication, correlation ID, and
  Redis rate-limit middleware.
- Validate the JSON body and reject unknown fields.
- Require `input` as a non-blank string of 1–50,000 characters.
- Accept optional non-blank `instructions` up to 10,000 characters.
- Resolve omitted `model` to `Settings.default_model`; reject models outside
  `Settings.allowed_models` with `400 unsupported_model`.
- Accept optional `max_output_tokens` from 1 through 16,384.
- Accept optional metadata with at most 16 string key/value pairs, key lengths
  from 1 through 64, and value lengths up to 512.
- Send only these approved fields to `client.responses.create`.
- Return a stable response containing a wrapper response ID, OpenAI response
  ID, provider status, model, output text, usage when available, and the
  correlation ID.
- Test with a fake async OpenAI client; never call the live provider in tests.

## Request and response models

The request model uses strict extra-field rejection. A missing model is
resolved before the provider call. Validation errors use the existing
`validation_error` envelope; an allowlist failure uses `unsupported_model`.

The wrapper response shape is:

```json
{
  "id": "wrp_resp_<uuid>",
  "openai_response_id": "resp_...",
  "status": "completed",
  "model": "gpt-5-mini",
  "output_text": "...",
  "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
  "correlation_id": "request-123"
}
```

`usage` may be `null` when the provider response does not include usage.
`output_text` is taken from the SDK response's normalized output text field.

## Request flow

1. Correlation middleware assigns or validates the correlation ID.
2. Authentication verifies the wrapper bearer key.
3. Rate limiting checks the shared Redis counter.
4. FastAPI validates the request body.
5. The route resolves and validates the model allowlist.
6. The route calls the shared async OpenAI client with only approved fields.
7. The route maps the provider response into the wrapper schema.

## Error boundaries

This phase owns request validation and unsupported-model errors. Provider
authentication failures, rate limits, timeouts, network failures, server
errors, and incomplete-response policy are explicitly deferred to Phase 9.
The route must not expose API keys, raw provider exceptions, prompts, or model
output in errors.

## Testing

Use a fake async OpenAI client and fake response objects. Cover successful
default-model and explicit-model calls, exact request-field forwarding,
unknown fields, blank/oversized input and instructions, invalid token limits,
metadata limits, unsupported models, missing authentication, correlation IDs,
and stable response normalization. Run the full existing suite.

## Deliberate deferrals

Idempotency records and duplicate-billing protection, provider retries and
detailed upstream error translation, background responses, job persistence,
webhooks, streaming, tools, arbitrary Responses API parameters, and live
OpenAI integration tests are outside this phase.
