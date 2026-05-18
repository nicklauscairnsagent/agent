from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing import Optional


class FeedbackRequest(BaseModel):
    """Request AI-generated feedback or a hint based on sim state."""

    session_id: UUID
    sim_slug: str
    student_id: Optional[UUID] = None
    sim_state: Optional[dict] = None
    student_action: Optional[dict] = None
    hint_level: Optional[int] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "sim_slug": "ph-scale",
                "student_id": "660e8400-e29b-41d4-a716-446655440001",
                "sim_state": {
                    "pH": 7.2,
                    "temperature": 25.0,
                    "beaker_contents": "water",
                    "drops_added": 3,
                },
                "student_action": {
                    "type": "slider_change",
                    "target": "acid-dropper",
                    "value": 5,
                },
                "hint_level": 1,
            },
        }
    )


class FeedbackResponse(BaseModel):
    """Feedback returned from the AI or rule-based engine."""

    feedback: str
    type: str  # 'hint', 'explanation', 'correction', 'encouragement'
    source: str = "llm"  # 'llm', 'rule_based', 'cached'
    cached: bool = False
    latency_ms: Optional[int] = None
    metadata: Optional[dict] = None
    """Additional context — e.g., detected misconceptions."""

    model_config = ConfigDict(from_attributes=True)


class FeedbackRateRequest(BaseModel):
    """Rate whether a feedback entry was helpful."""

    feedback_id: UUID
    helpful: bool
    student_comment: Optional[str] = None


class FeedbackRateResponse(BaseModel):
    """Confirmation that feedback rating was recorded."""

    status: str = "ok"

    model_config = ConfigDict(from_attributes=True)
