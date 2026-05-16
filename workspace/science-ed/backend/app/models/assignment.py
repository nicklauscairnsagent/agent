import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, ForeignKey, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Assignment(Base):
    __tablename__ = "assignments"

    __table_args__ = (
        UniqueConstraint("class_id", "sim_id", "due_date", name="uq_assignment_class_sim_due"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    sim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sims.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    teacher = relationship("User", back_populates="assignments", lazy="selectin")
    class_ = relationship("ClassModel", back_populates="assignments", lazy="selectin")
    sim = relationship("Sim", back_populates="assignments", lazy="selectin")
