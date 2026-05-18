import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, TIMESTAMP, UniqueConstraint, func
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Numeric, Float, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Enrollment(Base):
    __tablename__ = "enrollments"

    __table_args__ = (
        UniqueConstraint("class_id", "student_id", name="uq_enrollment_class_student"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    class_id: Mapped[str] = mapped_column(
        String, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    # relationships
    class_ = relationship("ClassModel", back_populates="enrollments", lazy="selectin")
    student = relationship("User", back_populates="enrollments", lazy="selectin")
