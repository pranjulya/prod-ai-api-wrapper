# Phase 4 Configuration Design

## Scope

Load all wrapper settings from environment variables and reject incomplete or
unsafe configuration at application startup.

## Design

`app.config` remains a standard-library dataclass and loader. It requires
non-empty `OPENAI_API_KEY`, `OPENAI_WEBHOOK_SECRET`, `WRAPPER_API_KEY`,
`REDIS_URL`, and `OPENAI_ALLOWED_MODELS`. The loader validates a Redis URL with
the `redis` or `rediss` scheme and a hostname. It splits the allowlist on
commas, strips each token, rejects empty tokens (including leading, trailing,
or doubled commas), and deduplicates remaining models while preserving order.
The resulting allowlist must not be empty.

`OPENAI_TIMEOUT_SECONDS`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`,
`JOB_TTL_SECONDS`, and `IDEMPOTENCY_TTL_SECONDS` must be positive integers.
They and `LOG_LEVEL` use the safe defaults in `.env.example` when omitted.
When `OPENAI_DEFAULT_MODEL` is unset or empty, its effective value is
`gpt-5-mini`; that effective value must always be a member of the allowlist.
For example, `OPENAI_ALLOWED_MODELS=gpt-4o` with no default model fails at
startup. Secret fields are excluded from dataclass repr, and configuration
errors name only the invalid variable, never its value.

## Testing

`tests/conftest.py` supplies an autouse fixture with dummy secrets, a valid
Redis URL, and an allowlist containing `gpt-5-mini`; individual tests override
only the variable under test. Tests cover missing secrets, malformed Redis
URLs, empty and malformed allowlists, default models outside the allowlist,
invalid positive integers, and secret-free error messages. Existing liveness
tests continue to validate startup using the shared dummy settings.

## Deliberate Deferrals

No `.env` loader, secret manager, Redis connection, or OpenAI client is added
in this phase. Environment injection remains the deployment boundary.
