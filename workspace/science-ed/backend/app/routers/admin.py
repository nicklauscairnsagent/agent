"""Admin router — system stats, catalog sync, data export, and compliance reports.

This module provides district admin functionality:
- /export/* — CSV data exports of students and classes
- /reports/* — aggregated usage stats and privacy audit logs
- Existing /stats and /sims/refresh endpoints

All endpoints require the authenticated user to have role='admin'.
Export endpoints are also rate-limited due to their heavyweight queries.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.middleware.rate_limit import rate_limit_exports
from app.models import (
    User,
    ClassModel,
    Enrollment,
    Assignment,
    SessionModel,
    Event,
    FeedbackLog,
    SkillState,
    TeacherAction,
    Sim,
)
from app.schemas import (
    AdminStatsResponse,
    SimsRefreshResponse,
    ExportStudentRecord,
    ExportClassRecord,
    UsageReportResponse,
    DailyActiveUser,
    TopSim,
    PrivacyAuditEntry,
    PrivacyAuditResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# ── Existing endpoints ────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    summary="Get system-wide statistics",
    description="Return platform-wide statistics for the admin dashboard: "
    "student/teacher counts, session/event volumes, LLM usage and cost.",
)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_role("admin")),
):
    """Return system-wide statistics.

    Queries live counts from the database.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Counts
    student_count = (
        await db.execute(select(sa_func.count(User.id)).where(User.role == "student"))
    ).scalar() or 0
    teacher_count = (
        await db.execute(select(sa_func.count(User.id)).where(User.role == "teacher"))
    ).scalar() or 0
    session_count = (
        await db.execute(select(sa_func.count(SessionModel.id)))
    ).scalar() or 0
    event_count = (
        await db.execute(select(sa_func.count(Event.id)))
    ).scalar() or 0
    active_today = (
        await db.execute(
            select(sa_func.count(User.id)).where(
                User.last_active_at >= today_start
            )
        )
    ).scalar() or 0
    feedback_count = (
        await db.execute(select(sa_func.count(FeedbackLog.id)))
    ).scalar() or 0

    # Events per minute (avg over last hour)
    hour_ago = now.timestamp() - 3600
    recent_events = (
        await db.execute(
            select(sa_func.count(Event.id)).where(
                Event.server_ts >= datetime.fromtimestamp(hour_ago, tz=timezone.utc)
            )
        )
    ).scalar() or 0
    e_per_min = round(recent_events / 60, 2) if recent_events else 0.0

    # LLM cost estimate: approximate from feedback log tokens
    llm_tokens = (
        await db.execute(
            select(sa_func.coalesce(sa_func.sum(FeedbackLog.tokens_used), 0)).where(
                FeedbackLog.source == "llm"
            )
        )
    ).scalar() or 0
    # Rough cost: $0.15 per 1K tokens for GPT-4o-mini
    llm_cost = round(llm_tokens * 0.15 / 1000, 4)

    return AdminStatsResponse(
        total_students=student_count,
        total_teachers=teacher_count,
        total_sessions=session_count,
        total_events=event_count,
        active_today=active_today,
        events_per_minute_avg=e_per_min,
        llm_calls_today=feedback_count,
        llm_cost_today_usd=llm_cost,
    )


@router.post(
    "/sims/refresh",
    response_model=SimsRefreshResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Refresh simulation catalog",
    description="Refresh the sims catalog from the Jekyll frontmatter. "
    "Scans the GitHub Pages site catalog JSON and syncs sim records.",
)
async def admin_sims_refresh(
    _current_user=Depends(require_role("admin")),
):
    """Refresh the sims catalog from the Jekyll frontmatter.

    Requires authentication with role='admin'.
    Scans GitHub Pages catalog and syncs sim records.
    """
    # TODO: implement real sync logic
    logger.info("Admin sims refresh requested")
    return SimsRefreshResponse(
        sims_found=0,
        sims_added=0,
        sims_updated=0,
        sims_removed=0,
    )


# ── Helper: build CSV from a list of dicts ────────────────────────────


