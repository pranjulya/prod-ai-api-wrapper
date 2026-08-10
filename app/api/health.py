from fastapi import APIRouter, HTTPException, Request
from redis.exceptions import RedisError

router = APIRouter()


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    try:
        await request.app.state.redis.ping()
    except RedisError:
        raise HTTPException(status_code=503, detail="Redis unavailable") from None
    return {"status": "ready"}
