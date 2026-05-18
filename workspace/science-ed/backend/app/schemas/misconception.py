"""Schemas for misconception detection — identifying science misconceptions
from student event patterns."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MisconceptionDetected(BaseModel):
    """A detected misconception with confidence and supporting evidence."""

    concept: str
    """Educational concept label (e.g., 'velocity-vs-acceleration')."""

    ngss_id: str
    """The NGSS standard this misconception relates to."""

    sim_slug: str
    """The simulation slug where evidence was found."""

    pattern_type: str
    """Type of pattern that triggered the detection:
    repeated_error, oscillating, rapid_guessing, sign_error."""

    confidence: float
    """Confidence score 0.0–1.0. Higher = more certain."""

    evidence_events: list[dict]
    """The event_value dicts that constitute evidence for this misconception."""

    count: int
    """Number of evidence events."""

    description: str
    """Human-readable description of the misconception."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "concept": "velocity-vs-acceleration",
                "ngss_id": "HS-PS2-1",
                "sim_slug": "projectile-motion-simulation",
                "pattern_type": "repeated_error",
                "confidence": 0.85,
                "evidence_events": [
                    {
                        "event_type": "sim_interaction",
                        "event_name": "answer_submit",
                        "value": {"question": "initial_velocity_y", "answer": 0},
                        "correct_value": 9.8,
                    }
                ],
                "count": 5,
                "description": "Student appears to confuse velocity with acceleration — "
                "consistently setting initial vertical velocity to 0 instead of 9.8 m/s",
            }
        }
    )


class MisconceptionListResponse(BaseModel):
    """Response containing all detected misconceptions for a student."""

    student_id: str
    misconceptions: list[MisconceptionDetected]
    total_count: int
    analyzed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
