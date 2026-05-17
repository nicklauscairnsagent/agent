"""Achievement router — badge catalog, student unlocks, streak, and notifications.

All endpoints require student authentication via Bearer JWT.

Endpoints
---------
- GET  /api/v1/achievements                   — full badge catalog
- GET  /api/v1/achievements/student            — student's unlocked badges + streak
- GET  /api/v1/achievements/progress           — progress toward each badge
- POST /api/v1/achievements/check              — trigger unlock check (called by backend)
- GET  /api/v1/achievements/notifications       — pending unlock toasts
- POST /api/v1/achievements/notifications/dismiss — mark notifications as seen
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.achievement import (
    AchievementCatalogResponse,
    AchievementCheckResponse,
    AchievementDefinitionResponse,
    AchievementProgressItem,
    AchievementProgressResponse,
    DismissNotificationResponse,
    StreakInfoResponse,
    StudentAchievementDetail,
    StudentAchievementsResponse,
    UnlockNotificationResponse,
)
from app.services.achievements import (
    check_and_unlock_achievements,
    dismiss_notifications,
    get_achievement_catalog,
    get_achievement_progress,
    get_pending_notifications,
    get_student_achievements,
    update_streak,
)
from app.services.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/achievements", tags=["achievements"])


# ── Catalog ───────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=AchievementCatalogResponse,
    summary="List all available achievements",
)
async def list_achievements(
    db: AsyncSession = Depends(get_db),
) -> AchievementCatalogResponse:
    """Return the full badge catalog — all achievement definitions.

    Does **not** require authentication since it's metadata visible to
    any user (including anonymous).
    """
    catalog = await get_achievement_catalog(db)
    return AchievementCatalogResponse(
        achievements=[
            AchievementDefinitionResponse.model_validate(ach)
            for ach in catalog
        ]
    )


# ── Student Achievements ──────────────────────────────────────────────────────


@router.get(
    "/student",
    response_model=StudentAchievementsResponse,
    summary="Get authenticated student's unlocked badges and streak",
)
async def student_achievements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StudentAchievementsResponse:
    """Return all achievements the authenticated student has unlocked,
    along with their current streak info.
    """
    unlocked = await get_student_achievements(db, current_user.id)
    details = []
    for sa in unlocked:
        if sa.achievement:
            details.append(
                StudentAchievementDetail(
                    achievement=AchievementDefinitionResponse.model_validate(
                        sa.achievement
                    ),
                    unlocked_at=sa.unlocked_at,
                    context_data=sa.context_data,
                )
            )

    return StudentAchievementsResponse(
        achievements=details,
        streak=StreakInfoResponse(
            current_streak=current_user.streak_count,
            longest_streak=current_user.streak_count,
            last_active_date=(
                current_user.last_streak_date
                if isinstance(current_user.last_streak_date, date)
                else (
                    current_user.last_streak_date
                    if current_user.last_streak_date
                    else None
                )
            ),
        ),
    )


# ── Progress ──────────────────────────────────────────────────────────────────


@router.get(
    "/progress",
    response_model=AchievementProgressResponse,
    summary="Get progress toward each achievement",
)
async def achievement_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AchievementProgressResponse:
    """Return progress (0.0–1.0) for each achievement, including
    unlocked status and a human-readable progress string.
    """
    catalog = await get_achievement_catalog(db)
    items_data = await get_achievement_progress(db, current_user.id)
    items = [
        AchievementProgressItem(
            achievement=AchievementDefinitionResponse.model_validate(item["achievement"]),
            unlocked=item["unlocked"],
            progress=item["progress"],
            progress_text=item["progress_text"],
        )
        for item in items_data
    ]
    unlocked_count = sum(1 for i in items if i.unlocked)
    return AchievementProgressResponse(
        items=items,
        total_completed=unlocked_count,
        total_available=len(catalog),
    )


# ── Check / Unlock ────────────────────────────────────────────────────────────


@router.post(
    "/check",
    response_model=AchievementCheckResponse,
    summary="Check for newly unlocked achievements (called on action completion)",
)
async def check_achievements(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AchievementCheckResponse:
    """Check all achievement criteria and unlock any new ones.

    This endpoint should be called by the backend (or by the student
    dashboard) after completing a session, submitting a task, or any
    other action that could trigger an achievement.

    Returns newly unlocked badges and current streak info.
    """
    # 1. Update streak
    streak_info = await update_streak(db, current_user.id)

    # 2. Check for time-based badge eligibility
    now = datetime.now(timezone.utc)
    hour = now.hour
    context = {
        "action": "check",
        "is_night_owl_hour": hour >= 22 or hour < 5,
        "is_early_bird_hour": 5 <= hour < 8,
    }

    # 3. Check and unlock achievements
    newly_unlocked = await check_and_unlock_achievements(
        db, current_user.id, context=context
    )

    # 4. Build response
    completed_count = 0
    details = []
    for sa in newly_unlocked:
        await db.refresh(sa, ["achievement"])
        if sa.achievement:
            details.append(
                StudentAchievementDetail(
                    achievement=AchievementDefinitionResponse.model_validate(
                        sa.achievement
                    ),
                    unlocked_at=sa.unlocked_at,
                    context_data=sa.context_data,
                )
            )

    # Count total unlocked
    all_unlocked = await get_student_achievements(db, current_user.id)
    completed_count = len(all_unlocked)

    return AchievementCheckResponse(
        newly_unlocked=details,
        streak_info=StreakInfoResponse(
            current_streak=streak_info["current_streak"],
            longest_streak=streak_info["longest_streak"],
            last_active_date=streak_info["last_active_date"],
        ),
        completion_count=completed_count,
    )


# ── Notifications (toast system) ──────────────────────────────────────────────


@router.get(
    "/notifications",
    response_model=UnlockNotificationResponse,
    summary="Get pending achievement unlock notifications",
)
async def pending_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnlockNotificationResponse:
    """Return achievements that were unlocked but not yet shown to the
    student (e.g. as a toast notification).
    """
    pending = await get_pending_notifications(db, current_user.id)
    details = []
    for sa in pending:
        if sa.achievement:
            details.append(
                StudentAchievementDetail(
                    achievement=AchievementDefinitionResponse.model_validate(
                        sa.achievement
                    ),
                    unlocked_at=sa.unlocked_at,
                    context_data=sa.context_data,
                )
            )
    return UnlockNotificationResponse(unlocks=details)


@router.post(
    "/notifications/dismiss",
    response_model=DismissNotificationResponse,
    summary="Dismiss pending achievement notifications",
)
async def dismiss_achievement_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DismissNotificationResponse:
    """Mark all pending achievement notifications as seen."""
    dismissed = await dismiss_notifications(db, current_user.id)
    return DismissNotificationResponse(dismissed=dismissed)
