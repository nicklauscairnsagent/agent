import uuid
from datetime import datetime

from sqlalchemy import Integer, Numeric, ForeignKey, TIMESTAMP, String, UniqueConstraint, func
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SkillState(Base):
    __tablename__ = "skill_state"

    __table_args__ = (
        UniqueConstraint("student_id", "skill_id", name="uq_skill_state_student_skill"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[str] = mapped_column(String, nullable=False)
    probability: Mapped[float] = mapped_column(Numeric(5, 4), default=0.1)
    learning_rate: Mapped[float] = mapped_column(Numeric(5, 4), default=0.3)
    guess_rate: Mapped[float] = mapped_column(Numeric(5, 4), default=0.2)
    slip_rate: Mapped[float] = mapped_column(Numeric(5, 4), default=0.1)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_practiced: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    student = relationship("User", back_populates="skill_states", lazy="selectin", passive_deletes=True)
