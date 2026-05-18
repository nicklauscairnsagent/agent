"""Teacher dashboard and classroom management router.

Provides 4 endpoints for teacher-facing analytics and classroom management:
- GET  /teacher/{id}/classes   → list classes with summary stats
- GET  /class/{id}/overview    → class-wide + per-student breakdown
- GET  /teacher/insights       → rule-based alerts & insights
- POST /teacher/assign         → assign a sim to a class
"""

from __future__ import annotations
from typing import Optional

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import TeacherOfClass, get_current_user, require_role, get_ws_user
from app.models import User, Enrollment, ClassModel, SessionModel
from app.schemas import (
    AssignRequest,
    AssignResponse,
    AlertItem,
    ClassOverviewResponse,
    ClassesResponse,
    ClassSummary,
    InsightsResponse,
    StudentSummary,
    ReplayResponse,
    SessionMetadata,
    ReplayEventItem,
    FeedbackReviewItem,
    FeedbackReviewListResponse,
    FlagRequest,
    FlagResponse,
    CorrectRequest,
    CorrectResponse,
)
from app.services.teacher_service import (
    assign_sim_to_class,
    get_class_overview,
    get_teacher_classes,
    get_teacher_insights,
    get_session_replay,
    list_teacher_feedback,
    flag_feedback,
    correct_feedback,
    get_mastery_heatmap,
)
from app.services.alert_service import (
    acknowledge_alert,
    broadcast_alert,
    generate_and_persist_alerts,
    get_alert_stats,
    list_active_alerts,
    list_alert_history,
    register_ws,
    resolve_alert,
    unregister_ws,
)
from app.schemas.alert import (
    AlertAcknowledgeRequest,
    AlertAcknowledgeResponse,
    AlertItemFull,
    AlertListResponse,
    AlertResolveRequest,
    AlertStatsResponse,
    WebSocketAlertPayload,
)
from app.schemas.teacher import (
    MasteryHeatmapResponse,
    MasteryHeatmapSkill,
    MasteryHeatmapStudent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["teacher"])


@router.get(
    "/teacher/{teacher_id}/classes",
    response_model=ClassesResponse,
)
async def teacher_classes(
    teacher_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClassesResponse:
    """List all classes belonging to a teacher with summary stats.

    Returns per-class metrics: student count, active today, average mastery,
    class code, number of struggling students.

    Requires authentication — the requesting user must be the teacher
    whose classes are being fetched, or an admin.
    """
    # Only the teacher themselves or admin can view their classes
    if current_user.id != teacher_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own classes",
        )

    logger.info("Fetching classes for teacher %s", teacher_id)

    class_list = await get_teacher_classes(db, teacher_id)

    return ClassesResponse(
        classes=[
            ClassSummary(**cls_data) for cls_data in class_list
        ],
    )


@router.get(
    "/class/{class_id}/overview",
    response_model=ClassOverviewResponse,
)
async def class_overview(
    class_id: str,
    _auth: User = Depends(TeacherOfClass),
    db: AsyncSession = Depends(get_db),
) -> ClassOverviewResponse:
    """Get class-wide analytics with per-student breakdowns.

    Returns class name, per-student sim count, mastery, struggling topics,
    last-active times, class average mastery, most struggled topics, and
    total time spent.

    Requires authentication — the requesting user must be the teacher
    of this class, or an admin.
    """
    logger.info("Fetching overview for class %s", class_id)

    overview = await get_class_overview(db, class_id)

    if overview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Class {class_id} not found",
        )

    return ClassOverviewResponse(
        class_id=overview["class_id"],
        class_name=overview["class_name"],
        students=[
            StudentSummary(**s) for s in overview["students"]
        ],
        class_average_mastery=overview["class_average_mastery"],
        most_struggled_topics=overview["most_struggled_topics"],
        total_time_hours=overview["total_time_hours"],
    )


