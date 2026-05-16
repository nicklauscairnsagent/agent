import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, TIMESTAMP, func
from sqlalchemy.types import Uuid
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TeacherAction(Base):
    __tablename__ = "teacher_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    teacher = relationship("User", back_populates="teacher_actions", lazy="selectin")
    class_ = relationship("ClassModel", back_populates="teacher_actions", lazy="selectin")