def _to_csv(rows: list[dict]) -> str:
    """Convert a list of dicts to CSV string. Returns headers even for empty lists."""
    output = io.StringIO()
    # Use a fixed field order for consistency
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = []
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _format_dt(dt: datetime | None) -> str:
    """Format datetime as ISO string, or empty string."""
    if dt is None:
        return ""
    return dt.isoformat()


# ── Data Export — Students ────────────────────────────────────────────


@router.get(
    "/export/students",
    summary="Export all student data as CSV",
    description="Download a CSV file of all students with their progress data. "
    "Supports ?from= and ?to= date range filtering on created_at. "
    "Rate-limited to 10 requests per 60 seconds per admin user.",
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV file with student data",
        },
        429: {"description": "Rate limit exceeded"},
    },
)
async def export_students(
    response: Response,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_role("admin")),
    _rate=Depends(rate_limit_exports()),
):
    """Export all student data as CSV.

    Includes progress metrics computed from sessions, events, feedback logs,
    and skill states.
    """
    # Base query — only students (not deleted)
    query = select(User).where(User.role == "student", User.deleted_at.is_(None))

    if date_from:
        try:
            raw = date_from.replace(" ", "+")
            dt_from = datetime.fromisoformat(raw)
            query = query.where(User.created_at >= dt_from)
        except ValueError:
            logger.warning("Invalid ?from date: %s", date_from)
    if date_to:
        try:
            raw = date_to.replace(" ", "+")
            dt_to = datetime.fromisoformat(raw)
            query = query.where(User.created_at <= dt_to)
        except ValueError:
            logger.warning("Invalid ?to date: %s", date_to)

    result = await db.execute(query)
    students = result.scalars().all()

    rows: list[dict] = []
    for student in students:
        # Session stats
        s_result = await db.execute(
            select(
                sa_func.count(SessionModel.id).label("count"),
                sa_func.avg(SessionModel.duration_seconds).label("avg_dur"),
            ).where(
                SessionModel.student_id == student.id,
                SessionModel.ended_at.isnot(None),
            )
        )
        s_row = s_result.one()
        total_sessions = s_row.count or 0
        avg_dur = s_row.avg_dur
        avg_dur = float(avg_dur) if avg_dur is not None else None

        # Events
        event_count = (
            await db.execute(
                select(sa_func.count(Event.id)).where(Event.student_id == student.id)
            )
        ).scalar() or 0

        # Completed sessions (is_completed=True)
        completed = (
            await db.execute(
                select(sa_func.count(SessionModel.id)).where(
                    SessionModel.student_id == student.id,
                    SessionModel.is_completed.is_(True),
                )
            )
        ).scalar() or 0

        # Feedback received
        feedback_count = (
            await db.execute(
                select(sa_func.count(FeedbackLog.id)).where(
                    FeedbackLog.student_id == student.id
                )
            )
        ).scalar() or 0

        # Skill states
        skill_count = (
            await db.execute(
                select(sa_func.count(SkillState.id)).where(
                    SkillState.student_id == student.id
                )
            )
        ).scalar() or 0
        avg_mastery = None
        if skill_count > 0:
            avg_m = (
                await db.execute(
                    select(sa_func.avg(SkillState.probability)).where(
                        SkillState.student_id == student.id
                    )
                )
            ).scalar()
            if avg_m is not None:
                avg_mastery = round(float(avg_m), 4)

        rows.append(
            {
                "user_id": student.id,
                "email": student.email or "",
                "username": student.username or "",
                "display_name": student.display_name or "",
                "role": student.role,
                "created_at": _format_dt(student.created_at),
                "last_active_at": _format_dt(student.last_active_at),
                "total_sessions": total_sessions,
                "total_events": event_count,
                "sims_completed": completed,
                "avg_session_duration_seconds": avg_dur if avg_dur is not None else "",
                "total_feedback_received": feedback_count,
                "skill_count": skill_count,
                "avg_mastery": avg_mastery if avg_mastery is not None else "",
            }
        )

    csv_content = _to_csv(rows)
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="students_export.csv"'},
    )


