import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import error_response
from app.logging import log_event


logger = logging.getLogger(__name__)


EXEMPT_PATHS = {"/webhooks/openai", "/health/live", "/health/ready"}


def _normalized_path(path: str) -> str:
    return path.rstrip("/") or "/"


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if _normalized_path(request.url.path) in EXEMPT_PATHS:
            return await call_next(request)
        scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
        if scheme != "Bearer" or not credential or not credential.isascii() or not hmac.compare_digest(
            credential, request.app.state.settings.wrapper_api_key
        ):
            log_event(
                logger,
                logging.WARNING,
                "authentication_failed",
                method=request.method,
                route=request.url.path,
                status_code=401,
                error_category="authentication",
            )
            return error_response(
                401,
                "authentication_failed",
                "Authentication required.",
                request.state.correlation_id,
            )
        return await call_next(request)
