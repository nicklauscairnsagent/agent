import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, TIMESTAMP, Boolean, func
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
    auth_provider: Mapped[str] = mapped_column(String, default="magic_link")
    auth_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
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
