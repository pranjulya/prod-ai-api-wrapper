import threading

import pytest


class FakePipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.commands = []

    def incr(self, key):
        self.commands.append(("incr", key))

    def expire(self, key, seconds, nx=False):
        self.commands.append(("expire", key, seconds, nx))

    async def execute(self):
        with self.redis_client.lock:
            key = self.commands[0][1]
            self.redis_client.values[key] = self.redis_client.values.get(key, 0) + 1
            return [self.redis_client.values[key], True]


class FakeRedis:
    def __init__(self, error=None):
        self.error = error
        self.lock = threading.Lock()
        self.pipeline_calls = 0
        self.values = {}

    def pipeline(self, transaction=True):
        if self.error:
            raise self.error
        self.pipeline_calls += 1
        return FakePipeline(self)

    async def ping(self):
        if self.error:
            raise self.error
        return True

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)

    async def aclose(self):
        pass


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


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    monkeypatch.setattr("app.main.create_redis", lambda url: FakeRedis())
