from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing import Optional


class ClassSummary(BaseModel):
    """Summary stats for one class in a teacher's roster."""

    id: UUID
    name: str
    student_count: int
    active_today: int
    average_mastery: float
    class_code: str
    struggling_students: int

    model_config = ConfigDict(from_attributes=True)


class ClassesResponse(BaseModel):
    """List of classes belonging to a teacher."""

    classes: list[ClassSummary]

    model_config = ConfigDict(from_attributes=True)


class StudentSummary(BaseModel):
    """Per-student analytics within a class overview."""

    id: UUID
    name: str
    sims_completed: int
    overall_mastery: float
    struggling_topics: list[str]
    last_active: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ClassOverviewResponse(BaseModel):
    """Class-wide analytics with per-student breakdowns."""

    class_id: UUID
    class_name: str
    students: list[StudentSummary]
    class_average_mastery: float
    most_struggled_topics: list[str]
    total_time_hours: float

    model_config = ConfigDict(from_attributes=True)


class AlertItem(BaseModel):
    """An AI-generated alert or insight item for the teacher."""

    type: str  # 'struggling_student', 'class_trend', 'milestone'
    student_name: Optional[str] = None
    topic: Optional[str] = None
    finding: Optional[str] = None
    action: str

    model_config = ConfigDict(from_attributes=True)


class InsightsResponse(BaseModel):
    """AI-generated insights and alerts for teacher attention."""

    alerts: list[AlertItem]

    model_config = ConfigDict(from_attributes=True)


class AssignRequest(BaseModel):
    """Assign a sim to a class."""

    teacher_id: UUID
    class_id: UUID
    sim_slug: str
    due_date: Optional[datetime] = None
    required: bool = True


class AssignResponse(BaseModel):
    """Confirmation of assignment creation."""

    status: str = "ok"
    assignment_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ReplayEventItem(BaseModel):
    """A single event in the session replay timeline."""

    event_id: int
    timestamp: datetime
    event_type: str
    event_name: Optional[str] = None
    event_data: Optional[dict] = None
    extra_data: dict = {}

    model_config = ConfigDict(from_attributes=True)


class SessionMetadata(BaseModel):
    """Metadata about the replayed session."""

    session_id: str
    student_name: Optional[str] = None
    sim_slug: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    is_completed: bool = False

    model_config = ConfigDict(from_attributes=True)


class ReplayResponse(BaseModel):
    """Full session replay — ordered event timeline + session metadata."""

    session: SessionMetadata
    events: list[ReplayEventItem]

    model_config = ConfigDict(from_attributes=True)


# ── Feedback Review ──────────────────────────────────────────────────


class FeedbackReviewItem(BaseModel):
    """One AI-generated feedback entry visible to a teacher for review."""

    feedback_id: str
    student_name: Optional[str] = None
    sim_slug: Optional[str] = None
    original_prompt: Optional[str] = None
    ai_response: str
    hint_level: Optional[str] = None
    feedback_type: str
    timestamp: datetime
    is_flagged: bool = False
    flag_reason: Optional[str] = None
    flag_note: Optional[str] = None
    corrected_text: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FeedbackReviewListResponse(BaseModel):
    """Paginated list of AI feedback items for teacher review."""

    feedback: list[FeedbackReviewItem]
    total: int

    model_config = ConfigDict(from_attributes=True)


class FlagRequest(BaseModel):
    """Request body for flagging a feedback item."""

    reason: str  # 'incorrect', 'misleading', 'inappropriate', 'other'
    note: Optional[str] = None


class FlagResponse(BaseModel):
    """Confirmation that feedback was flagged."""

    status: str = "ok"
    feedback_id: str

    model_config = ConfigDict(from_attributes=True)


class CorrectRequest(BaseModel):
    """Request body for correcting a feedback item."""

    corrected_text: str


class CorrectResponse(BaseModel):
    """Confirmation that feedback correction was recorded."""

    status: str = "ok"
    feedback_id: str

    model_config = ConfigDict(from_attributes=True)


# ── Mastery Heatmap ──────────────────────────────────────────────────


class MasteryHeatmapSkill(BaseModel):
    """One skill column in the mastery heatmap grid."""

    skill_id: str
    display_name: Optional[str] = None
    category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MasteryHeatmapCell(BaseModel):
    """Single cell in the heatmap — a student's state for one skill."""

    mastery_probability: float
    mastery_level: str  # struggling | introductory | developing | proficient | mastered
    total_attempts: int = 0
    correct_attempts: int = 0
    last_practiced: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MasteryHeatmapStudent(BaseModel):
    """One student row in the heatmap grid."""

    student_id: str
    student_name: str
    overall_mastery: float
    cells: dict[str, MasteryHeatmapCell]  # skill_id → cell

    model_config = ConfigDict(from_attributes=True)


class MasteryHeatmapResponse(BaseModel):
    """Full heatmap dataset — all students × all skills."""

    skills: list[MasteryHeatmapSkill]
    students: list[MasteryHeatmapStudent]
    class_average_mastery: float
    student_count: int
    skill_count: int

    model_config = ConfigDict(from_attributes=True)
