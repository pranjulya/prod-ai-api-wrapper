from fastapi import APIRouter

router = APIRouter()


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}
