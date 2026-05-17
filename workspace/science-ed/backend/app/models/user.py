import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, TIMESTAMP, Boolean, Integer, func, text
from sqlalchemy.types import Uuid
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # student, teacher, admin
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String, default="magic_link")
    auth_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # --- Auth hardening ---
    login_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    # Consent tracking (Finding 1.1 — compliance)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_date: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    consent_type: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    data_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Privacy: monitoring opt-out (IEP/504 accommodation)
    monitoring_opt_out: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    # relationships
    sessions = relationship("SessionModel", back_populates="student", lazy="selectin")
    events = relationship("Event", back_populates="student", lazy="selectin")
    task_results = relationship("TaskResult", back_populates="student", lazy="selectin")
    skill_states = relationship("SkillState", back_populates="student", lazy="selectin")
    feedback_logs = relationship("FeedbackLog", back_populates="student", lazy="selectin")
    classes = relationship("ClassModel", back_populates="teacher", lazy="selectin")
    assignments = relationship("Assignment", back_populates="teacher", lazy="selectin")
    teacher_actions = relationship("TeacherAction", back_populates="teacher", lazy="selectin")
    enrollments = relationship("Enrollment", back_populates="student", lazy="selectin")
