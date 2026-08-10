import asyncio

import pytest

from app.services.rate_limit import check_rate_limit


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []
        redis.pipelines.append(self)

    def incr(self, key):
        self.commands.append(("incr", key))

    def expire(self, key, seconds, nx=False):
        self.commands.append(("expire", key, seconds, nx))

    async def execute(self):
        results = []
        for command in self.commands:
            if command[0] == "incr":
                self.redis.values[command[1]] = self.redis.values.get(command[1], 0) + 1
                results.append(self.redis.values[command[1]])
            else:
                _, key, _, nx = command
                results.append(not nx or key not in self.redis.expiries)
                if results[-1]:
                    self.redis.expiries.add(key)
        return results


class FakeRedis:
    def __init__(self, error=None):
        self.values = {}
        self.expiries = set()
        self.pipelines = []
        self.transactions = []
        self.error = error

    def pipeline(self, transaction=True):
        if self.error:
            raise self.error
        self.transactions.append(transaction)
        return FakePipeline(self)


def test_first_request_is_allowed():
    redis = FakeRedis()
    result = asyncio.run(check_rate_limit(redis, limit=2, window_seconds=60, now=120))
    assert result.allowed
    assert len(redis.pipelines) == 1
    assert redis.transactions == [True]
    assert redis.pipelines[0].commands == [
        ("incr", "wrapper:rate-limit:2"),
        ("expire", "wrapper:rate-limit:2", 60, True),
    ]


def test_request_at_limit_is_allowed():
    redis = FakeRedis()
    asyncio.run(check_rate_limit(redis, limit=2, window_seconds=60, now=120))
    result = asyncio.run(check_rate_limit(redis, limit=2, window_seconds=60, now=121))
    assert result.allowed


def test_rejects_after_limit_and_reports_retry_after():
    redis = FakeRedis()
    asyncio.run(check_rate_limit(redis, limit=2, window_seconds=60, now=120))
    asyncio.run(check_rate_limit(redis, limit=2, window_seconds=60, now=121))
    result = asyncio.run(check_rate_limit(redis, limit=2, window_seconds=60, now=122))
    assert not result.allowed
    assert result.retry_after == 58


def test_window_rollover_starts_new_counter():
    redis = FakeRedis()
    asyncio.run(check_rate_limit(redis, limit=1, window_seconds=60, now=119))
    result = asyncio.run(check_rate_limit(redis, limit=1, window_seconds=60, now=120))
    assert result.allowed


def test_redis_failure_propagates():
    error = RuntimeError("redis unavailable")
    with pytest.raises(RuntimeError, match="redis unavailable"):
        asyncio.run(check_rate_limit(FakeRedis(error), limit=1, window_seconds=60, now=120))
