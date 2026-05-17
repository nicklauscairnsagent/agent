"""Achievement service — badge unlock logic, streak tracking, progress queries.

All functions expect to be called inside a transaction (the caller's
``get_db`` dependency handles commit/rollback).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import SessionModel, Sim, Skill, SkillState, TaskResult, User
from app.models.achievement import AchievementDefinition, StudentAchievement

logger = logging.getLogger(__name__)


# ── Catalog ───────────────────────────────────────────────────────────────────


async def get_achievement_catalog(
    db: AsyncSession,
) -> list[AchievementDefinition]:
    """Return all achievement definitions, ordered by sort_order."""
    result = await db.execute(
        select(AchievementDefinition).order_by(AchievementDefinition.sort_order)
    )
    return list(result.scalars().all())


# ── Student Unlocks ───────────────────────────────────────────────────────────


async def get_student_achievements(
    db: AsyncSession,
    student_id: UUID,
) -> list[StudentAchievement]:
    """Return all achievements a student has unlocked."""
    result = await db.execute(
        select(StudentAchievement)
        .where(StudentAchievement.student_id == student_id)
        .options(selectinload(StudentAchievement.achievement))
    )
    return list(result.scalars().all())


async def get_student_achievement_codes(
    db: AsyncSession,
    student_id: UUID,
) -> set[str]:
    """Return the set of achievement codes the student has already unlocked."""
    result = await db.execute(
        select(StudentAchievement.achievement_code).where(
            StudentAchievement.student_id == student_id
        )
    )
    return {row[0] for row in result.all()}


# ── Streak Tracking ───────────────────────────────────────────────────────────


async def update_streak(
    db: AsyncSession,
    student_id: UUID,
    *,
    activity_date: date | None = None,
) -> dict:
    """Update the student's consecutive-day streak.

    Called whenever the student completes an action (session end, task
    submission, etc.).  Returns the updated streak info dict::

        {"current_streak": int, "longest_streak": int,
         "last_active_date": date | None}

    Streak logic:
    - If *activity_date* is the same as ``last_streak_date`` → no change.
    - If *activity_date* is the day after ``last_streak_date`` → increment.
    - If *activity_date* is >1 day after → reset to 1.
    - If ``last_streak_date`` is ``None`` → start at 1.
    """
    if activity_date is None:
        activity_date = date.today()

    result = await db.execute(select(User).where(User.id == student_id))
    user = result.scalar_one_or_none()
    if user is None:
        return {"current_streak": 0, "longest_streak": 0, "last_active_date": None}

    last_date = user.last_streak_date

    if last_date == activity_date:
        # Same day — no change to streak count
        pass
    elif last_date is None:
        user.streak_count = 1
    elif (activity_date - last_date).days == 1:
        user.streak_count += 1
    else:
        user.streak_count = 1  # streak broken

    user.last_streak_date = activity_date
    await db.flush()

    return {
        "current_streak": user.streak_count,
        "longest_streak": user.streak_count,  # TODO: track historical longest
        "last_active_date": user.last_streak_date,
    }


# ── Completion Count Helpers ──────────────────────────────────────────────────


async def get_completed_sim_count(
    db: AsyncSession,
    student_id: UUID,
) -> int:
    """Return total count of distinct sims the student has completed."""
    result = await db.execute(
        select(func.count(func.distinct(SessionModel.sim_id))).where(
            SessionModel.student_id == student_id,
            SessionModel.is_completed.is_(True),
            SessionModel.sim_id.isnot(None),
        )
    )
    return result.scalar() or 0


async def get_mastered_categories(
    db: AsyncSession,
    student_id: UUID,
) -> list[str]:
    """Return category slugs where the student has mastered ALL sims.

    "Mastered" means the student has at least one completed session for
    every sim in that category.
    """
    # Get all sims grouped by category
    sim_result = await db.execute(
        select(Sim.category_slug, func.count(Sim.id).label("total")).group_by(
            Sim.category_slug
        )
    )
    category_totals = {row.category_slug: row.total for row in sim_result.all()}
    if not category_totals:
        return []

    # Get completed sims per category for this student
    completed_result = await db.execute(
        select(
            Sim.category_slug,
            func.count(func.distinct(SessionModel.sim_id)).label("completed"),
        )
        .join(SessionModel, SessionModel.sim_id == Sim.id)
        .where(
            SessionModel.student_id == student_id,
            SessionModel.is_completed.is_(True),
        )
        .group_by(Sim.category_slug)
    )
    completed_map = {row.category_slug: row.completed for row in completed_result.all()}

    mastered = []
    for slug, total in category_totals.items():
        if completed_map.get(slug, 0) >= total > 0:
            mastered.append(slug)
    return mastered


async def get_skill_categories_mastered(
    db: AsyncSession,
    student_id: UUID,
) -> list[str]:
    """Return skill categories where ALL skills are at mastery level (BKT >= 0.95)."""
    result = await db.execute(
        select(Skill.category, func.count(Skill.id).label("total")).group_by(
            Skill.category
        )
    )
    category_totals = {row.category: row.total for row in result.all()}
    if not category_totals:
        return []

    mastered_result = await db.execute(
        select(SkillState.skill_id)
        .join(Skill, Skill.id == SkillState.skill_id)
        .where(
            SkillState.student_id == student_id,
            SkillState.probability >= 0.95,
        )
    )
    mastered_skills = {row[0] for row in mastered_result.all()}

    # Group mastered skills by category
    cat_result = await db.execute(
        select(Skill.id, Skill.category).where(Skill.id.in_(mastered_skills))
    )
    mastered_by_cat: dict[str, set[str]] = {}
    for row in cat_result.all():
        mastered_by_cat.setdefault(row.category, set()).add(row.id)

    return [
        cat
        for cat, total in category_totals.items()
        if len(mastered_by_cat.get(cat, set())) >= total > 0
    ]


async def get_task_high_score(
    db: AsyncSession,
    student_id: UUID,
) -> float:
    """Return the highest score percentage the student has achieved on any task."""
    result = await db.execute(
        select(TaskResult)
        .where(
            TaskResult.student_id == student_id,
            TaskResult.score.isnot(None),
            TaskResult.total_count > 0,
        )
        .order_by(TaskResult.score.desc())
        .limit(1)
    )
    tr = result.scalar_one_or_none()
    if tr is None:
        return 0.0
    return float(tr.score)


# ── Achievement Unlock ────────────────────────────────────────────────────────


async def check_and_unlock_achievements(
    db: AsyncSession,
    student_id: UUID,
    *,
    context: dict | None = None,
) -> list[StudentAchievement]:
    """Check ALL achievements for a student and unlock any new ones.

    **context** may carry hints about what triggered the check::

        {
            "action": "session_end" | "task_submit" | "streak_update",
            "sim_slug": str | None,
            "task_score": float | None,
            "is_night_owl_hour": bool,    # 10 PM – 5 AM
            "is_early_bird_hour": bool,   # 5 AM – 8 AM
        }

    Returns a list of newly-unlocked StudentAchievement rows.  The caller
    should use this list to trigger notifications.
    """
    already = await get_student_achievement_codes(db, student_id)
    catalog = await get_achievement_catalog(db)
    completed_count = await get_completed_sim_count(db, student_id)
    newly_unlocked: list[StudentAchievement] = []

    # Pre-compute expensive checks only if needed
    mastered_categories: list[str] | None = None
    task_high_score: float | None = None

    for ach_def in catalog:
        if ach_def.code in already:
            continue

        unlocked = False
        context_data: dict | None = None

        if ach_def.criteria_type == "sim_count":
            threshold = ach_def.criteria_value.get("count", 0)
            if completed_count >= threshold:
                unlocked = True
                context_data = {
                    "completed_count": completed_count,
                    "threshold": threshold,
                }

        elif ach_def.criteria_type == "streak_days":
            # Re-read current streak from DB
            streak_res = await db.execute(
                select(User.streak_count).where(User.id == student_id)
            )
            current_streak = streak_res.scalar() or 0
            threshold = ach_def.criteria_value.get("days", 0)
            if current_streak >= threshold:
                unlocked = True
                context_data = {
                    "streak_days": current_streak,
                    "threshold": threshold,
                }

        elif ach_def.criteria_type == "category_mastery":
            if mastered_categories is None:
                mastered_categories = await get_mastered_categories(db, student_id)
            if mastered_categories:
                unlocked = True
                context_data = {"mastered_categories": mastered_categories}

        elif ach_def.criteria_type == "task_score":
            threshold = ach_def.criteria_value.get("score", 90)
            if task_high_score is None:
                task_high_score = await get_task_high_score(db, student_id)
            if task_high_score >= threshold:
                unlocked = True
                context_data = {"high_score": task_high_score, "threshold": threshold}

        elif ach_def.criteria_type == "time_based":
            # Time-based badges checked via context hint
            label = ach_def.criteria_value.get("label", "")
            if context:
                hour_hint = context.get(f"is_{label}_hour", False)
                if hour_hint:
                    unlocked = True
                    context_data = {
                        "trigger": label,
                        "sim_slug": context.get("sim_slug"),
                    }

        if unlocked:
            student_ach = StudentAchievement(
                student_id=student_id,
                achievement_code=ach_def.code,
                context_data=context_data or {},
                notified=False,
            )
            db.add(student_ach)
            newly_unlocked.append(student_ach)

    if newly_unlocked:
        await db.flush()
        # Re-load with relationship for complete response
        for sa in newly_unlocked:
            await db.refresh(sa, ["achievement"])

    return newly_unlocked


# ── Progress Queries ──────────────────────────────────────────────────────────


async def get_achievement_progress(
    db: AsyncSession,
    student_id: UUID,
) -> list[dict]:
    """Return progress (0.0–1.0) toward each achievement for this student."""
    catalog = await get_achievement_catalog(db)
    already = await get_student_achievement_codes(db, student_id)
    completed_count = await get_completed_sim_count(db, student_id)
    streak_res = await db.execute(
        select(User.streak_count).where(User.id == student_id)
    )
    current_streak = streak_res.scalar() or 0
    task_high_score = await get_task_high_score(db, student_id)

    items = []
    for ach_def in catalog:
        unlocked = ach_def.code in already
        progress = 1.0 if unlocked else 0.0
        progress_text = ""

        if ach_def.criteria_type == "sim_count":
            threshold = ach_def.criteria_value.get("count", 0)
            progress = min(completed_count / threshold, 1.0) if threshold > 0 else 0.0
            progress_text = f"{completed_count}/{threshold} simulations"

        elif ach_def.criteria_type == "streak_days":
            threshold = ach_def.criteria_value.get("days", 0)
            progress = (
                min(current_streak / threshold, 1.0) if threshold > 0 else 0.0
            )
            progress_text = f"{current_streak}/{threshold} days"

        elif ach_def.criteria_type == "task_score":
            threshold = ach_def.criteria_value.get("score", 90)
            progress = min(task_high_score / threshold, 1.0) if threshold > 0 else 0.0
            progress_text = f"{task_high_score:.0f}% / {threshold}%"

        elif ach_def.criteria_type == "category_mastery":
            mastered = await get_mastered_categories(db, student_id)
            progress = 1.0 if mastered else 0.0
            progress_text = (
                "Mastered categories" if mastered else "No categories mastered yet"
            )

        elif ach_def.criteria_type == "time_based":
            progress = 1.0 if unlocked else 0.0
            progress_text = (
                "Unlocked!" if unlocked else "Complete a sim in the right time window"
            )

        items.append(
            {
                "achievement": ach_def,
                "unlocked": unlocked,
                "progress": round(progress, 4),
                "progress_text": progress_text,
            }
        )

    return items


# ── Notifications ─────────────────────────────────────────────────────────────


async def get_pending_notifications(
    db: AsyncSession,
    student_id: UUID,
) -> list[StudentAchievement]:
    """Return achievements that have been unlocked but not yet notified."""
    result = await db.execute(
        select(StudentAchievement)
        .where(
            StudentAchievement.student_id == student_id,
            StudentAchievement.notified.is_(False),
        )
        .options(selectinload(StudentAchievement.achievement))
    )
    return list(result.scalars().all())


async def dismiss_notifications(
    db: AsyncSession,
    student_id: UUID,
) -> int:
    """Mark all pending notifications as notified. Returns count dismissed."""
    result = await db.execute(
        select(StudentAchievement).where(
            StudentAchievement.student_id == student_id,
            StudentAchievement.notified.is_(False),
        )
    )
    rows = list(result.scalars().all())
    for row in rows:
        row.notified = True
    await db.flush()
    return len(rows)
