import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, TIMESTAMP, Boolean, JSON, Integer, Numeric, Float, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # student, teacher, admin
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column("hashed_password", String, nullable=True)
    auth_provider: Mapped[str] = mapped_column(String, default="magic_link")
    auth_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, default=None
    )
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    # ── COPPA / Age verification fields ──────────────────────────────────
    birth_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Year of birth for age verification (COPPA §312.5)",
    )
    account_status: Mapped[str] = mapped_column(
        String, default="active",
        comment="'active' | 'pending_consent' | 'disabled' — COPPA compliance state",
    )
    parental_consent_id: Mapped[str | None] = mapped_column(
        String, nullable=True,
        comment="UUID of the parental consent record",
    )
    parental_consent_date: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
        comment="When parental consent was verified (COPPA §312.5)",
    )
    parental_consent_method: Mapped[str | None] = mapped_column(
        String, nullable=True,
        comment="'email' | 'video' | 'signed_form' — how consent was verified",
    )
    parent_verification_token: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True,
        comment="UUID token for parent/guardian to access student data (FERPA §99.10 / COPPA §312.6 B2)",
    )

    # --- Consent tracking (FERPA/COPPA compliance B4) ---
    consent_given: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Whether the user (or their parent) has given consent",
    )
    consent_date: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
        comment="When consent was given",
    )
    consent_type: Mapped[str | None] = mapped_column(
        String, nullable=True,
        comment="Type of consent: 'parental' (COPPA), 'student' (FERPA), 'explicit'",
    )
    consent_scope: Mapped[str | None] = mapped_column(
        String, nullable=True,
        comment="JSON list of consent scopes, e.g. '\"[\"tracking\",\"feedback\",\"export\"]\"'",
    )
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
        comment="When consent was withdrawn (null = active)",
    )

    # relationships
    sessions = relationship("SessionModel", back_populates="student", lazy="selectin")
    events = relationship("Event", back_populates="student", lazy="selectin")
    task_results = relationship("TaskResult", back_populates="student", lazy="selectin")
    skill_states = relationship("SkillState", back_populates="student", lazy="selectin")
    feedback_logs = relationship(
        "FeedbackLog", back_populates="student", lazy="selectin",
        foreign_keys="FeedbackLog.student_id",
    )
    classes = relationship("ClassModel", back_populates="teacher", lazy="selectin")
    assignments = relationship("Assignment", back_populates="teacher", lazy="selectin")
    teacher_actions = relationship("TeacherAction", back_populates="teacher", lazy="selectin")
    enrollments = relationship("Enrollment", back_populates="student", lazy="selectin")
