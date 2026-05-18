from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AdminStatsResponse(BaseModel):
    """Platform-wide statistics for admin dashboard."""

    total_students: int
    total_teachers: int
    total_sessions: int
    total_events: int
    active_today: int
    events_per_minute_avg: float
    llm_calls_today: int
    llm_cost_today_usd: float

    model_config = ConfigDict(from_attributes=True)


class SimsRefreshResponse(BaseModel):
    """Result of refreshing the sim catalog from GitHub Pages."""

    sims_found: int
    sims_added: int
    sims_updated: int
    sims_removed: int

    model_config = ConfigDict(from_attributes=True)


# ── Data Export Schemas ───────────────────────────────────────────────


class ExportStudentRecord(BaseModel):
    """A single student record for CSV export."""

    user_id: str
    email: str | None = None
    username: str | None = None
    display_name: str | None = None
    role: str
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    total_sessions: int = 0
    total_events: int = 0
    sims_completed: int = 0
    avg_session_duration_seconds: float | None = None
    total_feedback_received: int = 0
    skill_count: int = 0
    avg_mastery: float | None = None

    model_config = ConfigDict(from_attributes=True)


class ExportClassRecord(BaseModel):
    """A single class record for CSV export."""

    class_id: str
    class_name: str
    class_code: str
    subject: str | None = None
    grade_level: str | None = None
    school_name: str | None = None
    teacher_name: str | None = None
    teacher_email: str | None = None
    student_count: int = 0
    assignment_count: int = 0
    assignments_completed: int = 0
    created_at: datetime | None = None
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


# ── Usage Report Schemas ──────────────────────────────────────────────


class DailyActiveUser(BaseModel):
    """Daily active user count for a date."""

    date: str
    count: int


class TopSim(BaseModel):
    """Most-used sim data."""

    sim_slug: str
    sim_title: str
    session_count: int


class UsageReportResponse(BaseModel):
    """Aggregated usage statistics."""

    total_students: int
    total_teachers: int
    total_classes: int
    total_sims: int
    total_sessions: int
    total_events: int
    total_assignments: int
    total_feedback_calls: int
    avg_session_duration_seconds: float | None = None
    avg_sessions_per_student: float | None = None
    daily_active_users: list[DailyActiveUser] = []
    top_sims: list[TopSim] = []
    date_range_from: str | None = None
    date_range_to: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Privacy Audit Schemas ─────────────────────────────────────────────


class PrivacyAuditEntry(BaseModel):
    """A single privacy audit log entry."""

    id: str
    timestamp: str
    actor_type: str  # teacher, admin, system
    actor_id: str
    actor_name: str | None = None
    action: str
    target_type: str  # student, class, feedback
    target_id: str | None = None
    target_name: str | None = None
    details: dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class PrivacyAuditResponse(BaseModel):
    """Privacy audit log response."""

    entries: list[PrivacyAuditEntry] = []
    total: int = 0
    date_range_from: str | None = None
    date_range_to: str | None = None

    model_config = ConfigDict(from_attributes=True)
