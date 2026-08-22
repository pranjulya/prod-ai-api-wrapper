import asyncio

from app.services.idempotency import ClaimStatus, claim, delete, get, redis_key, request_hash, store


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.calls = []

    async def set(self, key, value, nx=False, ex=None):
        self.calls.append((key, value, nx, ex))
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


def test_hash_and_key_are_deterministic_and_namespaced():
    assert request_hash({"input": "hi", "metadata": {"a": "b"}}, "gpt-5-mini") == request_hash({"metadata": {"a": "b"}, "input": "hi"}, "gpt-5-mini")
    assert redis_key("client-key").startswith("wrapper:idempotency:")
    assert "client-key" not in redis_key("client-key")


def test_claim_get_store_delete():
    asyncio.run(_claim_get_store_delete())


async def _claim_get_store_delete():
    redis = FakeRedis()
    key = redis_key("key")
    first = await claim(redis, key=key, request_hash_value="hash", correlation_id="corr", ttl_seconds=60)
    assert first.status is ClaimStatus.CLAIMED
    second = await claim(redis, key=key, request_hash_value="hash", correlation_id="other", ttl_seconds=60)
    assert second.status is ClaimStatus.EXISTING
    assert second.record.request_hash == "hash"
    await store(redis, key=key, request_hash_value="hash", response={"id": "r"}, ttl_seconds=120)
    record = await get(redis, key)
    assert record.state == "completed" and record.response == {"id": "r"}
    assert redis.calls[-1][3] == 120
    await delete(redis, key)
    assert await get(redis, key) is None


def test_claim_records_the_provided_ttl():
    asyncio.run(_claim_records_the_provided_ttl())


async def _claim_records_the_provided_ttl():
    redis = FakeRedis()
    key = redis_key("ttl-key")
    await claim(redis, key=key, request_hash_value="hash", correlation_id="corr", ttl_seconds=100)
    assert redis.calls[0][2] is True
    assert redis.calls[0][3] == 100
