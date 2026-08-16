import logging

from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import error_response
from app.logging import log_event
from app.services.rate_limit import check_rate_limit


EXEMPT_PATHS = {"/health/live", "/health/ready", "/webhooks/openai"}
logger = logging.getLogger(__name__)


class RateLimitingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        try:
            result = await check_rate_limit(
                request.app.state.redis,
                limit=request.app.state.settings.rate_limit_requests,
                window_seconds=request.app.state.settings.rate_limit_window_seconds,
            )
        except RedisError:
            log_event(
                logger,
                logging.ERROR,
                "request_failed",
                method=request.method,
                route=request.url.path,
                status_code=503,
                error_category="redis",
            )
            raise HTTPException(status_code=503, detail="Redis unavailable") from None
        if not result.allowed:
            log_event(
                logger,
                logging.WARNING,
                "rate_limit_rejected",
                method=request.method,
                route=request.url.path,
                status_code=429,
                retry_after=result.retry_after,
                error_category="rate_limit",
            )
            return error_response(
                429,
                "rate_limit_exceeded",
                "Rate limit exceeded.",
                request.state.correlation_id,
                headers={"Retry-After": str(result.retry_after)},
            )
        return await call_next(request)
