"""Teacher dashboard and classroom management service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    User,
    ClassModel,
    Enrollment,
    SkillState,
    SessionModel,
    Sim,
    Assignment,
    TeacherAction,
    Event,
    FeedbackLog,
)
from app.schemas.extra_data import ALLOWED_TEACHER_ACTION_KEYS, validate_extra_data_dict

logger = logging.getLogger(__name__)

# Mastery probability below which a student is considered "struggling"
STRUGGLE_THRESHOLD = 0.4


async def get_teacher_classes(
    db: AsyncSession,
    teacher_id: str,
) -> list[dict]:
    """List all classes for a teacher with summary stats.

    Returns a list of dicts matching ``ClassSummary`` schema fields:
    id, name, student_count, active_today, average_mastery, class_code,
    struggling_students.
    """
    # --- Fetch the teacher's classes ---
    classes_result = await db.execute(
        select(ClassModel)
        .where(ClassModel.teacher_id == teacher_id)
        .order_by(ClassModel.created_at.desc())
    )
    classes = classes_result.scalars().all()

    if not classes:
        return []

    # --- For each class gather stats ---
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    summaries = []
    for cls in classes:
        # Student count: number of enrollments
        enroll_count = await db.scalar(
            select(func.count(Enrollment.id)).where(
                Enrollment.class_id == cls.id
            )
        )

        # Active today: enrolled students whose last_active_at >= today_start
        active_today = await db.scalar(
            select(func.count(User.id))
            .select_from(Enrollment)
            .join(User, Enrollment.student_id == User.id)
            .where(
                Enrollment.class_id == cls.id,
                User.last_active_at >= today_start,
            )
        )

        # Average mastery: average of per-student skill probability averages
        per_student_avg = (
            select(
                func.avg(SkillState.probability).label("student_avg")
            )
            .where(SkillState.student_id == Enrollment.student_id)
            .correlate(Enrollment)
            .scalar_subquery()
        )
        class_avg_result = await db.execute(
            select(func.avg(per_student_avg))
            .select_from(Enrollment)
            .where(Enrollment.class_id == cls.id)
        )
        avg_mastery_val = class_avg_result.scalar()
        avg_mastery = float(avg_mastery_val) if avg_mastery_val is not None else 0.0

        # Struggling students: count distinct enrolled students
        # whose average skill probability across all skills < threshold
        # We use a subquery: for each enrolled student, get their avg mastery
        # and count those below threshold
        struggle_subq = (
            select(
                SkillState.student_id,
                func.avg(SkillState.probability).label("avg_mastery"),
            )
            .select_from(Enrollment)
            .join(SkillState, SkillState.student_id == Enrollment.student_id)
            .where(Enrollment.class_id == cls.id)
            .group_by(SkillState.student_id)
            .subquery()
        )
        struggling_count_result = await db.execute(
            select(func.count()).select_from(struggle_subq).where(
                struggle_subq.c.avg_mastery < STRUGGLE_THRESHOLD
            )
        )
        struggling_count = struggling_count_result.scalar() or 0

        summaries.append(
            {
                "id": cls.id,
                "name": cls.name,
                "student_count": enroll_count or 0,
                "active_today": active_today or 0,
                "average_mastery": float(avg_mastery or 0.0),
                "class_code": cls.class_code,
                "struggling_students": struggling_count,
            }
        )

    return summaries


async def get_class_overview(
    db: AsyncSession,
    class_id: str,
) -> dict | None:
    """Get class-wide analytics with per-student breakdowns.

    Returns a dict matching ``ClassOverviewResponse`` fields, or ``None``
    if the class does not exist.
    """
    # --- Fetch class ---
    cls_result = await db.execute(
        select(ClassModel).where(ClassModel.id == class_id)
    )
    cls: ClassModel | None = cls_result.scalar_one_or_none()
    if cls is None:
        return None

    # --- Fetch enrolled students ---
    enrollments_result = await db.execute(
        select(Enrollment)
        .options(selectinload(Enrollment.student))
        .where(Enrollment.class_id == class_id)
    )
    enrollments = enrollments_result.scalars().all()

    student_summaries = []
    all_student_masteries: list[float] = []
    all_struggled_topics: list[str] = []
    total_time_seconds = 0

    for enrollment in enrollments:
        student = enrollment.student
        student_id = student.id

        # Sims completed: count of sessions where is_completed is True
        sims_completed = await db.scalar(
            select(func.count(SessionModel.id)).where(
                SessionModel.student_id == student_id,
                SessionModel.is_completed == True,  # noqa: E712
            )
        )

        # Skill states for this student
        skill_states_result = await db.execute(
            select(SkillState).where(SkillState.student_id == student_id)
        )
        skill_states = skill_states_result.scalars().all()

        # Overall mastery: average of all skill probabilities
        if skill_states:
            overall_mastery = sum(
                float(s.probability) for s in skill_states
            ) / len(skill_states)
        else:
            overall_mastery = 0.0

        all_student_masteries.append(overall_mastery)

        # Struggling topics: skill names where probability < threshold
        struggling = [
            s.skill_id for s in skill_states
            if float(s.probability) < STRUGGLE_THRESHOLD
        ]
        all_struggled_topics.extend(struggling)

        # Total time spent by this student
        time_result = await db.scalar(
            select(
                func.coalesce(
                    func.sum(SessionModel.duration_seconds), 0
                )
            ).where(
                SessionModel.student_id == student_id,
            )
        )
        total_time_seconds += time_result or 0

        student_summaries.append(
            {
                "id": student_id,
                "name": student.display_name or student.username or student.email or "Unknown",
                "sims_completed": sims_completed or 0,
                "overall_mastery": round(overall_mastery, 4),
                "struggling_topics": struggling,
                "last_active": student.last_active_at,
            }
        )

    # Class averages
    class_average_mastery = (
        sum(all_student_masteries) / len(all_student_masteries)
        if all_student_masteries
        else 0.0
    )

    # Most struggled topics: find topics that appear most often as struggling
    topic_freq: dict[str, int] = {}
    for t in all_struggled_topics:
        topic_freq[t] = topic_freq.get(t, 0) + 1
    # Sort by frequency descending, take top 5
    most_struggled = sorted(topic_freq, key=topic_freq.get, reverse=True)[:5]

    total_time_hours = round(total_time_seconds / 3600, 2)

    return {
        "class_id": cls.id,
        "class_name": cls.name,
        "students": student_summaries,
        "class_average_mastery": round(class_average_mastery, 4),
        "most_struggled_topics": most_struggled,
        "total_time_hours": total_time_hours,
    }


async def get_teacher_insights(
    db: AsyncSession,
    teacher_id: str,
) -> list[dict]:
    """Generate rule-based insights & alerts for the teacher.

    Scans all classes belonging to *teacher_id* and produces alert items
    for:
    - Struggling students (average mastery below threshold)
    - Class trends (low average class mastery)
    - Milestones (students who just crossed above threshold)

    Returns a list of dicts matching ``AlertItem`` schema fields.
    """
    alerts: list[dict] = []

    # --- Fetch teacher's classes ---
    classes_result = await db.execute(
        select(ClassModel).where(ClassModel.teacher_id == teacher_id)
    )
    classes = classes_result.scalars().all()

    for cls in classes:
        # --- Per-class: find struggling students ---
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
                select(SkillState).where(
                    SkillState.student_id == student_id
                )
            )
            skill_states = skill_states_result.scalars().all()

            if skill_states:
                avg_mastery = sum(
                    float(s.probability) for s in skill_states
                ) / len(skill_states)
            else:
                avg_mastery = 0.0

            class_masteries.append(avg_mastery)

            if avg_mastery < STRUGGLE_THRESHOLD:
                # Find their most struggling skill
                worst_skill = min(
                    skill_states,
                    key=lambda s: float(s.probability),
                ) if skill_states else None

                alerts.append(
                    {
                        "type": "struggling_student",
                        "student_name": student.display_name
                        or student.username
                        or "Unknown",
                        "topic": worst_skill.skill_id if worst_skill else None,
                        "finding": (
                            f"Average mastery {avg_mastery:.0%} "
                            f"across {len(skill_states)} skills"
                        ),
                        "action": (
                            f"Review {student.display_name or student.username}'s "
                            f"work and consider one-on-one intervention"
                        ),
                    }
                )

        # --- Class-level trend alert ---
        if class_masteries:
            class_avg = sum(class_masteries) / len(class_masteries)
            if class_avg < STRUGGLE_THRESHOLD:
                alerts.append(
                    {
                        "type": "class_trend",
                        "student_name": None,
                        "topic": None,
                        "finding": (
                            f"Class '{cls.name}' has an average mastery "
                            f"of {class_avg:.0%} — below the {STRUGGLE_THRESHOLD:.0%} threshold"
                        ),
                        "action": (
                            f"Consider re-teaching core concepts or assigning "
                            f"remedial simulations to {cls.name}"
                        ),
                    }
                )

    # Limit to top 20 alerts to keep response manageable
    return alerts[:20]


async def assign_sim_to_class(
    db: AsyncSession,
    teacher_id: str,
    class_id: str,
    sim_slug: str,
    due_date: datetime | None = None,
    required: bool = True,
) -> dict | None:
    """Assign a sim to an entire class.

    Validates that:
    1. The teacher exists and has role='teacher'
    2. The class exists and belongs to the teacher
    3. The sim exists (looked up by slug)

    Returns a dict with assignment_id and status, or ``None`` if validation
    fails (caller should raise 404/403).
    """
    # --- Validate teacher ---
    teacher_result = await db.execute(
        select(User).where(User.id == teacher_id)
    )
    teacher = teacher_result.scalar_one_or_none()
    if teacher is None:
        logger.warning("Teacher %s not found", teacher_id)
        return None
    if teacher.role != "teacher":
        logger.warning("User %s is not a teacher (role=%s)", teacher_id, teacher.role)
        return None

    # --- Validate class & ownership ---
    cls_result = await db.execute(
        select(ClassModel).where(ClassModel.id == class_id)
    )
    cls = cls_result.scalar_one_or_none()
    if cls is None:
        logger.warning("Class %s not found", class_id)
        return None
    if cls.teacher_id != teacher_id:
        logger.warning(
            "Teacher %s does not own class %s", teacher_id, class_id
        )
        return None

    # --- Validate sim ---
    sim_result = await db.execute(
        select(Sim).where(Sim.slug == sim_slug)
    )
    sim = sim_result.scalar_one_or_none()
    if sim is None:
        logger.warning("Sim with slug '%s' not found", sim_slug)
        return None

    # --- Create assignment ---
    assignment = Assignment(
        teacher_id=teacher_id,
        class_id=class_id,
        sim_id=sim.id,
        title=f"{sim.title_en}",
        due_date=due_date,
        required=required,
    )
    db.add(assignment)
    await db.flush()

    # --- Log teacher action ---
    action = TeacherAction(
        teacher_id=teacher_id,
        class_id=class_id,
        action_type="assign_sim",
        target_id=assignment.id,
        extra_data=validate_extra_data_dict(
            {
                "sim_slug": sim_slug,
                "sim_title": sim.title_en,
                "required": required,
                "due_date": due_date.isoformat() if due_date else None,
            },
            ALLOWED_TEACHER_ACTION_KEYS,
            "TeacherAction.extra_data",
        ),
    )
    db.add(action)
    await db.flush()

    logger.info(
        "Assigned sim '%s' to class '%s' (assignment=%s)",
        sim_slug,
        cls.name,
        assignment.id,
    )

    return {
        "status": "ok",
        "assignment_id": assignment.id,
    }


async def get_session_replay(
    db: AsyncSession,
    teacher_id: str,
    session_id: str,
    limit: int = 500,
    after: int | None = None,
) -> dict | None:
    """Fetch session replay data — event timeline + session metadata.

    Returns a dict with ``session`` and ``events`` keys, or ``None`` if
    the session does not exist or has no associated student.

    The caller is responsible for verifying the teacher->student ownership
    before calling this function.
    """
    # --- Fetch session with relationships ---
    session_result = await db.execute(
        select(SessionModel)
        .options(selectinload(SessionModel.student), selectinload(SessionModel.sim))
        .where(SessionModel.id == session_id)
    )
    session: SessionModel | None = session_result.scalar_one_or_none()

    if session is None:
        return None

    # --- Build event query ---
    query = (
        select(Event)
        .where(Event.session_id == session_id)
        .order_by(Event.client_ts.asc(), Event.id.asc())
    )

    if after is not None:
        query = query.where(Event.id > after)

    query = query.limit(limit)

    events_result = await db.execute(query)
    events = events_result.scalars().all()

    # --- Build metadata ---
    student_name: str | None = None
    if session.student is not None:
        student_name = (
            session.student.display_name
            or session.student.username
            or session.student.email
        )

    sim_slug: str | None = None
    if session.sim is not None:
        sim_slug = session.sim.slug

    return {
        "session": {
            "session_id": session.id,
            "student_name": student_name,
            "sim_slug": sim_slug,
            "start_time": session.started_at,
            "end_time": session.ended_at,
            "duration_seconds": session.duration_seconds,
            "is_completed": session.is_completed,
        },
        "events": [
            {
                "event_id": e.id,
                "timestamp": e.client_ts,
                "event_type": e.event_type,
                "event_name": e.event_name,
                "event_data": e.event_value,
                "extra_data": e.extra_data or {},
            }
            for e in events
        ],
    }


async def list_teacher_feedback(
    db: AsyncSession,
    teacher_id: str,
    student_id: str | None = None,
    sim_slug: str | None = None,
    flagged_only: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List AI feedback given to students in the teacher's classes.

    Returns feedback entries for all students enrolled in any class owned
    by *teacher_id*, ordered by most recent first.
    Supports filtering by student_id, sim_slug, and flagged_only.
    """
    # --- Subquery: student IDs enrolled in this teacher's classes ---
    enrolled_student_ids = (
        select(Enrollment.student_id)
        .join(ClassModel, ClassModel.id == Enrollment.class_id)
        .where(ClassModel.teacher_id == teacher_id)
        .subquery()
    )

    query = (
        select(FeedbackLog)
        .where(FeedbackLog.student_id.in_(select(enrolled_student_ids.c.student_id)))
        .order_by(FeedbackLog.created_at.desc())
    )

    if student_id is not None:
        query = query.where(FeedbackLog.student_id == student_id)
    if sim_slug is not None:
        query = query.join(Sim, Sim.id == FeedbackLog.sim_id).where(Sim.slug == sim_slug)
    if flagged_only is True:
        query = query.where(FeedbackLog.is_flagged == True)  # noqa: E712

    # Clone for total count before applying limit/offset
    total_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(total_query) or 0

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    feedback_entries = result.scalars().all()

    # --- Fetch student & sim data for display names ---
    student_ids = {f.student_id for f in feedback_entries}
    sim_ids = {f.sim_id for f in feedback_entries if f.sim_id}

    students_map: dict[str, User] = {}
    if student_ids:
        students_result = await db.execute(
            select(User).where(User.id.in_(student_ids))
        )
        students_map = {s.id: s for s in students_result.scalars().all()}

    sims_map: dict[str, Sim] = {}
    if sim_ids:
        sims_result = await db.execute(
            select(Sim).where(Sim.id.in_(sim_ids))
        )
        sims_map = {s.id: s for s in sims_result.scalars().all()}

    items = []
    for fb in feedback_entries:
        student = students_map.get(fb.student_id)
        sim = sims_map.get(fb.sim_id) if fb.sim_id else None
        student_name = (
            student.display_name or student.username or student.email or "Unknown"
            if student
            else "Unknown"
        )
        items.append(
            {
                "feedback_id": fb.id,
                "student_name": student_name,
                "sim_slug": sim.slug if sim else None,
                "original_prompt": None,  # not stored in FeedbackLog; could be reconstructed
                "ai_response": fb.feedback_text,
                "hint_level": fb.feedback_type,
                "feedback_type": fb.feedback_type,
                "timestamp": fb.created_at,
                "is_flagged": bool(fb.is_flagged or False),
                "flag_reason": fb.flag_reason,
                "flag_note": fb.flag_note,
                "corrected_text": fb.corrected_text,
            }
        )

    return items, total


