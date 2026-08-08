import pytest


@pytest.fixture(autouse=True)
def valid_environment(monkeypatch):
    for name in {
        "OPENAI_DEFAULT_MODEL",
        "OPENAI_TIMEOUT_SECONDS",
        "RATE_LIMIT_REQUESTS",
        "RATE_LIMIT_WINDOW_SECONDS",
        "JOB_TTL_SECONDS",
        "IDEMPOTENCY_TTL_SECONDS",
        "LOG_LEVEL",
    }:
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "OPENAI_API_KEY": "test-openai-key",
        "OPENAI_WEBHOOK_SECRET": "test-webhook-secret",
        "WRAPPER_API_KEY": "test-wrapper-key",
        "REDIS_URL": "redis://localhost:6379/0",
        "OPENAI_ALLOWED_MODELS": "gpt-5-mini,gpt-4o",
    }.items():
        monkeypatch.setenv(name, value)
