from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import load_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Production API Wrapper", lifespan=lifespan)
    app.include_router(health_router, prefix="/health", tags=["health"])
    return app


app = create_app()
