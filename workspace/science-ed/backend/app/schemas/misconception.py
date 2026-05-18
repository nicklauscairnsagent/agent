"""Schemas for misconception detection — identifying science misconceptions
from student event patterns.

Includes both pattern-based detection schemas and AI/LLM-enhanced analysis.
"""

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


class AIMisconceptionResult(BaseModel):
    """A single AI-detected misconception with teaching context."""

    concept: str
    """Short educational concept label (e.g., 'velocity-vs-acceleration')."""

    specific_misconception: str
    """Natural-language description of the specific misconception detected."""

    confidence: float
    """Confidence score 0.0–1.0. Only results > 0.6 are surfaced to teachers."""

    explanation: str
    """Detailed explanation of why this behavior indicates the misconception."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "concept": "velocity-vs-acceleration",
                "specific_misconception": "Student confuses velocity with acceleration — "
                "they set initial vertical velocity to 9.8 m/s as if it were gravitational acceleration",
                "confidence": 0.87,
                "explanation": "The student consistently enters the gravitational acceleration "
                "value (9.8 m/s) as the initial velocity, suggesting they do not distinguish "
                "between initial velocity (a choice) and gravitational acceleration (a constant).",
            }
        }
    )


class AIMisconceptionAnalysis(BaseModel):
    """Full AI analysis output attached to a misconception query response."""

    detected_misconceptions: list[AIMisconceptionResult] = []
    """List of AI-detected misconceptions (may be empty)."""

    teaching_guidance: str | None = None
    """1-2 sentences on how to address this misconception."""

    recommended_remediation: str | None = None
    """Suggestion for which sim or activity to assign next."""

    ai_used: bool = True
    """Whether AI analysis was actually performed (True) or fell back (False)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detected_misconceptions": [
                    {
                        "concept": "velocity-vs-acceleration",
                        "specific_misconception": "Student confuses velocity with acceleration",
                        "confidence": 0.87,
                        "explanation": "Consistently enters 9.8 m/s as initial velocity.",
                    }
                ],
                "teaching_guidance": "Review the difference between initial velocity (a choice) "
                "and gravitational acceleration (a constant 9.8 m/s on Earth). "
                "Use the simulation's velocity vectors overlay to illustrate.",
                "recommended_remediation": "Assign the 'Forces and Motion' simulation to "
                "reinforce the distinction between velocity and acceleration.",
            }
        }
    )


class MisconceptionListResponse(BaseModel):
    """Response containing all detected misconceptions for a student."""

    student_id: str
    misconceptions: list[MisconceptionDetected]
    total_count: int
    analyzed_at: datetime | None = None
    ai_analysis: AIMisconceptionAnalysis | None = None
    """Optional AI-enhanced analysis alongside pattern-based results."""

    model_config = ConfigDict(from_attributes=True)
