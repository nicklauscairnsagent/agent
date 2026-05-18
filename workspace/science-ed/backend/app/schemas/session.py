from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing import Optional


class SessionStartRequest(BaseModel):
    """Start a new learning session (called when a sim or task page loads)."""

    sim_slug: str
    student_id: Optional[UUID] = None
    task_slug: Optional[str] = None
    page_type: str = "sim"  # 'sim', 'task', 'prescreener', 'screener'
    anon_token: Optional[str] = None
    device_info: Optional[dict] = None
    referrer: Optional[str] = None


class SessionStartResponse(BaseModel):
    """Response returned after a session is created."""

    session_id: UUID
    student_token: str
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionEndRequest(BaseModel):
    """End a learning session (sim_complete or tab close)."""

    session_id: UUID
    duration_seconds: Optional[int] = None
    completed: bool = False


class SessionEndResponse(BaseModel):
    """Confirmation that a session was ended."""

    status: str = "ok"

    model_config = ConfigDict(from_attributes=True)
