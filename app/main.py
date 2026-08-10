from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import load_settings
from app.middleware.authentication import AuthenticationMiddleware
from app.middleware.correlation import CorrelationMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Production API Wrapper", lifespan=lifespan)
    app.add_middleware(AuthenticationMiddleware)
    app.add_middleware(CorrelationMiddleware)
    app.include_router(health_router, prefix="/health", tags=["health"])
    return app


app = create_app()
