"""Parent-facing data access schemas (FERPA §99.10 / COPPA §312.6 B2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ── Request Schemas ──────────────────────────────────────────────────────


class ParentVerifyRequest(BaseModel):
    """Identity verification for parent data access.

    The parent provides a verification token (either the child's
    parental_consent_id for under-13 students, or a generated
    parent_verification_token for any student).
    """

    token: str


class ParentVerifyQuery(BaseModel):
    """Query parameter model for token verification.

    Allows passing the token as a query parameter instead of request body
    for GET-based data access.
    """

    token: str


class GenerateParentTokenRequest(BaseModel):
    """Student generates a parent verification token."""

    pass


# ── Response Schemas ─────────────────────────────────────────────────────


class ParentSessionItem(BaseModel):
    """Simplified session record for parent view."""

    id: str
    sim_id: str | None = None
    sim_slug: str | None = None
    sim_title: str | None = None
    task_slug: str | None = None
    page_type: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    is_completed: bool = False

    model_config = ConfigDict(from_attributes=True)


class ParentEventItem(BaseModel):
    """Simplified event record for parent view."""

    id: int
    event_type: str
    event_name: str | None = None
    event_value: dict[str, Any] | None = None
    client_ts: datetime | None = None
    server_ts: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ParentFeedbackItem(BaseModel):
    """Simplified feedback record for parent view."""

    id: str
    feedback_type: str
    feedback_text: str
    source: str | None = None
    was_helpful: bool | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ParentSkillStateItem(BaseModel):
    """Simplified skill state record for parent view."""

    skill_id: str
    probability: float
    total_attempts: int
    correct_attempts: int
    last_practiced: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ParentEnrollmentItem(BaseModel):
    """Simplified enrollment for parent view."""

    class_id: str
    class_name: str | None = None
    enrolled_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ParentChildProfile(BaseModel):
    """Child's profile information shared with parent."""

    id: str
    email: str | None = None
    username: str | None = None
    display_name: str | None = None
    role: str
    account_status: str = "active"
    created_at: datetime | None = None
    last_active_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ParentDataResponse(BaseModel):
    """Complete student records response for parent/guardian.

    Returned by GET /api/v1/parent/{child_id}/data.
    Provides a comprehensive view of the child's educational records
    including profile, sessions, events, feedback, skill states, and
    class enrollments.
    """

    profile: ParentChildProfile
    sessions: list[ParentSessionItem] = []
    events: list[ParentEventItem] = []
    feedback: list[ParentFeedbackItem] = []
    skill_states: list[ParentSkillStateItem] = []
    enrollments: list[ParentEnrollmentItem] = []
    total_sessions: int = 0
    total_events: int = 0
    total_feedback: int = 0
    total_skills: int = 0

    model_config = ConfigDict(from_attributes=True)


class GenerateParentTokenResponse(BaseModel):
    """Response after generating a parent verification token."""

    parent_verification_token: str
    message: str = (
        "Share this token with your parent or guardian so they can "
        "access your educational records. Keep it private — anyone "
        "with this token can view your data."
    )

    model_config = ConfigDict(from_attributes=True)
