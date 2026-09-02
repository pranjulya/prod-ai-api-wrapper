import logging
import re
import time
import uuid

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import error_response, http_exception_handler
from app.logging import bind_correlation_id, log_event, reset_correlation_id

logger = logging.getLogger(__name__)
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _route(request) -> str:
    fastapi_scope = request.scope.get("fastapi")
    if isinstance(fastapi_scope, dict):
        context = fastapi_scope.get("effective_route_context")
        for field in ("path_format", "path"):
            value = context.get(field) if isinstance(context, dict) else getattr(context, field, None)
            if isinstance(value, str) and value:
                return value
    route = request.scope.get("route")
    for field in ("path_format", "path"):
        value = getattr(route, field, None)
        if isinstance(value, str) and value:
            return value
    return request.url.path


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID")
        correlation_id = supplied_id if supplied_id and CORRELATION_ID_PATTERN.fullmatch(supplied_id) else str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        token = bind_correlation_id(correlation_id)
        started_at = time.perf_counter()
        log_event(logger, logging.INFO, "request_started", method=request.method)
        try:
            if supplied_id is not None and not CORRELATION_ID_PATTERN.fullmatch(supplied_id):
                request.state.error_category = "validation"
                response = error_response(400, "invalid_correlation_id", "Invalid correlation ID.", correlation_id)
            else:
                try:
                    response = await call_next(request)
                except StarletteHTTPException as exc:
                    response = await http_exception_handler(request, exc)
                except Exception:
                    request.state.error_category = "internal"
                    log_event(
                        logger,
                        logging.ERROR,
                        "request_failed",
                        method=request.method,
                        route=_route(request),
                        status_code=500,
                        error_category="internal",
                    )
                    response = error_response(500, "internal_error", "Internal server error.", correlation_id)
            response.headers["X-Correlation-ID"] = correlation_id
            log_event(
                logger,
                logging.INFO,
                "request_completed",
                method=request.method,
                route=_route(request),
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                openai_request_id=getattr(request.state, "openai_request_id", None),
                error_category=getattr(request.state, "error_category", None),
            )
            return response
        finally:
            reset_correlation_id(token)
