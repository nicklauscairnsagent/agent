import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, TIMESTAMP, Boolean, Integer, func, JSON
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Sim(Base):
    __tablename__ = "sims"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title_en: Mapped[str] = mapped_column(String, nullable=False)
    title_es: Mapped[str | None] = mapped_column(String, nullable=True)
    category_slug: Mapped[str] = mapped_column(String, nullable=False)
    category_en: Mapped[str] = mapped_column(String, nullable=False)
    category_es: Mapped[str | None] = mapped_column(String, nullable=True)
    ngss_standards: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_en: Mapped[str] = mapped_column(String, nullable=False)
    url_es: Mapped[str | None] = mapped_column(String, nullable=True)
    has_task: Mapped[bool] = mapped_column(Boolean, default=False)
    has_prescreener: Mapped[bool] = mapped_column(Boolean, default=False)
    has_screener: Mapped[bool] = mapped_column(Boolean, default=False)
    task_slugs: Mapped[list] = mapped_column(JSON, default=list)
    location: Mapped[str] = mapped_column(String, default="Generic")
    difficulty: Mapped[int] = mapped_column(Integer, default=5)
    prerequisites: Mapped[list] = mapped_column(
        JSON, default=list
    )
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # relationships
    sessions = relationship("SessionModel", back_populates="sim", lazy="selectin")
    events = relationship("Event", back_populates="sim", lazy="selectin")
    task_results = relationship("TaskResult", back_populates="sim", lazy="selectin")
    feedback_logs = relationship("FeedbackLog", back_populates="sim", lazy="selectin")
    assignments = relationship("Assignment", back_populates="sim", lazy="selectin")
