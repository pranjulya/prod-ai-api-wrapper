import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


async def check_rate_limit(redis, *, limit: int, window_seconds: int, now: float | None = None) -> RateLimitResult:
    now = time.time() if now is None else now
    window_index = int(now // window_seconds)
    key = f"wrapper:rate-limit:{window_index}"

    pipeline = redis.pipeline(transaction=True)
    pipeline.incr(key)
    pipeline.expire(key, window_seconds, nx=True)
    count, _ = await pipeline.execute()

    retry_after = max(1, ((window_index + 1) * window_seconds) - int(now))
    return RateLimitResult(allowed=count <= limit, retry_after=retry_after)
