"""ORM model for the ``schedules`` table."""

import uuid
import datetime as dt

from sqlalchemy import String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base


class Schedule(Base):
    """Recurring send rule linking a template to a set of days and a time."""

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    message_template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("message_templates.id"), nullable=False)
    days_of_week: Mapped[list] = mapped_column(JSONB, nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(8), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)

    owner: Mapped["User"] = relationship("User", back_populates="schedules")
    template: Mapped["MessageTemplate"] = relationship("MessageTemplate", back_populates="schedules")
