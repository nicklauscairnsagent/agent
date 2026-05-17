"""Achievement models — badge definitions and student unlock records.

Two tables:

1. ``AchievementDefinition`` — the master catalog of badges (Explorer,
   Scholar, Scientist, Specialist, Streak badges, Perfectionist, etc.)
   loaded at startup or via a seed migration.

2. ``StudentAchievement`` — records which students have unlocked which
   achievements, with the date and context (e.g. the sim slug that
   triggered it).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from .base import Base


class AchievementDefinition(Base):
    """Master catalog entry for one achievement/badge type.

    These rows are seeded by the migration and should rarely change.
    New achievement types can be added by inserting new rows.
    """

    __tablename__ = "achievement_definitions"

    code: Mapped[str] = mapped_column(
        String, primary_key=True
    )  # e.g. "explorer", "scholar", "streak_7"
    display_name_en: Mapped[str] = mapped_column(String, nullable=False)
    display_name_es: Mapped[str | None] = mapped_column(String, nullable=True)
    description_en: Mapped[str] = mapped_column(Text, nullable=False)
    description_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_name: Mapped[str] = mapped_column(
        String, nullable=False
    )  # CSS class or icon identifier
    category: Mapped[str] = mapped_column(
        String, nullable=False
    )  # milestone, streak, mastery, special, time_based
    criteria_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # sim_count, streak_days, task_score, category_mastery, time_based, any_timed
    criteria_value: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # e.g. {"count": 10} or {"score": 90, "category_slug": "physics"}
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # relationships
    unlocks = relationship(
        "StudentAchievement", back_populates="achievement", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<AchievementDefinition {self.code}: {self.display_name_en}>"


class StudentAchievement(Base):
    """Record of a student unlocking a specific achievement."""

    __tablename__ = "student_achievements"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    achievement_code: Mapped[str] = mapped_column(
        String,
        ForeignKey("achievement_definitions.code", ondelete="CASCADE"),
        nullable=False,
    )
    unlocked_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    context_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # e.g. {"sim_slug": "pendulum", "score": 95, "streak_days": 7}
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether the student has been notified (toast shown)

    # relationships
    student = relationship(
        "User", back_populates="achievements", lazy="selectin", passive_deletes=True
    )
    achievement = relationship(
        "AchievementDefinition", back_populates="unlocks", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<StudentAchievement student={self.student_id} "
            f"achievement={self.achievement_code}>"
        )
