"""Alert schemas for teacher-facing alert dashboard."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ── Request / Response ────────────────────────────────────────────────


class AlertItemFull(BaseModel):
    """Full alert info returned by the alert dashboard API.

    Extends the basic ``AlertItem`` with severity, lifecycle status,
    recommended remediation, and timestamps.
    """

    id: str
    teacher_id: str
    class_id: Optional[str] = None
    student_id: Optional[str] = None
    student_name: Optional[str] = None
    class_name: Optional[str] = None

    severity: str  # 'info', 'warning', 'critical'
    alert_type: str
    title: str
    description: str
    recommendation: Optional[str] = None

    suggested_sim_slug: Optional[str] = None
    suggested_sim_title: Optional[str] = None

    acknowledged: bool = False
    resolved: bool = False
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertListResponse(BaseModel):
    """Paginated list of alerts."""

    alerts: list[AlertItemFull]
    total: int
    offset: int
    limit: int


class AlertAcknowledgeRequest(BaseModel):
    """Mark an alert as acknowledged."""

    acknowledged: bool = True


class AlertResolveRequest(BaseModel):
    """Mark an alert as resolved."""

    resolved: bool = True


class AlertAcknowledgeResponse(BaseModel):
    """Confirmation of alert status change."""

    status: str = "ok"
    alert_id: str
    acknowledged: bool
    resolved: bool


class WebSocketAlertPayload(BaseModel):
    """Payload sent via WebSocket when a new alert is generated."""

    type: str = "new_alert"
    alert: AlertItemFull


class AlertStatsResponse(BaseModel):
    """Summary counts for the alert badge."""

    total_active: int
    info_count: int
    warning_count: int
    critical_count: int
    unacknowledged_count: int
