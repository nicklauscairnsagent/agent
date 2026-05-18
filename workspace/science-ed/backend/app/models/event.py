import uuid
from datetime import datetime

from sqlalchemy import String, Text, BigInteger, ForeignKey, TIMESTAMP, func
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Numeric, Float, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id"), nullable=False
    )
    student_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id"), nullable=True
    )
    sim_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sims.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_name: Mapped[str | None] = mapped_column(String, nullable=True)
    event_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    client_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    server_ts: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    # relationships
    session = relationship("SessionModel", back_populates="events", lazy="selectin")
    student = relationship("User", back_populates="events", lazy="selectin")
    sim = relationship("Sim", back_populates="events", lazy="selectin")
    feedback_logs = relationship("FeedbackLog", back_populates="trigger_event", lazy="selectin")
