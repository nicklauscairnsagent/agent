"""Health check endpoints — verify the API is operational."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.schemas import HealthResponse

router = APIRouter(prefix="", tags=["health"])
v1_router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
@v1_router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return service health status.

    Verifies the API is running and accepting requests.
    Database connectivity is checked during startup (lifespan event).
    """
    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
    )
