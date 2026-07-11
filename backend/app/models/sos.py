# SOS Config & Log Models
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SOSConfig(Base):
    __tablename__ = "sos_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_keywords: Mapped[list] = mapped_column(
        type_=JSON, default=lambda: ["help me", "sos now", "emergency"],
        nullable=False,
    )
    chain_notification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    chain_notification_delay: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    chain_call: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    chain_call_delay: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    chain_call_preset_name: Mapped[str] = mapped_column(String(120), default="Boss", nullable=False)
    chain_notification_title: Mapped[str] = mapped_column(
        String(200), default="Team Meeting in 5 min", nullable=False,
    )
    chain_notification_message: Mapped[str] = mapped_column(
        Text, default="Your 3:30 PM standup starts soon. Join the call now.", nullable=False,
    )
    trusted_contacts: Mapped[list] = mapped_column(
        type_=JSON, default=list, nullable=False,
    )
    auto_share_location: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    silent_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class SOSLog(Base):
    __tablename__ = "sos_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    trigger_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manual",
    )
    status: Mapped[str] = mapped_column(
        String(30), default="active", nullable=False,
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_notification_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    chain_call_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alert_sent_to: Mapped[list] = mapped_column(
        type_=JSON, default=list, nullable=False,
    )
    resolved_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
