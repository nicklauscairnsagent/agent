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
from app.schemas import (
    MisconceptionDetected,
    MisconceptionListResponse,
    AIMisconceptionResult,
    AIMisconceptionAnalysis,
)
from app.schemas.alert import WebSocketAlertPayload, AlertItemFull
from app.services.misconception_detector import detect_misconceptions
from app.services.ai_misconception_analyzer import (
    analyze_misconceptions_ai,
    generate_ws_flags,
    AIAnalysisOutput,
)
from app.services.alert_service import broadcast_alert

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
    "Requires authentication. When use_ai=true (default for teachers), "
    "AI-powered analysis enriches the response with natural-language "
    "explanations and teaching guidance.",
)
async def get_misconceptions(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
    sim_slug: str | None = Query(
        None, description="Optional: filter misconceptions to a specific simulation slug"
    ),
    use_ai: bool = Query(
        True, description="Enable AI-powered misconception analysis with teaching guidance"
    ),
):
    """Get detected misconceptions for a student.

    Teachers can view their students' data. Students can only view
    their own misconceptions. When use_ai=true, the pattern-based
    results are enriched with LLM analysis for richer context.
    """
    # Authorization: student can only see their own; teacher can see any student
    if current_user.role == "student" and str(current_user.id) != student_id:
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

    # ── AI Enhanced Analysis (when requested and teacher) ──────────────
    ai_analysis_out: AIMisconceptionAnalysis | None = None

    if use_ai and sim_slug:
        # Fetch raw events for AI context
        raw_events = await _fetch_recent_events(
            student_id=student_id,
            db=db,
            sim_slug=sim_slug,
            limit=30,
        )

        # Run AI analysis
        pattern_dicts = [
            {
                "concept": d.concept,
                "ngss_id": d.ngss_id,
                "sim_slug": d.sim_slug,
                "pattern_type": d.pattern_type,
                "confidence": d.confidence,
                "count": d.count,
                "description": d.description,
            }
            for d in detected
        ]

        ai_result = await analyze_misconceptions_ai(
            sim_slug=sim_slug,
            raw_events=raw_events,
            pattern_results=pattern_dicts,
        )

        # Build the response schema
        ai_misconceptions = [
            AIMisconceptionResult(
                concept=m.concept,
                specific_misconception=m.specific_misconception,
                confidence=m.confidence,
                explanation=m.explanation,
            )
            for m in ai_result.detected_misconceptions
        ]

        ai_analysis_out = AIMisconceptionAnalysis(
            detected_misconceptions=ai_misconceptions,
            teaching_guidance=ai_result.teaching_guidance,
            recommended_remediation=ai_result.recommended_remediation,
            ai_used=ai_result.ai_used,
        )

        # ── Generate WebSocket flags for high-confidence AI findings ──
        teacher_id = str(current_user.id) if current_user.role == "teacher" else None
        ws_flags = generate_ws_flags(ai_result, student_id, sim_slug, teacher_id)

        for flag in ws_flags:
            try:
                metadata = flag.get("metadata", {})
                alert_data = {
                    "id": "",
                    "teacher_id": teacher_id or "",
                    "class_id": None,
                    "student_id": student_id,
                    "student_name": None,
                    "class_name": None,
                    "severity": "warning",
                    "alert_type": "ai_misconception",
                    "title": f"AI Detected Misconception: {metadata.get('concept', 'unknown')}",
                    "description": flag.get("message", ""),
                    "recommendation": metadata.get("teaching_guidance"),
                    "suggested_sim_slug": metadata.get("remediation_sim"),
                    "suggested_sim_title": None,
                    "acknowledged": False,
                    "resolved": False,
                    "acknowledged_at": None,
                    "resolved_at": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await broadcast_alert(teacher_id or "", alert_data)
            except Exception as exc:
                logger.warning("Failed to broadcast AI misconception flag: %s", exc)

    elif use_ai and sim_slug is None:
        # When no sim_slug is specified and use_ai=True, run AI on each
        # sim that has detected misconceptions
        unique_sims = {d.sim_slug for d in detected if d.sim_slug}
        all_ai_misconceptions: list[AIMisconceptionResult] = []
        combined_guidance: list[str] = []
        combined_remediation: list[str] = []

        for sim in unique_sims:
            raw_events = await _fetch_recent_events(
                student_id=student_id,
                db=db,
                sim_slug=sim,
                limit=30,
            )

            sim_patterns = [
                {
                    "concept": d.concept,
                    "ngss_id": d.ngss_id,
                    "sim_slug": d.sim_slug,
                    "pattern_type": d.pattern_type,
                    "confidence": d.confidence,
                    "count": d.count,
                    "description": d.description,
                }
                for d in detected
                if d.sim_slug == sim
            ]

            ai_result = await analyze_misconceptions_ai(
                sim_slug=sim,
                raw_events=raw_events,
                pattern_results=sim_patterns,
            )

            for m in ai_result.detected_misconceptions:
                all_ai_misconceptions.append(
                    AIMisconceptionResult(
                        concept=m.concept,
                        specific_misconception=m.specific_misconception,
                        confidence=m.confidence,
                        explanation=m.explanation,
                    )
                )
            if ai_result.teaching_guidance:
                combined_guidance.append(ai_result.teaching_guidance)
            if ai_result.recommended_remediation:
                combined_remediation.append(ai_result.recommended_remediation)

        if all_ai_misconceptions:
            ai_analysis_out = AIMisconceptionAnalysis(
                detected_misconceptions=all_ai_misconceptions,
                teaching_guidance=" ".join(combined_guidance) if combined_guidance else None,
                recommended_remediation=" ".join(combined_remediation) if combined_remediation else None,
                ai_used=True,
            )

    return MisconceptionListResponse(
        student_id=student_id,
        misconceptions=misconceptions_out,
        total_count=len(misconceptions_out),
        analyzed_at=datetime.now(timezone.utc),
        ai_analysis=ai_analysis_out,
    )


async def _fetch_recent_events(
    student_id: str,
    db,
    sim_slug: str,
    limit: int = 30,
) -> list[dict]:
    """Fetch recent interaction events for a student+sim combination.

    Reuses the same query logic as the pattern-based detector to get
    raw event data for the AI prompt.
    """
    from sqlalchemy import and_, select
    from app.models import Event, SessionModel

    stmt = (
        select(Event)
        .join(SessionModel, Event.session_id == SessionModel.id)
        .where(
            and_(
                Event.student_id == student_id,
                SessionModel.sim_id == sim_slug,
            )
        )
        .order_by(Event.server_ts.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    events = list(result.scalars().all())

    return [
        {
            "event_type": e.event_type,
            "event_name": e.event_name,
            "event_value": e.event_value or {},
            "client_ts": str(e.client_ts) if e.client_ts else None,
        }
        for e in events
    ]
