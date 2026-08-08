# Phase 4 Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load, validate, and safely represent all wrapper environment settings during application startup.

**Architecture:** Extend the standard-library `app.config` module with one immutable `Settings` dataclass and `load_settings()` loader. A shared pytest fixture supplies dummy environment values; tests override only the value needed for each behavior.

**Tech Stack:** Python 3.12+, FastAPI, pytest, standard library (`dataclasses`, `os`, `urllib.parse`).

## Global Constraints

- Do not add a configuration dependency.
- Require non-empty `OPENAI_API_KEY`, `OPENAI_WEBHOOK_SECRET`, `WRAPPER_API_KEY`, `REDIS_URL`, and `OPENAI_ALLOWED_MODELS`.
- Accept only `redis` and `rediss` URLs with a hostname.
- Split model allowlists on commas, strip tokens, reject empty tokens, and deduplicate while preserving order.
- Resolve an absent or empty `OPENAI_DEFAULT_MODEL` to `gpt-5-mini`, then require it in the allowlist.
- Require positive integer timeout, rate-limit, and TTL values.
- Never include a secret value in a settings representation or configuration error.

---

### Task 1: Validate complete startup configuration

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`
- Modify: `app/config.py`
- Modify: `tests/test_health.py`

**Interfaces:**
- Consumes: Environment variables named in `.env.example`.
- Produces: `Settings` and `load_settings() -> Settings`; invalid configuration raises `ConfigError(ValueError)` with a value-free message.

- [ ] **Step 1: Add shared dummy configuration and failing tests**

```python
# tests/conftest.py
import pytest


@pytest.fixture(autouse=True)
def valid_environment(monkeypatch):
    for name, value in {
        "OPENAI_API_KEY": "test-openai-key",
        "OPENAI_WEBHOOK_SECRET": "test-webhook-secret",
        "WRAPPER_API_KEY": "test-wrapper-key",
        "REDIS_URL": "redis://localhost:6379/0",
        "OPENAI_ALLOWED_MODELS": "gpt-5-mini,gpt-4o",
    }.items():
        monkeypatch.setenv(name, value)
```

```python
# tests/test_config.py
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
```

- [ ] **Step 2: Run test to verify the missing interface**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`

Expected: FAIL during collection because `ConfigError` does not exist.

- [ ] **Step 3: Implement the minimal settings loader**

```python
class ConfigError(ValueError):
    pass


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
```

Use `field(repr=False)` for the three secret dataclass fields. `_redis_url()` checks `urlparse(value).scheme` and `.hostname`; `_positive()` catches `ValueError` and rejects values less than one. Each helper raises `ConfigError` using the environment variable name only.

- [ ] **Step 4: Expand tests and verify them**

```python
@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "OPENAI_WEBHOOK_SECRET", "WRAPPER_API_KEY"])
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
```

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_health.py -q`

Expected: PASS with all configuration and liveness tests green.

- [ ] **Step 5: Commit**

Run: `git add app/config.py tests/conftest.py tests/test_config.py tests/test_health.py && git commit -m "feat: validate application settings"`

### Task 2: Document configuration behavior

**Files:**
- Modify: `Learning/learning-path.md`

**Interfaces:**
- Consumes: The final `Settings` behavior from Task 1.
- Produces: A completed configuration milestone that tells learners validation occurs before serving requests.

- [ ] **Step 1: Update the configuration learning milestone**

```markdown
5. **Configuration (complete)** — load environment settings, validate secrets and operational limits at startup, and keep secret values out of errors.
```

- [ ] **Step 2: Verify documentation and the full suite**

Run: `rg -q 'Configuration \(complete\)' Learning/learning-path.md && .venv/bin/python -m pytest -q && .venv/bin/python -m compileall -q app && git diff --check`

Expected: exit status `0` and all tests pass.

- [ ] **Step 3: Commit**

Run: `git add Learning/learning-path.md && git commit -m "docs: record configuration milestone"`
