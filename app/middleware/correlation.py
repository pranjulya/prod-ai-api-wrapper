import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import error_response


logger = logging.getLogger(__name__)
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID")
        correlation_id = supplied_id if supplied_id and CORRELATION_ID_PATTERN.fullmatch(supplied_id) else str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        if supplied_id is not None and not CORRELATION_ID_PATTERN.fullmatch(supplied_id):
            response = error_response(400, "invalid_correlation_id", "Invalid correlation ID.", correlation_id)
        else:
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error("request failed correlation_id=%s exception_type=%s", correlation_id, type(exc).__name__)
                response = error_response(500, "internal_error", "Internal server error.", correlation_id)
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info("request completed correlation_id=%s status_code=%s", correlation_id, response.status_code)
        return response