@router.get(
    "/class/{class_id}/mastery-heatmap",
    response_model=MasteryHeatmapResponse,
)
async def class_mastery_heatmap(
    class_id: str,
    _auth: User = Depends(TeacherOfClass),
    db: AsyncSession = Depends(get_db),
) -> MasteryHeatmapResponse:
    """Get mastery heatmap — all students x all skills with mastery levels.

    Returns a grid of students (rows) × skills (columns) where each cell
    contains the student's mastery probability, classification level,
    attempt counts, and last practice date. Skills not attempted by a
    student show as ``not_attempted``.

    Students are sorted by overall mastery descending.

    Requires authentication — the requesting user must be the teacher
    of this class, or an admin.
    """
    logger.info("Fetching mastery heatmap for class %s", class_id)

    heatmap = await get_mastery_heatmap(db, class_id)

    if heatmap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Class {class_id} not found",
        )

    return MasteryHeatmapResponse(
        skills=[MasteryHeatmapSkill(**s) for s in heatmap["skills"]],
        students=[MasteryHeatmapStudent(**s) for s in heatmap["students"]],
        class_average_mastery=heatmap["class_average_mastery"],
        student_count=heatmap["student_count"],
        skill_count=heatmap["skill_count"],
    )


@router.get(
    "/teacher/insights",
    response_model=InsightsResponse,
)
async def teacher_insights(
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> InsightsResponse:
    """Generate rule-based insights & alerts for teacher attention.

    Requires authentication with role='teacher'.
    Insights are scoped to the authenticated teacher's classes.
    """
    logger.info("Generating teacher insights for teacher %s", current_user.id)

    alerts_data = await get_teacher_insights(db, current_user.id)

    return InsightsResponse(
        alerts=[AlertItem(**a) for a in alerts_data],
    )


@router.post(
    "/teacher/assign",
    response_model=AssignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def teacher_assign(
    body: AssignRequest,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> AssignResponse:
    """Assign a simulation to an entire class.

    Validates that the teacher, class, and sim exist, that the teacher
    owns the class, and that the sim slug is valid.

    Requires authentication with role='teacher'. The teacher_id in the
    request body must match the authenticated user's ID.
    """
    logger.info(
        "Assigning sim '%s' to class %s by teacher %s",
        body.sim_slug,
        body.class_id,
        current_user.id,
    )

    # Ensure the teacher is assigning as themselves
    if str(body.teacher_id) != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only assign sims as yourself",
        )

    result = await assign_sim_to_class(
        db=db,
        teacher_id=current_user.id,
        class_id=str(body.class_id),
        sim_slug=body.sim_slug,
        due_date=body.due_date,
        required=body.required,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Teacher, class, or simulation not found — or teacher does not own this class",
        )

    return AssignResponse(
        status=result["status"],
        assignment_id=result["assignment_id"],
    )


@router.get(
    "/teacher/replay/{session_id}",
    response_model=ReplayResponse,
)
async def session_replay(
    session_id: str,
    limit: int = 500,
    after: int | None = None,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> ReplayResponse:
    """Get full session replay — ordered event timeline + metadata.

    Returns all events for a session ordered by client timestamp, along
    with session metadata (student name, sim_slug, start/end time).

    The requesting teacher must have the session's student enrolled in one
    of their classes. Anonymous sessions (no student_id) are not accessible.

    Query params:
    - `limit`  — max events to return (default: 500)
    - `after`  — cursor: event ID to start after (for pagination)
    """
    logger.info(
        "Teacher %s requesting replay for session %s", current_user.id, session_id
    )

    # --- Fetch session to check existence and get student_id ---
    session_result = await db.execute(
        select(SessionModel).where(SessionModel.id == session_id)
    )
    session = session_result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    if session.student_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    # --- Verify teacher owns a class that this student is enrolled in ---
    enrollment_result = await db.execute(
        select(Enrollment)
        .join(ClassModel, ClassModel.id == Enrollment.class_id)
        .where(
            Enrollment.student_id == session.student_id,
            ClassModel.teacher_id == current_user.id,
        )
        .limit(1)
    )
    enrollment = enrollment_result.scalar_one_or_none()

    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this session's replay",
        )

    # --- Fetch replay data ---
    replay_data = await get_session_replay(
        db=db,
        teacher_id=current_user.id,
        session_id=session_id,
        limit=limit,
        after=after,
    )

    if replay_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session replay data not found",
        )

    # Build the response using Pydantic schemas
    return ReplayResponse(
        session=SessionMetadata(**replay_data["session"]),
        events=[ReplayEventItem(**e) for e in replay_data["events"]],
    )


# ── Feedback Review ──────────────────────────────────────────────────


@router.get(
    "/teacher/feedback",
    response_model=FeedbackReviewListResponse,
)
async def list_feedback_for_teacher(
    student_id: Optional[str] = None,
    sim_slug: Optional[str] = None,
    flagged_only: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> FeedbackReviewListResponse:
    """List recent AI feedback given to students in the teacher's classes.

    Returns paginated feedback entries ordered by most recent first.
    Filters by ``student_id``, ``sim_slug``, or ``flagged_only``.

    Requires authentication with role='teacher'.
    Feedback is scoped to students enrolled in the teacher's classes.
    """
    logger.info(
        "Teacher %s listing feedback (student_id=%s, sim_slug=%s, flagged_only=%s)",
        current_user.id, student_id, sim_slug, flagged_only,
    )

    items, total = await list_teacher_feedback(
        db=db,
        teacher_id=current_user.id,
        student_id=student_id,
        sim_slug=sim_slug,
        flagged_only=flagged_only,
        limit=limit,
        offset=offset,
    )

    return FeedbackReviewListResponse(
        feedback=[FeedbackReviewItem(**item) for item in items],
        total=total,
    )


@router.post(
    "/teacher/feedback/{feedback_id}/flag",
    response_model=FlagResponse,
    status_code=status.HTTP_200_OK,
)
async def flag_feedback_item(
    feedback_id: str,
    body: FlagRequest,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> FlagResponse:
    """Flag a feedback item as incorrect, misleading, or inappropriate.

    Requires authentication with role='teacher'.
    Records which teacher flagged it and their reason.
    Returns 404 if the feedback item does not exist.
    """
    logger.info(
        "Teacher %s flagging feedback %s (reason=%s)",
        current_user.id, feedback_id, body.reason,
    )

    result = await flag_feedback(
        db=db,
        feedback_id=feedback_id,
        teacher_id=current_user.id,
        reason=body.reason,
        note=body.note,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback item not found",
        )

    return FlagResponse(
        status="ok",
        feedback_id=result["feedback_id"],
    )


@router.post(
    "/teacher/feedback/{feedback_id}/correct",
    response_model=CorrectResponse,
    status_code=status.HTTP_200_OK,
)
async def correct_feedback_item(
    feedback_id: str,
    body: CorrectRequest,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> CorrectResponse:
    """Provide a corrected version of a feedback text.

    Requires authentication with role='teacher'.
    Stores the teacher's correction for future model improvement.
    Returns 404 if the feedback item does not exist.
    """
    logger.info(
        "Teacher %s correcting feedback %s",
        current_user.id, feedback_id,
    )

    result = await correct_feedback(
        db=db,
        feedback_id=feedback_id,
        corrected_text=body.corrected_text,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback item not found",
        )

    return CorrectResponse(
        status="ok",
        feedback_id=result["feedback_id"],
    )


# ── Alert Dashboard ───────────────────────────────────────────────────


@router.websocket("/teacher/ws")
async def teacher_alert_ws(
    websocket: WebSocket,
    user: User | None = Depends(get_ws_user),
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for real-time alert notifications.

    Accepts a ``token`` query parameter (JWT). After authentication,
    the server pushes ``new_alert`` events as JSON. The teacher keeps
    the connection open and listens for incoming alert payloads.

    Authentication failure closes with code 4001.
    """
    if user is None or user.role != "teacher":
        await websocket.close(code=4003, reason="Teacher role required")
        return

    await websocket.accept()
    register_ws(user.id, websocket)

    try:
        # Keep the connection alive — listen for ping/pong
        while True:
            data = await websocket.receive_text()
            # Client can send {"type": "ping"} to keep alive
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        unregister_ws(user.id, websocket)


@router.get(
    "/teacher/alerts",
    response_model=AlertListResponse,
)
async def active_alerts(
    class_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """List active (unresolved) alerts for the teacher.

    Optionally filter by class_id, severity, or alert_type.
    Supports pagination via limit/offset.
    """
    alerts, total = await list_active_alerts(
        db, current_user.id,
        class_id=class_id,
        severity=severity,
        alert_type=alert_type,
        limit=limit,
        offset=offset,
    )
    return AlertListResponse(
        alerts=[AlertItemFull(**a) for a in alerts],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/teacher/alerts/history",
    response_model=AlertListResponse,
)
async def alert_history(
    class_id: Optional[str] = Query(None),
    days: int = Query(30, description="How many days back to include"),
    limit: int = Query(50),
    offset: int = Query(0),
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """List resolved or older alerts within a date range."""
    alerts, total = await list_alert_history(
        db, current_user.id,
        class_id=class_id,
        days=days,
        limit=limit,
        offset=offset,
    )
    return AlertListResponse(
        alerts=[AlertItemFull(**a) for a in alerts],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/teacher/alerts/stats",
    response_model=AlertStatsResponse,
)
async def alert_stats(
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> AlertStatsResponse:
    """Get summary counts for the alert badge on the teacher dashboard."""
    stats = await get_alert_stats(db, current_user.id)
    return AlertStatsResponse(**stats)


@router.post(
    "/teacher/alerts/{alert_id}/acknowledge",
    response_model=AlertAcknowledgeResponse,
)
async def acknowledge_teacher_alert(
    alert_id: str,
    body: AlertAcknowledgeRequest,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> AlertAcknowledgeResponse:
    """Mark an alert as acknowledged (or un-acknowledged)."""
    result = await acknowledge_alert(
        db, alert_id, current_user.id, acknowledged=body.acknowledged
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found or does not belong to you",
        )
    return AlertAcknowledgeResponse(
        status="ok",
        alert_id=result["id"],
        acknowledged=result["acknowledged"],
        resolved=result["resolved"],
    )


@router.post(
    "/teacher/alerts/{alert_id}/resolve",
    response_model=AlertAcknowledgeResponse,
)
async def resolve_teacher_alert(
    alert_id: str,
    body: AlertResolveRequest,
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> AlertAcknowledgeResponse:
    """Mark an alert as resolved (or re-open)."""
    result = await resolve_alert(
        db, alert_id, current_user.id, resolved=body.resolved
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found or does not belong to you",
        )
    return AlertAcknowledgeResponse(
        status="ok",
        alert_id=result["id"],
        acknowledged=result["acknowledged"],
        resolved=result["resolved"],
    )


@router.post(
    "/teacher/alerts/generate",
    status_code=status.HTTP_200_OK,
)
async def generate_alerts(
    current_user: User = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-run rule-based alert generation and broadcast new alerts.

    Scans all of the teacher's classes for struggling students, class trends,
    and inactivity. Newly created alerts are broadcast via WebSocket to all
    connected teacher sessions.
    """
    new_alerts = await generate_and_persist_alerts(db, current_user.id)

    # Broadcast each new alert to the teacher's WebSocket connections
    for alert in new_alerts:
        await broadcast_alert(current_user.id, alert)

    return {"status": "ok", "created": len(new_alerts)}
