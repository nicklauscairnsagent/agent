from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing import Optional


class StudentProgressResponse(BaseModel):
    """Overall progress across all sims for a student."""

    student_id: UUID
    total_sims_started: int
    total_sims_completed: int
    total_time_spent_minutes: int
    mastery_by_ngss: dict  # {skill_id: {"probability": float, "sims_practiced": int}}
    recent_sims: list[dict]  # [{"slug": str, "completed": bool, "score": float}]
    recommended_next: list[str]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "student_id": "660e8400-e29b-41d4-a716-446655440001",
                "total_sims_started": 12,
                "total_sims_completed": 8,
                "total_time_spent_minutes": 145,
                "mastery_by_ngss": {
                    "HS-PS1-1": {"probability": 0.72, "sims_practiced": 3},
                    "HS-PS1-4": {"probability": 0.45, "sims_practiced": 2},
                    "HS-LS1-1": {"probability": 0.88, "sims_practiced": 5},
                },
                "recent_sims": [
                    {"slug": "ph-scale", "completed": True, "score": 0.85},
                    {"slug": "dna-replication", "completed": False, "score": 0.0},
                ],
                "recommended_next": ["natural-selection", "enzyme-kinetics"],
            },
        }
    )


class SkillStateResponse(BaseModel):
    """BKT (Bayesian Knowledge Tracing) state for a single skill."""

    student_id: UUID
    skill_id: str
    know_probability: float
    learning_rate: float
    total_attempts: int
    correct_attempts: int
    streak: int
    last_practiced: Optional[datetime] = None
    sims_practiced: list[dict]  # [{"slug": str, "score": float}]

    model_config = ConfigDict(from_attributes=True)


class ClaimRequest(BaseModel):
    """Claim anonymous session data to an existing student account."""

    anon_token: str
    student_id: UUID


class ClaimResponse(BaseModel):
    """Confirmation of session merge after claiming."""

    status: str = "ok"
    sessions_merged: int = 0

    model_config = ConfigDict(from_attributes=True)


class DeletionRequestCreate(BaseModel):
    """Request body for creating a deletion request."""

    reason: Optional[str] = None


class DeletionRequestResponse(BaseModel):
    """Response after creating a deletion request."""

    id: str
    user_id: str
    status: str
    reason: Optional[str] = None
    created_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ConsentRequest(BaseModel):
    """Update consent tracking for FERPA/COPPA compliance (Finding B4)."""

    consent_given: bool
    consent_type: Optional[str] = None
    consent_scope: Optional[list[str]] = None  # e.g. ["tracking", "feedback", "export"]


class ConsentResponse(BaseModel):
    """Current consent state for a user."""

    consent_given: bool = False
    consent_date: Optional[datetime] = None
    consent_type: Optional[str] = None
    consent_scope: Optional[list[str]] = None
    consent_withdrawn_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ── Self-Service Data Export (FERPA/COPPA B6) ───────────────────────


class StudentProfileData(BaseModel):
    """Student profile information for self-service data export."""

    id: str
    email: str | None = None
    username: str | None = None
    display_name: str | None = None
    role: str = "student"
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    account_status: str = "active"
    consent_given: bool = False
    consent_type: str | None = None
    consent_date: datetime | None = None
    consent_withdrawn_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentSessionData(BaseModel):
    """Session data for self-service data export."""

    id: str
    sim_id: str | None = None
    page_type: str = "sim"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    is_completed: bool = False

    model_config = ConfigDict(from_attributes=True)


class StudentEventData(BaseModel):
    """Event data for self-service data export."""

    id: int
    session_id: str
    event_type: str
    event_name: str | None = None
    event_value: dict | None = None
    client_ts: datetime | None = None
    server_ts: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentFeedbackData(BaseModel):
    """Feedback data for self-service data export."""

    id: str
    session_id: str
    sim_id: str | None = None
    feedback_type: str
    feedback_text: str
    source: str = "llm"
    was_helpful: bool | None = None
    was_dismissed: bool | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentSkillStateData(BaseModel):
    """Skill state data for self-service data export."""

    id: str
    skill_id: str
    probability: float = 0.0
    total_attempts: int = 0
    correct_attempts: int = 0
    last_practiced: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentEnrollmentData(BaseModel):
    """Enrollment data for self-service data export."""

    id: str
    class_id: str
    enrolled_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StudentDataResponse(BaseModel):
    """Complete self-service data response (JSON).

    Contains all data categories for a single student.
    Used by GET /api/v1/student/me/data.
    """

    profile: StudentProfileData
    sessions: list[StudentSessionData] = []
    events: list[StudentEventData] = []
    feedback: list[StudentFeedbackData] = []
    skill_states: list[StudentSkillStateData] = []
    enrollments: list[StudentEnrollmentData] = []
    exported_at: str

    model_config = ConfigDict(from_attributes=True)


class StudentExportRow(BaseModel):
    """A single row in the CSV data export.

    Each row includes a 'section' field indicating which data category
    it belongs to, allowing multi-table data to be represented in a
    single flat CSV file.
    """

    section: str
    field1: str = ""
    field2: str = ""
    field3: str = ""
    field4: str = ""
    field5: str = ""
    field6: str = ""
    field7: str = ""
    field8: str = ""
    exported_at: str = ""
