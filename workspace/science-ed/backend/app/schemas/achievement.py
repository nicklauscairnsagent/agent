"""Achievement schemas — badge definitions, student unlocks, streak info.

All models use ``from_attributes=True`` for ORM integration and
``extra=\"forbid\"`` for request bodies to reject unknown fields.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Achievement Definition ────────────────────────────────────────────────────


class AchievementDefinitionResponse(BaseModel):
    """A single badge type from the master catalog."""

    code: str
    display_name_en: str
    display_name_es: str | None = None
    description_en: str
    description_es: str | None = None
    icon_name: str
    category: str  # milestone, streak, mastery, special, time_based
    criteria_type: str
    criteria_value: dict = Field(default_factory=dict)
    sort_order: int = 0
    is_secret: bool = False

    model_config = ConfigDict(from_attributes=True)


# ── Student Achievement ───────────────────────────────────────────────────────


class StudentAchievementResponse(BaseModel):
    """One unlocked achievement for a student."""

    achievement_code: str
    unlocked_at: datetime
    context_data: dict | None = None
    notified: bool = False

    model_config = ConfigDict(from_attributes=True)


class StudentAchievementDetail(BaseModel):
    """Full achievement detail for the student dashboard."""

    achievement: AchievementDefinitionResponse
    unlocked_at: datetime | None = None
    context_data: dict | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Streak Info ───────────────────────────────────────────────────────────────


class StreakInfoResponse(BaseModel):
    """Current streak state for the authenticated student."""

    current_streak: int = 0
    longest_streak: int = 0
    last_active_date: date | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Endpoint Response Types ───────────────────────────────────────────────────


class AchievementCatalogResponse(BaseModel):
    """Response for GET /achievements — full badge catalog."""

    achievements: list[AchievementDefinitionResponse]

    model_config = ConfigDict(from_attributes=True)


class StudentAchievementsResponse(BaseModel):
    """Response for GET /achievements/student — student's unlocked badges."""

    achievements: list[StudentAchievementDetail]
    streak: StreakInfoResponse

    model_config = ConfigDict(from_attributes=True)


class AchievementCheckResponse(BaseModel):
    """Response for POST /achievements/check — newly unlocked badges."""

    newly_unlocked: list[StudentAchievementDetail] = Field(
        default_factory=list,
        description="Achievements unlocked by this action",
    )
    streak_info: StreakInfoResponse
    completion_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class AchievementProgressItem(BaseModel):
    """Progress toward a specific achievement."""

    achievement: AchievementDefinitionResponse
    unlocked: bool
    progress: float = 0.0  # 0.0–1.0
    progress_text: str = ""  # e.g. "7/10 simulations"

    model_config = ConfigDict(from_attributes=True)


class AchievementProgressResponse(BaseModel):
    """Response for GET /achievements/progress — progress toward all badges."""

    items: list[AchievementProgressItem]
    total_completed: int
    total_available: int

    model_config = ConfigDict(from_attributes=True)


class UnlockNotificationResponse(BaseModel):
    """Response for GET /achievements/notifications — pending unlock toasts."""

    unlocks: list[StudentAchievementDetail]

    model_config = ConfigDict(from_attributes=True)


class DismissNotificationResponse(BaseModel):
    """Response for POST /achievements/notifications/dismiss."""

    dismissed: int

    model_config = ConfigDict(from_attributes=True)
