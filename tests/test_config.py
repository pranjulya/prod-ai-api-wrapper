import pytest

from app.config import ConfigError, load_settings


def test_allowlist_strips_and_deduplicates_models(monkeypatch):
    monkeypatch.setenv("OPENAI_ALLOWED_MODELS", " gpt-5-mini , gpt-4o , gpt-5-mini ")

    assert load_settings().allowed_models == ("gpt-5-mini", "gpt-4o")


def test_default_model_must_be_allowed(monkeypatch):
    monkeypatch.setenv("OPENAI_ALLOWED_MODELS", "gpt-4o")
    monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)

    with pytest.raises(ConfigError, match="OPENAI_DEFAULT_MODEL"):
        load_settings()


@pytest.mark.parametrize(
    "name", ["OPENAI_API_KEY", "OPENAI_WEBHOOK_SECRET", "WRAPPER_API_KEY"]
)
def test_missing_secret_is_reported_without_its_value(monkeypatch, name):
    monkeypatch.delenv(name)

    with pytest.raises(ConfigError, match=name) as error:
        load_settings()

    assert "test-" not in str(error.value)


@pytest.mark.parametrize("value", ["redis:///0", "http://redis:6379/0"])
def test_invalid_redis_url_is_rejected(monkeypatch, value):
    monkeypatch.setenv("REDIS_URL", value)

    with pytest.raises(ConfigError, match="REDIS_URL"):
        load_settings()


def test_missing_redis_url_is_rejected(monkeypatch):
    monkeypatch.delenv("REDIS_URL")

    with pytest.raises(ConfigError, match="REDIS_URL"):
        load_settings()


@pytest.mark.parametrize("value", ["", "gpt-5-mini,", ",gpt-5-mini", "gpt-5-mini,,gpt-4o"])
def test_empty_or_malformed_allowlist_is_rejected(monkeypatch, value):
    monkeypatch.setenv("OPENAI_ALLOWED_MODELS", value)

    with pytest.raises(ConfigError, match="OPENAI_ALLOWED_MODELS"):
        load_settings()


@pytest.mark.parametrize(
    "name", [
        "OPENAI_TIMEOUT_SECONDS",
        "RATE_LIMIT_REQUESTS",
        "RATE_LIMIT_WINDOW_SECONDS",
        "JOB_TTL_SECONDS",
        "IDEMPOTENCY_TTL_SECONDS",
    ],
)
@pytest.mark.parametrize("value", ["0", "-1", "slow"])
def test_operational_settings_must_be_positive_integers(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ConfigError, match=name):
        load_settings()


def test_settings_repr_hides_secrets():
    settings = load_settings()

    assert "test-openai-key" not in repr(settings)
    assert "test-webhook-secret" not in repr(settings)
    assert "test-wrapper-key" not in repr(settings)