async def flag_feedback(
    db: AsyncSession,
    feedback_id: str,
    teacher_id: str,
    reason: str,
    note: str | None = None,
) -> dict | None:
    """Flag a feedback item. Returns updated item dict or None if not found."""
    result = await db.execute(
        select(FeedbackLog).where(FeedbackLog.id == feedback_id)
    )
    fb = result.scalar_one_or_none()
    if fb is None:
        return None

    fb.is_flagged = True
    fb.flagged_by = teacher_id
    fb.flag_reason = reason
    if note:
        fb.flag_note = note
    await db.flush()

    return {
        "status": "ok",
        "feedback_id": fb.id,
    }


async def correct_feedback(
    db: AsyncSession,
    feedback_id: str,
    corrected_text: str,
) -> dict | None:
    """Record a teacher's corrected version of the feedback text.
    Returns updated item dict or None if not found.
    """
    result = await db.execute(
        select(FeedbackLog).where(FeedbackLog.id == feedback_id)
    )
    fb = result.scalar_one_or_none()
    if fb is None:
        return None

    fb.corrected_text = corrected_text
    # Also mark as flagged so it shows up in review queues
    await db.flush()

    return {
        "status": "ok",
        "feedback_id": fb.id,
    }


async def get_mastery_heatmap(
    db: AsyncSession,
    class_id: str,
) -> dict | None:
    """Build a mastery heatmap dataset: all students × all skills.

    Queries all enrolled students in the class and their SkillState records.
    Applies BKT forgetting-curve decay and classifies each cell into a
    mastery level. Sorts students by overall mastery descending.

    Returns a dict matching ``MasteryHeatmapResponse`` fields, or ``None``
    if the class does not exist.
    """
    # ── Fetch class ────────────────────────────────────────────────
    cls_result = await db.execute(
        select(ClassModel).where(ClassModel.id == class_id)
    )
    cls: ClassModel | None = cls_result.scalar_one_or_none()
    if cls is None:
        return None

    # ── Fetch enrolled students with user data ─────────────────────
    enrollments_result = await db.execute(
        select(Enrollment)
        .options(selectinload(Enrollment.student))
        .where(Enrollment.class_id == class_id)
    )
    enrollments = enrollments_result.scalars().all()

    if not enrollments:
        return {
            "skills": [],
            "students": [],
            "class_average_mastery": 0.0,
            "student_count": 0,
            "skill_count": 0,
        }

    # ── Bulk fetch ALL skill states for all students in this class ─
    student_ids = [e.student_id for e in enrollments]
    skill_states_result = await db.execute(
        select(SkillState).where(SkillState.student_id.in_(student_ids))
    )
    all_skill_states = skill_states_result.scalars().all()

    # Build lookup: {student_id: {skill_id: SkillState}}
    states_by_student: dict[str, dict[str, SkillState]] = {}
    all_skill_ids: set[str] = set()
    for ss in all_skill_states:
        sid = ss.student_id
        skid = ss.skill_id
        if sid not in states_by_student:
            states_by_student[sid] = {}
        states_by_student[sid][skid] = ss
        all_skill_ids.add(skid)

    # Sort skill IDs for deterministic column order
    sorted_skill_ids = sorted(all_skill_ids)

    # Build skill metadata list
    now = datetime.now(timezone.utc)
    skills_list = [
        {"skill_id": skid, "display_name": skid, "category": None}
        for skid in sorted_skill_ids
    ]

    # ── Per-student data ───────────────────────────────────────────
    students_list: list[dict] = []
    overall_masteries: list[float] = []

    for enrollment in enrollments:
        student = enrollment.student
        sid = student.id
        student_states = states_by_student.get(sid, {})

        cells: dict[str, dict] = {}
        student_mastery_sum = 0.0
        skill_count = 0

        for skid in sorted_skill_ids:
            ss = student_states.get(skid)
            if ss is None:
                # Not attempted
                cells[skid] = {
                    "mastery_probability": 0.0,
                    "mastery_level": "not_attempted",
                    "total_attempts": 0,
                    "correct_attempts": 0,
                    "last_practiced": None,
                }
                continue

            prob = float(ss.probability)

            # Apply forgetting-curve decay
            if ss.last_practiced is not None:
                last_prac = ss.last_practiced
                if last_prac.tzinfo is None:
                    last_prac = last_prac.replace(tzinfo=timezone.utc)
                days_since = (now - last_prac).total_seconds() / 86400.0
                from app.services.bkt import apply_forgetting_curve

                prob = apply_forgetting_curve(prob, days_since)

            # Determine mastery level
            if prob < 0.15:
                level = "struggling"
            elif prob < 0.35:
                level = "introductory"
            elif prob < 0.70:
                level = "developing"
            elif prob < 0.90:
                level = "proficient"
            else:
                level = "mastered"

            cells[skid] = {
                "mastery_probability": round(prob, 4),
                "mastery_level": level,
                "total_attempts": ss.total_attempts or 0,
                "correct_attempts": ss.correct_attempts or 0,
                "last_practiced": ss.last_practiced,
            }

            student_mastery_sum += prob
            skill_count += 1

        overall_mastery = (
            round(student_mastery_sum / skill_count, 4) if skill_count > 0 else 0.0
        )
        overall_masteries.append(overall_mastery)

        students_list.append(
            {
                "student_id": sid,
                "student_name": (
                    student.display_name
                    or student.username
                    or student.email
                    or "Unknown"
                ),
                "overall_mastery": overall_mastery,
                "cells": cells,
            }
        )

    # Sort students by overall mastery descending
    students_list.sort(key=lambda s: s["overall_mastery"], reverse=True)

    class_average_mastery = (
        round(sum(overall_masteries) / len(overall_masteries), 4)
        if overall_masteries
        else 0.0
    )

    return {
        "skills": skills_list,
        "students": students_list,
        "class_average_mastery": class_average_mastery,
        "student_count": len(students_list),
        "skill_count": len(sorted_skill_ids),
    }
