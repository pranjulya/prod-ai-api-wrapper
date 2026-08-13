import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ClaimStatus(StrEnum):
    CLAIMED = "claimed"
    EXISTING = "existing"


@dataclass(frozen=True)
class IdempotencyRecord:
    request_hash: str
    state: str
    correlation_id: str | None = None
    response: dict[str, Any] | None = None


@dataclass(frozen=True)
class ClaimResult:
    status: ClaimStatus
    record: IdempotencyRecord | None = None


def request_hash(payload: Any, effective_model: str) -> str:
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    encoded = json.dumps({"model": effective_model, "request": value}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def redis_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"wrapper:idempotency:{digest}"


def _decode(value: str | bytes | None) -> IdempotencyRecord | None:
    if value is None:
        return None
    data = json.loads(value)
    return IdempotencyRecord(
        request_hash=data["request_hash"],
        state=data["state"],
        correlation_id=data.get("correlation_id"),
        response=data.get("response"),
    )


def _encode(record: IdempotencyRecord) -> str:
    return json.dumps({"request_hash": record.request_hash, "state": record.state, "correlation_id": record.correlation_id, "response": record.response}, separators=(",", ":"), ensure_ascii=True)


async def get(redis, key: str) -> IdempotencyRecord | None:
    return _decode(await redis.get(key))


async def claim(redis, *, key: str, request_hash_value: str, correlation_id: str, ttl_seconds: int) -> ClaimResult:
    record = IdempotencyRecord(request_hash_value, "in_progress", correlation_id)
    claimed = await redis.set(key, _encode(record), nx=True, ex=ttl_seconds)
    if claimed:
        return ClaimResult(ClaimStatus.CLAIMED, record)
    return ClaimResult(ClaimStatus.EXISTING, await get(redis, key))


async def store(redis, *, key: str, request_hash_value: str, response: Any, ttl_seconds: int) -> None:
    value = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
    await redis.set(key, _encode(IdempotencyRecord(request_hash_value, "completed", response=value)), ex=ttl_seconds)


async def delete(redis, key: str) -> None:
    await redis.delete(key)