# ── Data Export — Classes ─────────────────────────────────────────────


@router.get(
    "/export/classes",
    summary="Export class rosters and assignment completion as CSV",
    description="Download a CSV file of all classes with teacher info, "
    "student counts, and assignment completion data. "
    "Supports ?from= and ?to= date range filtering on class created_at. "
    "Rate-limited to 10 requests per 60 seconds per admin user.",
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV file with class data",
        },
        429: {"description": "Rate limit exceeded"},
    },
)
async def export_classes(
    response: Response,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_role("admin")),
    _rate=Depends(rate_limit_exports()),
):
    """Export class data as CSV.

    Includes teacher information, student counts, assignment counts,
    and aggregate completion metrics.
    """
    query = select(ClassModel)

    if date_from:
        try:
            raw = date_from.replace(" ", "+")
            dt_from = datetime.fromisoformat(raw)
            query = query.where(ClassModel.created_at >= dt_from)
        except ValueError:
            logger.warning("Invalid ?from date: %s", date_from)
    if date_to:
        try:
            raw = date_to.replace(" ", "+")
            dt_to = datetime.fromisoformat(raw)
            query = query.where(ClassModel.created_at <= dt_to)
        except ValueError:
            logger.warning("Invalid ?to date: %s", date_to)

    result = await db.execute(query)
    classes = result.scalars().all()

    rows: list[dict] = []
    for cls in classes:
        # Teacher info
        teacher_name = ""
        teacher_email = ""
        if cls.teacher:
            teacher_name = cls.teacher.display_name or ""
            teacher_email = cls.teacher.email or ""

        # Student count
        student_count = (
            await db.execute(
                select(sa_func.count(Enrollment.id)).where(
                    Enrollment.class_id == cls.id
                )
            )
        ).scalar() or 0

        # Assignment count
        assignment_count = (
            await db.execute(
                select(sa_func.count(Assignment.id)).where(
                    Assignment.class_id == cls.id
                )
            )
        ).scalar() or 0

        # Assignments completed: count sessions for enrolled students
        # that have is_completed=True and belong to assigned sims
        completed = (
            await db.execute(
                select(sa_func.count(SessionModel.id))
                .join(
                    Enrollment,
                    Enrollment.student_id == SessionModel.student_id,
                )
                .where(
                    Enrollment.class_id == cls.id,
                    SessionModel.is_completed.is_(True),
                )
            )
        ).scalar() or 0

        rows.append(
            {
                "class_id": cls.id,
                "class_name": cls.name,
                "class_code": cls.class_code,
                "subject": cls.subject or "",
                "grade_level": cls.grade_level or "",
                "school_name": cls.school_name or "",
                "teacher_name": teacher_name,
                "teacher_email": teacher_email,
                "student_count": student_count,
                "assignment_count": assignment_count,
                "assignments_completed": completed,
                "created_at": _format_dt(cls.created_at),
                "is_active": cls.is_active,
            }
        )

    csv_content = _to_csv(rows)
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="classes_export.csv"'},
    )


# ── Usage Report ──────────────────────────────────────────────────────


