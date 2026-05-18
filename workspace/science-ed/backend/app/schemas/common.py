from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict
from typing import Literal, Optional


class HealthResponse(BaseModel):
    """Health check endpoint response."""

    status: str
    version: str
    timestamp: datetime
    database: Literal["connected", "disconnected"] = "connected"
    last_monitoring_tick: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    detail: str
    error_code: Optional[str] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
