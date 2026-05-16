import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Numeric, ForeignKey, TIMESTAMP, func, JSON
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class TaskResult(Base):
    __tablename__ = "task_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    sim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sims.id"), nullable=False
    )
    task_slug: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    answers: Mapped[dict] = mapped_column(JSON, nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ngss_targets: Mapped[list] = mapped_column(JSON, default=list)
    seps: Mapped[list] = mapped_column(JSON, default=list)
    dcis: Mapped[list] = mapped_column(JSON, default=list)
    cccs: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # relationships
    session = relationship("SessionModel", back_populates="task_results", lazy="selectin")
    student = relationship("User", back_populates="task_results", lazy="selectin")
    sim = relationship("Sim", back_populates="task_results", lazy="selectin")
