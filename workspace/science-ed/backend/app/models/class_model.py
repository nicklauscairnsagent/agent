import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer, ForeignKey, TIMESTAMP, func, text
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ClassModel(Base):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    grade_level: Mapped[str | None] = mapped_column(String, nullable=True)
    class_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    school_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Privacy / Monitoring Consent Toggles (§9.3) ──────────────────
    monitoring_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    enable_live_monitoring: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    enable_analytics: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    enable_frustration_detection: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    retention_days_replays: Mapped[int] = mapped_column(
        Integer, default=30, server_default=text("30")
    )
    retention_days_flags: Mapped[int] = mapped_column(
        Integer, default=90, server_default=text("90")
    )
    retention_days_heatmaps: Mapped[int] = mapped_column(
        Integer, default=365, server_default=text("365")
    )
    parent_access_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    # relationships
    teacher = relationship("User", back_populates="classes", lazy="selectin", passive_deletes=True)
    enrollments = relationship("Enrollment", back_populates="class_", lazy="selectin")
    assignments = relationship("Assignment", back_populates="class_", lazy="selectin")
    teacher_actions = relationship("TeacherAction", back_populates="class_", lazy="selectin")
