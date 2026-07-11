# Fake Call Preset Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FakeCallPreset(Base):
    __tablename__ = "fake_call_presets"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    caller_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    caller_label: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Custom",
    )
    caller_avatar_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    ringtone_style: Mapped[str] = mapped_column(
        String(30),
        default="default",
        nullable=False,
    )
    auto_answer_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class FakeCallLog(Base):
    __tablename__ = "fake_call_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fake_call_presets.id", ondelete="SET NULL"),
        nullable=True,
    )
    caller_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    trigger_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="manual",
    )
    delay_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="triggered",
        nullable=False,
    )
    answered: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    alert_sent: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lng: Mapped[float | None] = mapped_column(nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