@router.get(
    "/reports/usage",
    response_model=UsageReportResponse,
    summary="Aggregate platform usage statistics",
    description="Return aggregated usage stats: daily active users, "
    "total counts, most-used sims, and averages. "
    "Supports ?from= and ?to= date range filtering.",
)
async def report_usage(
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_role("admin")),
):
    """Return aggregated platform usage statistics.

    All counts are live database queries aggregated across the
    optional date range.
    """
    # Parse date range
    dt_from: datetime | None = None
    dt_to: datetime | None = None
    if date_from:
        try:
            raw = date_from.replace(" ", "+")
            dt_from = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Invalid ?from date: %s", date_from)
    if date_to:
        try:
            raw = date_to.replace(" ", "+")
            dt_to = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Invalid ?to date: %s", date_to)

    # ── Total counts ──
    student_count = (
        await db.execute(
            select(sa_func.count(User.id)).where(
                User.role == "student", User.deleted_at.is_(None)
            )
        )
    ).scalar() or 0
    teacher_count = (
        await db.execute(
            select(sa_func.count(User.id)).where(
                User.role == "teacher", User.deleted_at.is_(None)
            )
        )
    ).scalar() or 0
    class_count = (
        await db.execute(select(sa_func.count(ClassModel.id)))
    ).scalar() or 0
    sim_count = (
        await db.execute(
            select(sa_func.count()).select_from(
                select(SessionModel.sim_id)
                .distinct()
                .where(SessionModel.sim_id.isnot(None))
                .subquery()
            )
        )
    ).scalar() or 0
    assignment_count = (
        await db.execute(select(sa_func.count(Assignment.id)))
    ).scalar() or 0
    feedback_count = (
        await db.execute(select(sa_func.count(FeedbackLog.id)))
    ).scalar() or 0

    # ── Session / Event counts ──
    session_query = select(sa_func.count(SessionModel.id))
    event_query = select(sa_func.count(Event.id))
    if dt_from:
        session_query = session_query.where(SessionModel.started_at >= dt_from)
        event_query = event_query.where(Event.server_ts >= dt_from)
    if dt_to:
        session_query = session_query.where(SessionModel.started_at <= dt_to)
        event_query = event_query.where(Event.server_ts <= dt_to)

    total_sessions = (await db.execute(session_query)).scalar() or 0
    total_events = (await db.execute(event_query)).scalar() or 0

    # ── Average session duration ──
    avg_dur_query = select(sa_func.avg(SessionModel.duration_seconds)).where(
        SessionModel.duration_seconds.isnot(None)
    )
    if dt_from:
        avg_dur_query = avg_dur_query.where(SessionModel.started_at >= dt_from)
    if dt_to:
        avg_dur_query = avg_dur_query.where(SessionModel.started_at <= dt_to)
    avg_dur_raw = (await db.execute(avg_dur_query)).scalar()
    avg_dur = round(float(avg_dur_raw), 2) if avg_dur_raw else None

    # ── Avg sessions per student ──
    avg_sessions = None
    if student_count > 0:
        avg_sessions_raw = total_sessions / student_count
        avg_sessions = round(float(avg_sessions_raw), 2)

    # ── Daily active users (last 30 days) ──
    thirty_days_ago = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # Use last_active_at grouped by date
    daily_query = (
        select(
            sa_func.date(User.last_active_at).label("date"),
            sa_func.count(User.id).label("count"),
        )
        .where(
            User.last_active_at >= thirty_days_ago,
            User.role == "student",
            User.deleted_at.is_(None),
        )
        .group_by(sa_func.date(User.last_active_at))
        .order_by(sa_func.date(User.last_active_at))
    )
    daily_result = await db.execute(daily_query)
    daily_active = [
        DailyActiveUser(date=str(row.date), count=row.count)
        for row in daily_result
    ]

    # ── Top sims (by session count) ──
    top_query = (
        select(
            SessionModel.sim_id,
            sa_func.count(SessionModel.id).label("cnt"),
        )
        .where(SessionModel.sim_id.isnot(None))
        .group_by(SessionModel.sim_id)
        .order_by(sa_func.count(SessionModel.id).desc())
        .limit(10)
    )
    top_result = await db.execute(top_query)
    top_sim_ids = [row.sim_id for row in top_result]

    top_sims_list: list[TopSim] = []
    for sim_id in top_sim_ids:
        sim_row = await db.execute(
            select(Sim).where(Sim.id == sim_id)
        )
        sim = sim_row.scalar_one_or_none()
        if sim is None:
            continue
        count_result = await db.execute(
            select(sa_func.count(SessionModel.id)).where(
                SessionModel.sim_id == sim_id
            )
        )
        cnt = count_result.scalar() or 0
        top_sims_list.append(
            TopSim(
                sim_slug=sim.slug,
                sim_title=sim.title_en,
                session_count=cnt,
            )
        )

    return UsageReportResponse(
        total_students=student_count,
        total_teachers=teacher_count,
        total_classes=class_count,
        total_sims=sim_count,
        total_sessions=total_sessions,
        total_events=total_events,
        total_assignments=assignment_count,
        total_feedback_calls=feedback_count,
        avg_session_duration_seconds=avg_dur,
        avg_sessions_per_student=avg_sessions,
        daily_active_users=daily_active,
        top_sims=top_sims_list,
        date_range_from=date_from,
        date_range_to=date_to,
    )


