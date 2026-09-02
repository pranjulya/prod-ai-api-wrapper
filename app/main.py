import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.responses import router as responses_router
from app.api.webhooks import router as webhooks_router
from app.clients.openai_client import create_openai_client
from app.clients.redis_client import create_redis
from app.config import load_settings
from app.errors import http_exception_handler, validation_exception_handler
from app.logging import configure_logging
from app.middleware.authentication import AuthenticationMiddleware
from app.middleware.correlation import CorrelationMiddleware
from app.middleware.rate_limiting import RateLimitingMiddleware

configure_logging(os.getenv("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    configure_logging(app.state.settings.log_level)
    app.state.redis = create_redis(app.state.settings.redis_url)
    app.state.openai = create_openai_client(app.state.settings)
    try:
        yield
    finally:
        try:
            await app.state.openai.close()
        finally:
            await app.state.redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Production API Wrapper", lifespan=lifespan)
    app.add_middleware(RateLimitingMiddleware)
    app.add_middleware(AuthenticationMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(responses_router, prefix="/v1", tags=["responses"])
    app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
    return app


app = create_app()
