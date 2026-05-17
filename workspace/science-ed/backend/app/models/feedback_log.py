import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, BigInteger, Boolean, ForeignKey, TIMESTAMP, func
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FeedbackLog(Base):
    __tablename__ = "feedback_log"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    sim_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sims.id"), nullable=True
    )
    event_trigger: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id"), nullable=True
    )
    feedback_type: Mapped[str] = mapped_column(String, nullable=False)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, default="llm")
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    was_helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    was_dismissed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # relationships
    session = relationship("SessionModel", back_populates="feedback_logs", lazy="selectin", passive_deletes=True)
    student = relationship("User", back_populates="feedback_logs", lazy="selectin", passive_deletes=True)
    sim = relationship("Sim", back_populates="feedback_logs", lazy="selectin")
    trigger_event = relationship("Event", back_populates="feedback_logs", lazy="selectin")
