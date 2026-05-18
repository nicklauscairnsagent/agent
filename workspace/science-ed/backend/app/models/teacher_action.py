import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, TIMESTAMP, func
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Numeric, Float, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TeacherAction(Base):
    __tablename__ = "teacher_actions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    teacher_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    class_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("classes.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    teacher = relationship("User", back_populates="teacher_actions", lazy="selectin")
    class_ = relationship("ClassModel", back_populates="teacher_actions", lazy="selectin")
