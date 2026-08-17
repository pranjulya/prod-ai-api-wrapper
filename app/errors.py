from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class UnsupportedModelError(StarletteHTTPException):
    def __init__(self):
        super().__init__(status_code=400)


class IdempotencyConflictError(StarletteHTTPException):
    def __init__(self, code: str):
        self.code = code
        super().__init__(status_code=409)


class JobNotFoundError(StarletteHTTPException):
    def __init__(self):
        super().__init__(status_code=404)


def error_response(status_code: int, code: str, message: str, correlation_id: str, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
        headers=headers,
    )


async def http_exception_handler(request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {
        404: "not_found",
        405: "method_not_allowed",
        429: "rate_limit_exceeded",
        503: "upstream_unavailable",
        504: "upstream_timeout",
    }
    if isinstance(exc, UnsupportedModelError):
        codes[400] = "unsupported_model"
    elif isinstance(exc, IdempotencyConflictError):
        codes[409] = exc.code
    elif isinstance(exc, JobNotFoundError):
        codes[404] = "job_not_found"
    return error_response(
        exc.status_code, codes.get(exc.status_code, "http_error"), "Request failed.", request.state.correlation_id, exc.headers
    )


async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    request.state.error_category = "validation"
    return error_response(422, "validation_error", "Request validation failed.", request.state.correlation_id)
