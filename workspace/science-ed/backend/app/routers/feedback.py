"""Feedback router — AI-generated hints, explanations, ratings, and misconception detection."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import FeedbackRequest, FeedbackResponse, FeedbackRateRequest, FeedbackRateResponse
from app.schemas import MisconceptionDetected, MisconceptionListResponse
from app.services.misconception_detector import detect_misconceptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


@router.post(
    "/request",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request AI-generated feedback or hint",
    description="Request AI-generated feedback or a hint based on sim state. "
    "Requires authentication. The student_id in the request must match "
    "the authenticated user if the user is a student.",
)
async def feedback_request(
    body: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Request AI-generated feedback or a hint based on sim state.

    Requires authentication. The student_id in the request must match
    the authenticated user if the user is a student.

    When misconception patterns are detected for this student+sim combination,
    they are included in the response metadata for context-aware feedback.
    """
    # Verify student_id matches if provided and user is a student
    if (
        current_user.role == "student"
        and body.student_id is not None
        and str(body.student_id) != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only request feedback for yourself",
        )

    # Resolve student_id for misconception detection
    target_student_id = str(body.student_id or current_user.id)

    # Detect misconceptions from event patterns
    detected = await detect_misconceptions(
        student_id=target_student_id,
        db=db,
        sim_slug=body.sim_slug,
        max_events_per_sim=50,
    )

    misconceptions_out = []
    for d in detected:
        misconceptions_out.append(
            MisconceptionDetected(
                concept=d.concept,
                ngss_id=d.ngss_id,
                sim_slug=d.sim_slug,
                pattern_type=d.pattern_type,
                confidence=d.confidence,
                evidence_events=d.evidence_events,
                count=d.count,
                description=d.description,
            )
        )

    # Build feedback — when misconceptions are detected, include them as context
    if misconceptions_out:
        top_misconception = misconceptions_out[0]
        feedback_text = (
            f"I notice you may be struggling with the concept of "
            f"'{top_misconception.concept}' ({top_misconception.description}). "
            f"Let's work through this together. "
            f"Try thinking about what scientific principle applies here."
        )
    else:
        feedback_text = "Keep up the good work! Think about what happens to the variables you can control."

    return FeedbackResponse(
        feedback=feedback_text,
        type="hint",
        source="rule_based",
        cached=False,
        latency_ms=0,
        metadata={"detected_misconceptions": [m.model_dump() for m in misconceptions_out]}
        if misconceptions_out
        else None,
    )


@router.post(
    "/rate",
    response_model=FeedbackRateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Rate feedback helpfulness",
    description="Rate whether a feedback entry was helpful. "
    "Requires authentication. Records the feedback rating for analytics.",
)
async def feedback_rate(
    body: FeedbackRateRequest,
    _current_user: User = Depends(get_current_user),
):
    """Rate whether a feedback entry was helpful.

    Requires authentication. Records the feedback rating for analytics.
    """
    # TODO: implement real service logic
    return FeedbackRateResponse(status="ok")


@router.get(
    "/misconceptions/{student_id}",
    response_model=MisconceptionListResponse,
    summary="Get detected misconceptions for a student",
    description="Returns all detected misconceptions across simulations for a student. "
    "Teachers can view their students' misconceptions. "
    "Students can view their own misconceptions. "
    "Requires authentication.",
)
async def get_misconceptions(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
    sim_slug: str | None = Query(
        None, description="Optional: filter misconceptions to a specific simulation slug"
    ),
):
    """Get detected misconceptions for a student.

    Teachers can view their students' data. Students can only view
    their own misconceptions.
    """
    # Authorization: student can only see their own; teacher can see any student
    if current_user.role == "student" and current_user.id != student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own misconceptions",
        )

    # Teachers need to have the student in one of their classes
    if current_user.role == "teacher":
        from app.dependencies import OwnerOrTeacher

        # Verify teacher-student relationship
        await OwnerOrTeacher(id=student_id, current_user=current_user, db=db)

    detected = await detect_misconceptions(
        student_id=student_id,
        db=db,
        sim_slug=sim_slug,
        max_events_per_sim=50,
    )

    misconceptions_out = [
        MisconceptionDetected(
            concept=d.concept,
            ngss_id=d.ngss_id,
            sim_slug=d.sim_slug,
            pattern_type=d.pattern_type,
            confidence=d.confidence,
            evidence_events=d.evidence_events,
            count=d.count,
            description=d.description,
        )
        for d in detected
    ]

    return MisconceptionListResponse(
        student_id=student_id,
        misconceptions=misconceptions_out,
        total_count=len(misconceptions_out),
        analyzed_at=datetime.now(timezone.utc),
    )
