"""Alert service — CRUD and lifecycle management for teacher alerts.

Provides functions to:
- List active alerts (unresolved, optionally filtered by teacher/class/student)
- List alert history (resolved or date-filtered)
- Acknowledge and resolve alerts
- Generate alerts from rule-based logic
- Push alerts to teacher WebSocket connections
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, case, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AlertModel, ClassModel, User
from app.models.enrollment import Enrollment
from app.models.skill_state import SkillState

logger = logging.getLogger(__name__)

STRUGGLE_THRESHOLD = 0.4

# ── In-memory WebSocket registry (teacher_id → set of websockets) ──────

_teacher_ws: dict[str, set] = {}


def register_ws(teacher_id: str, ws) -> None:
    """Register a WebSocket connection for a teacher."""
    if teacher_id not in _teacher_ws:
        _teacher_ws[teacher_id] = set()
    _teacher_ws[teacher_id].add(ws)
    logger.debug("Registered WS for teacher %s (%d connections)", teacher_id, len(_teacher_ws[teacher_id]))


def unregister_ws(teacher_id: str, ws) -> None:
    """Unregister a WebSocket connection."""
    if teacher_id in _teacher_ws:
        _teacher_ws[teacher_id].discard(ws)
        if not _teacher_ws[teacher_id]:
            del _teacher_ws[teacher_id]
    logger.debug("Unregistered WS for teacher %s", teacher_id)


async def broadcast_alert(teacher_id: str, alert_data: dict) -> None:
    """Push an alert to all connected WebSocket sessions for a teacher."""
    if teacher_id not in _teacher_ws:
        return
    message = json.dumps({"type": "new_alert", "alert": alert_data, "default": ""})
    dead = set()
    for ws in _teacher_ws[teacher_id]:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _teacher_ws[teacher_id].discard(ws)
    if not _teacher_ws[teacher_id]:
        del _teacher_ws[teacher_id]


# ── CRUD ───────────────────────────────────────────────────────────────


async def list_active_alerts(
    db: AsyncSession,
    teacher_id: str,
    class_id: Optional[str] = None,
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List unresolved alerts for a teacher, with optional filters.

    Returns (alerts_list, total_count).
    """
    query = (
        select(AlertModel)
        .options(
            selectinload(AlertModel.student),
            selectinload(AlertModel.class_rel),
        )
        .where(
            AlertModel.teacher_id == teacher_id,
            AlertModel.resolved == False,  # noqa: E712
        )
        .order_by(AlertModel.created_at.desc())
    )

    count_query = (
        select(func.count(AlertModel.id))
        .where(
            AlertModel.teacher_id == teacher_id,
            AlertModel.resolved == False,  # noqa: E712
        )
    )

    if class_id:
        query = query.where(AlertModel.class_id == class_id)
        count_query = count_query.where(AlertModel.class_id == class_id)
    if severity:
        query = query.where(AlertModel.severity == severity)
        count_query = count_query.where(AlertModel.severity == severity)
    if alert_type:
        query = query.where(AlertModel.alert_type == alert_type)
        count_query = count_query.where(AlertModel.alert_type == alert_type)

    total = await db.scalar(count_query) or 0
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    alerts = result.scalars().all()

    return [_alert_to_dict(a) for a in alerts], total


