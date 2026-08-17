import json
import logging
import threading

import pytest

from app.logging import JsonFormatter


class FakePipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.commands = []

    def incr(self, key):
        self.commands.append(("incr", key))

    def expire(self, key, seconds, nx=False):
        self.commands.append(("expire", key, seconds, nx))

    def set(self, key, value, nx=False, ex=None):
        self.commands.append(("set", key, value, nx, ex))

    def delete(self, key):
        self.commands.append(("delete", key))

    async def execute(self):
        results = []
        with self.redis_client.lock:
            for command in self.commands:
                if command[0] == "incr":
                    key = command[1]
                    value = self.redis_client.values.get(key, 0) + 1
                    self.redis_client.values[key] = value
                    results.append(value)
                elif command[0] == "expire":
                    _, key, seconds, _ = command
                    self.redis_client.expirations[key] = seconds
                    results.append(True)
                elif command[0] == "set":
                    _, key, value, nx, seconds = command
                    if nx and key in self.redis_client.values:
                        results.append(False)
                        continue
                    self.redis_client.values[key] = value
                    if seconds is not None:
                        self.redis_client.expirations[key] = seconds
                    results.append(True)
                elif command[0] == "delete":
                    self.redis_client.values.pop(command[1], None)
                    results.append(True)
        return results


class FakeRedis:
    def __init__(self, error=None):
        self.error = error
        self.lock = threading.Lock()
        self.pipeline_calls = 0
        self.values = {}
        self.expirations = {}

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
        with self.lock:
            if nx and key in self.values:
                return False
            self.values[key] = value
            if ex is not None:
                self.expirations[key] = ex
            return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)

    async def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        values = args[numkeys:]
        with self.lock:
            if script.startswith("-- release-webhook-event"):
                key = keys[0]
                if self.values.get(key) != values[0]:
                    return 0
                self.values.pop(key, None)
                return 1
            if script.startswith("-- mark-webhook-event-processed"):
                key = keys[0]
                if self.values.get(key) != values[0]:
                    return 0
                self.values[key] = values[1]
                self.expirations[key] = int(values[2])
                return 1
            if script.startswith("-- finalize-webhook-event"):
                event_key, stored_job_key = keys
                owner, serialized_job, job_ttl, processed, processed_ttl = values
                if self.values.get(event_key) != owner:
                    return 0
                current = self.values.get(stored_job_key)
                if current is None:
                    return 0
                if isinstance(current, bytes):
                    current = current.decode()
                if json.loads(current)["status"] in {
                    "completed",
                    "failed",
                    "cancelled",
                    "incomplete",
                    "expired",
                }:
                    self.values[event_key] = processed
                    self.expirations[event_key] = int(processed_ttl)
                    return 2
                self.values[stored_job_key] = serialized_job
                self.expirations[stored_job_key] = int(job_ttl)
                self.values[event_key] = processed
                self.expirations[event_key] = int(processed_ttl)
                return 1
            raise AssertionError("unexpected Redis script")

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


@pytest.fixture
def captured_events():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(json.loads(JsonFormatter().format(record)))

    logger = logging.getLogger("app")
    handler = Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
