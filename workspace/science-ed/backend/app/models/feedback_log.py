import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, BigInteger, Boolean, ForeignKey, TIMESTAMP, func
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Numeric, Float, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FeedbackLog(Base):
    __tablename__ = "feedback_log"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id"), nullable=False
    )
    student_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    sim_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sims.id"), nullable=True
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

    # --- Teacher feedback review / flagging ---
    is_flagged: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    flagged_by: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    flag_reason: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 'incorrect', 'misleading', 'inappropriate', 'other'
    flag_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    session = relationship("SessionModel", back_populates="feedback_logs", lazy="selectin")
    student = relationship(
        "User", back_populates="feedback_logs", lazy="selectin",
        foreign_keys="FeedbackLog.student_id",
    )
    sim = relationship("Sim", back_populates="feedback_logs", lazy="selectin")
    trigger_event = relationship("Event", back_populates="feedback_logs", lazy="selectin")
    flagger = relationship(
        "User", lazy="selectin",
        foreign_keys="FeedbackLog.flagged_by",
    )