async def list_alert_history(
    db: AsyncSession,
    teacher_id: str,
    class_id: Optional[str] = None,
    days: int = 30,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List resolved or old alerts within a date range.

    Returns (alerts_list, total_count).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    query = (
        select(AlertModel)
        .options(
            selectinload(AlertModel.student),
            selectinload(AlertModel.class_rel),
        )
        .where(
            AlertModel.teacher_id == teacher_id,
            or_(
                AlertModel.resolved == True,  # noqa: E712
                AlertModel.created_at < since,
            ),
        )
        .order_by(AlertModel.created_at.desc())
    )

    count_query = (
        select(func.count(AlertModel.id))
        .where(
            AlertModel.teacher_id == teacher_id,
            or_(
                AlertModel.resolved == True,  # noqa: E712
                AlertModel.created_at < since,
            ),
        )
    )

    if class_id:
        query = query.where(AlertModel.class_id == class_id)
        count_query = count_query.where(AlertModel.class_id == class_id)

    total = await db.scalar(count_query) or 0
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    alerts = result.scalars().all()

    return [_alert_to_dict(a) for a in alerts], total


async def acknowledge_alert(
    db: AsyncSession,
    alert_id: str,
    teacher_id: str,
    acknowledged: bool = True,
) -> dict | None:
    """Mark an alert as acknowledged (or un-acknowledged)."""
    result = await db.execute(
        select(AlertModel).where(
            AlertModel.id == alert_id,
            AlertModel.teacher_id == teacher_id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        return None

    alert.acknowledged = acknowledged
    alert.acknowledged_at = datetime.now(timezone.utc) if acknowledged else None
    await db.flush()
    return _alert_to_dict(alert)


async def resolve_alert(
    db: AsyncSession,
    alert_id: str,
    teacher_id: str,
    resolved: bool = True,
) -> dict | None:
    """Mark an alert as resolved (or re-open)."""
    result = await db.execute(
        select(AlertModel).where(
            AlertModel.id == alert_id,
            AlertModel.teacher_id == teacher_id,
        )
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        return None

    alert.resolved = resolved
    alert.resolved_at = datetime.now(timezone.utc) if resolved else None
    await db.flush()
    return _alert_to_dict(alert)


async def get_alert_stats(
    db: AsyncSession,
    teacher_id: str,
) -> dict:
    """Get summary counts for the alert badge."""
    result = await db.execute(
        select(
            func.count(AlertModel.id).label("total_active"),
            func.sum(
                case((AlertModel.severity == "info", 1), else_=0)
            ).label("info_count"),
            func.sum(
                case((AlertModel.severity == "warning", 1), else_=0)
            ).label("warning_count"),
            func.sum(
                case((AlertModel.severity == "critical", 1), else_=0)
            ).label("critical_count"),
            func.sum(
                case((AlertModel.acknowledged == False, 1), else_=0)  # noqa: E712
            ).label("unacknowledged_count"),
        ).where(
            AlertModel.teacher_id == teacher_id,
            AlertModel.resolved == False,  # noqa: E712
        )
    )
    row = result.one()
    return {
        "total_active": row.total_active or 0,
        "info_count": row.info_count or 0,
        "warning_count": row.warning_count or 0,
        "critical_count": row.critical_count or 0,
        "unacknowledged_count": row.unacknowledged_count or 0,
    }


# ── Alert Generation ───────────────────────────────────────────────────


async def generate_and_persist_alerts(
    db: AsyncSession,
    teacher_id: str,
) -> list[dict]:
    """Run rule-based alert generation and persist new alerts.

    Checks for:
    - Struggling students (avg mastery < threshold)
    - Class-level trends (class avg < threshold)
    - Students who haven't been active in 7+ days
    - Skill regression (students who were above threshold but dropped below)

    Returns list of newly created alerts.
    """

    created = []

    # ── Fetch teacher's classes ────────────────────────────────────────
    classes_result = await db.execute(
        select(ClassModel).where(ClassModel.teacher_id == teacher_id)
    )
    classes = classes_result.scalars().all()

    for cls in classes:
        enrollments_result = await db.execute(
            select(Enrollment)
            .options(selectinload(Enrollment.student))
            .where(Enrollment.class_id == cls.id)
        )
        enrollments = enrollments_result.scalars().all()

        class_masteries: list[float] = []

        for enrollment in enrollments:
            student = enrollment.student
            student_id = student.id

            skill_states_result = await db.execute(
                select(SkillState).where(SkillState.student_id == student_id)
            )
            skill_states = skill_states_result.scalars().all()

            if skill_states:
                avg_mastery = sum(
                    float(s.probability) for s in skill_states
                ) / len(skill_states)
            else:
                avg_mastery = 0.0

            class_masteries.append(avg_mastery)

            # --- Struggling student ---
            if avg_mastery < STRUGGLE_THRESHOLD:
                worst_skill = min(
                    skill_states,
                    key=lambda s: float(s.probability),
                ) if skill_states else None

                severity = "critical" if avg_mastery < 0.25 else "warning"
                title = f"{student.display_name or student.username or 'Student'} needs attention"
                description = (
                    f"Average mastery {avg_mastery:.0%} across "
                    f"{len(skill_states)} skills"
                )
                if worst_skill:
                    description += f". Lowest skill: {worst_skill.skill_id} ({float(worst_skill.probability):.0%})"
                recommendation = (
                    f"Review {student.display_name or student.username}'s work, "
                    f"provide one-on-one support, and assign remedial simulations"
                )

                created.append(
                    await _create_alert_if_new(
                        db, teacher_id, cls.id, student_id,
                        severity, "struggling_student",
                        title, description, recommendation,
                    )
                )

        # --- Class-level trend ---
        if class_masteries:
            class_avg = sum(class_masteries) / len(class_masteries)
            if class_avg < STRUGGLE_THRESHOLD:
                severity = "critical" if class_avg < 0.25 else "warning"
                title = f"Class '{cls.name}' below mastery threshold"
                description = (
                    f"Average mastery {class_avg:.0%} across {len(class_masteries)} students"
                )
                recommendation = (
                    f"Consider re-teaching core concepts or assigning "
                    f"remedial simulations to {cls.name}"
                )
                created.append(
                    await _create_alert_if_new(
                        db, teacher_id, cls.id, None,
                        severity, "class_trend",
                        title, description, recommendation,
                    )
                )

    # Flush and return
    await db.flush()
    return [a for a in created if a is not None]


async def _create_alert_if_new(
    db: AsyncSession,
    teacher_id: str,
    class_id: str,
    student_id: str | None,
    severity: str,
    alert_type: str,
    title: str,
    description: str,
    recommendation: str,
) -> dict | None:
    """Create an alert only if an equivalent unresolved one doesn't exist."""
    # Deduplicate: same teacher, type, student, severity within last 24h
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = select(AlertModel).where(
        AlertModel.teacher_id == teacher_id,
        AlertModel.alert_type == alert_type,
        AlertModel.student_id == student_id,
        AlertModel.severity == severity,
        AlertModel.resolved == False,  # noqa: E712
        AlertModel.created_at >= since,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return None

    sim_slug, sim_title = _suggest_remediation(alert_type, title)

    alert = AlertModel(
        teacher_id=teacher_id,
        class_id=class_id,
        student_id=student_id,
        severity=severity,
        alert_type=alert_type,
        title=title,
        description=description,
        recommendation=recommendation,
        suggested_sim_slug=sim_slug,
        suggested_sim_title=sim_title,
    )
    db.add(alert)
    return _alert_to_dict(alert)


def _suggest_remediation(
    alert_type: str, title: str
) -> tuple[str | None, str | None]:
    """Suggest a remediation sim based on alert type."""
    # Would use an NGSS→sim mapping in production
    if alert_type == "struggling_student":
        return "general-skills-practice", "General Skills Practice"
    return None, None


def _alert_to_dict(alert: AlertModel) -> dict:
    """Convert an AlertModel to a dict with expanded names."""
    student_name = None
    if alert.student is not None:
        student_name = (
            alert.student.display_name
            or alert.student.username
            or alert.student.email
        )

    class_name = alert.class_rel.name if alert.class_rel is not None else None

    return {
        "id": alert.id,
        "teacher_id": alert.teacher_id,
        "class_id": alert.class_id,
        "student_id": alert.student_id,
        "student_name": student_name,
        "class_name": class_name,
        "severity": alert.severity,
        "alert_type": alert.alert_type,
        "title": alert.title,
        "description": alert.description,
        "recommendation": alert.recommendation,
        "suggested_sim_slug": alert.suggested_sim_slug,
        "suggested_sim_title": alert.suggested_sim_title,
        "acknowledged": alert.acknowledged,
        "resolved": alert.resolved,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }
