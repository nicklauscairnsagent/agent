import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, ForeignKey, TIMESTAMP, func
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Numeric, Float, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ClassModel(Base):
    __tablename__ = "classes"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    teacher_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
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

    # relationships
    teacher = relationship("User", back_populates="classes", lazy="selectin")
    enrollments = relationship("Enrollment", back_populates="class_", lazy="selectin")
    assignments = relationship("Assignment", back_populates="class_", lazy="selectin")
    teacher_actions = relationship("TeacherAction", back_populates="class_", lazy="selectin")
