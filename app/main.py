from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.clients.redis_client import create_redis
from app.config import load_settings
from app.errors import http_exception_handler, validation_exception_handler
from app.middleware.authentication import AuthenticationMiddleware
from app.middleware.correlation import CorrelationMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    app.state.redis = create_redis(app.state.settings.redis_url)
    try:
        yield
    finally:
        await app.state.redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Production API Wrapper", lifespan=lifespan)
    app.add_middleware(AuthenticationMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(health_router, prefix="/health", tags=["health"])
    return app


app = create_app()
