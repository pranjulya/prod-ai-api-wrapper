from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_response(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
    )


async def http_exception_handler(request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {404: "not_found", 405: "method_not_allowed"}
    return error_response(exc.status_code, codes.get(exc.status_code, "http_error"), "Request failed.", request.state.correlation_id)


async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    return error_response(422, "validation_error", "Request validation failed.", request.state.correlation_id)
