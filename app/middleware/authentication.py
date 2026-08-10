import hmac

from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import error_response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/webhooks/openai":
            return await call_next(request)
        scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
        if scheme != "Bearer" or not credential or not hmac.compare_digest(
            credential, request.app.state.settings.wrapper_api_key
        ):
            return error_response(
                401,
                "authentication_failed",
                "Authentication required.",
                request.state.correlation_id,
            )
        return await call_next(request)
