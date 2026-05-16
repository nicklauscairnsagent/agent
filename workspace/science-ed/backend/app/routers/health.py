from fastapi import APIRouter

router = APIRouter(prefix="", tags=["health"])
v1_router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
@v1_router.get("/health")
async def health_check():
    return {"status": "ok", "service": "science-ed-backend"}
