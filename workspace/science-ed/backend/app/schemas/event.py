from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional

from app.schemas.extra_data import EventExtraData


class EventCreate(BaseModel):
    """A single interaction event from the tracking SDK."""

    event_type: str  # 'sim_load', 'slider_change', 'button_click', etc.
    event_name: Optional[str] = None
    event_value: Optional[dict[str, Any]] = None
    client_ts: datetime
    extra_data: EventExtraData = Field(
        default_factory=dict,
        description="Allowed keys: sim_state (simulation state snapshot)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "slider_change",
                "event_name": "pH_level_adjusted",
                "event_value": {"slider_id": "ph-control", "value": 7.2, "previous": 6.8},
                "client_ts": "2026-05-16T14:30:00Z",
                "extra_data": {"sim_state": {"temperature": 298, "pH": 7.0}},
            },
        }
    )


class EventBatchRequest(BaseModel):
    """Batch submission of interaction events."""

    session_id: UUID
    events: list[EventCreate]


class EventBatchResponse(BaseModel):
    """Confirmation of ingested events."""

    ingested: int
    session_id: UUID

    model_config = ConfigDict(from_attributes=True)
