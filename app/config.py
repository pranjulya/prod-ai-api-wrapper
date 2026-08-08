import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = field(repr=False)
    openai_webhook_secret: str = field(repr=False)
    wrapper_api_key: str = field(repr=False)
    redis_url: str
    allowed_models: tuple[str, ...]
    default_model: str
    openai_timeout_seconds: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    job_ttl_seconds: int
    idempotency_ttl_seconds: int
    log_level: str


def load_settings() -> Settings:
    allowed_models = _allowed_models(_required("OPENAI_ALLOWED_MODELS"))
    default_model = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    if default_model not in allowed_models:
        raise ConfigError("OPENAI_DEFAULT_MODEL must be in OPENAI_ALLOWED_MODELS")
    return Settings(
        openai_api_key=_required("OPENAI_API_KEY"),
        openai_webhook_secret=_required("OPENAI_WEBHOOK_SECRET"),
        wrapper_api_key=_required("WRAPPER_API_KEY"),
        redis_url=_redis_url(_required("REDIS_URL")),
        allowed_models=allowed_models,
        default_model=default_model,
        openai_timeout_seconds=_positive("OPENAI_TIMEOUT_SECONDS", 30),
        rate_limit_requests=_positive("RATE_LIMIT_REQUESTS", 60),
        rate_limit_window_seconds=_positive("RATE_LIMIT_WINDOW_SECONDS", 60),
        job_ttl_seconds=_positive("JOB_TTL_SECONDS", 86400),
        idempotency_ttl_seconds=_positive("IDEMPOTENCY_TTL_SECONDS", 86400),
        log_level=_log_level(),
    )


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _redis_url(value: str) -> str:
    try:
        parsed = urlparse(value)
    except ValueError:
        raise ConfigError("REDIS_URL is invalid") from None
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ConfigError("REDIS_URL is invalid")
    return value


def _allowed_models(value: str) -> tuple[str, ...]:
    models = [model.strip() for model in value.split(",")]
    if not all(models):
        raise ConfigError("OPENAI_ALLOWED_MODELS is invalid")
    return tuple(dict.fromkeys(models))


def _positive(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ConfigError(f"{name} must be a positive integer") from None
    if value < 1:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _log_level() -> str:
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in LOG_LEVELS:
        raise ConfigError("LOG_LEVEL is invalid")
    return log_level