# ── Privacy Audit Log ─────────────────────────────────────────────────


@router.get(
    "/reports/privacy",
    response_model=PrivacyAuditResponse,
    summary="Student data access audit log",
    description="Return a log of who accessed what student data and when. "
    "Includes teacher flagging/correcting of feedback, and teacher "
    "actions on student data. Supports ?from= and ?to= date range filtering.",
)
async def report_privacy(
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_role("admin")),
):
    """Return a student data access audit log.

    Sources for the audit trail:
    1. TeacherAction records — teachers viewing classes/students
    2. FeedbackLog flagging — teachers flagging or correcting AI feedback
    3. Direct session queries for teacher activity
    """
    dt_from: datetime | None = None
    dt_to: datetime | None = None
    if date_from:
        try:
            raw = date_from.replace(" ", "+")
            dt_from = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Invalid ?from date: %s", date_from)
    if date_to:
        try:
            raw = date_to.replace(" ", "+")
            dt_to = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("Invalid ?to date: %s", date_to)

    entries: list[PrivacyAuditEntry] = []

    # ── Source 1: TeacherAction entries ──
    ta_query = select(TeacherAction)
    if dt_from:
        ta_query = ta_query.where(TeacherAction.created_at >= dt_from)
    if dt_to:
        ta_query = ta_query.where(TeacherAction.created_at <= dt_to)
    ta_query = ta_query.order_by(TeacherAction.created_at.desc()).limit(500)

    ta_result = await db.execute(ta_query)
    for ta in ta_result.scalars().all():
        target_type = "class" if ta.class_id else "student"
        actor_name = ""
        if ta.teacher:
            actor_name = ta.teacher.display_name or ta.teacher.email or ""

        entries.append(
            PrivacyAuditEntry(
                id=ta.id,
                timestamp=_format_dt(ta.created_at),
                actor_type="teacher",
                actor_id=ta.teacher_id,
                actor_name=actor_name,
                action=ta.action_type,
                target_type=target_type,
                target_id=ta.target_id or ta.class_id or "",
                target_name="",
                details=ta.extra_data or {},
            )
        )

    # ── Source 2: FeedbackLog flagging by teachers ──
    fl_query = select(FeedbackLog).where(FeedbackLog.is_flagged.is_(True))
    if dt_from:
        fl_query = fl_query.where(FeedbackLog.created_at >= dt_from)
    if dt_to:
        fl_query = fl_query.where(FeedbackLog.created_at <= dt_to)
    fl_query = fl_query.order_by(FeedbackLog.created_at.desc()).limit(500)

    fl_result = await db.execute(fl_query)
    for fl in fl_result.scalars().all():
        actor_name = ""
        if fl.flagger:
            actor_name = fl.flagger.display_name or fl.flagger.email or ""

        target_name = ""
        if fl.student:
            target_name = fl.student.display_name or fl.student.email or ""

        entries.append(
            PrivacyAuditEntry(
                id=f"flag_{fl.id}",
                timestamp=_format_dt(fl.created_at),
                actor_type="teacher",
                actor_id=fl.flagged_by or "",
                actor_name=actor_name,
                action=f"flagged_feedback: {fl.flag_reason or 'other'}",
                target_type="feedback",
                target_id=fl.student_id or "",
                target_name=target_name,
                details={
                    "feedback_type": fl.feedback_type,
                    "session_id": fl.session_id,
                    "flag_reason": fl.flag_reason,
                    "corrected": bool(fl.corrected_text),
                },
            )
        )

    # Sort combined entries by timestamp descending
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    total = len(entries)

    return PrivacyAuditResponse(
        entries=entries,
        total=total,
        date_range_from=date_from,
        date_range_to=date_to,
    )
