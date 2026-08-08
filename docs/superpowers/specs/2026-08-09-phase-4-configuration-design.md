# Phase 4 Configuration Design

## Scope

Load all wrapper settings from environment variables and reject incomplete or
unsafe configuration at application startup.

## Design

`app.config` remains a standard-library dataclass and loader. It requires
non-empty `OPENAI_API_KEY`, `OPENAI_WEBHOOK_SECRET`, `WRAPPER_API_KEY`,
`REDIS_URL`, and `OPENAI_ALLOWED_MODELS`. The loader validates a Redis URL with
the `redis` or `rediss` scheme and a hostname; parses a non-empty,
comma-separated model allowlist; and requires an explicit default model to be
one of the allowed models.

`OPENAI_TIMEOUT_SECONDS`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`,
`JOB_TTL_SECONDS`, and `IDEMPOTENCY_TTL_SECONDS` must be positive integers.
They, `LOG_LEVEL`, and the default model use the safe defaults in
`.env.example` when omitted. Secret fields are excluded from dataclass repr,
and configuration errors name only the invalid variable, never its value.

## Testing

Tests set dummy secrets in the environment and cover missing secrets, malformed
Redis URLs, empty allowlists, default models outside the allowlist, invalid
positive integers, and secret-free error messages. Existing liveness tests
continue to validate startup using dummy settings.

## Deliberate Deferrals

No `.env` loader, secret manager, Redis connection, or OpenAI client is added
in this phase. Environment injection remains the deployment boundary.
