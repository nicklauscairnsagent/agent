"""
Health check endpoints — verify the API and database are operational.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import HealthResponse
from app.state import get_last_monitoring_tick

router = APIRouter(prefix="", tags=["health"])
v1_router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
@v1_router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Return service health status.

    Public endpoint — no authentication required.
    Reports API version, database connectivity, and the last monitoring
    background job tick. Still returns HTTP 200 when the database is
    unreachable (transient failures should not trigger alarms).
    """
    database_status: str = "connected"
    try:
        await db.execute(sql_text("SELECT 1"))
    except Exception:  # noqa: BLE001
        database_status = "disconnected"

    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        database=database_status,
        last_monitoring_tick=get_last_monitoring_tick(),
    )
