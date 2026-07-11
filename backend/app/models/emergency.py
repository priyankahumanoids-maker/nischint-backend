# Emergency Event Models
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, JSON, ForeignKey, Text, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmergencyEvent(Base):
    __tablename__ = "emergency_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False)  # shake, hidden_button, volume_combo, power_button
    severity_level: Mapped[int] = mapped_column(Integer, default=2, nullable=False)  # 1=suspicious, 2=distress, 3=confirmed_emergency
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active, cancelled, resolved, escalated
    cancel_pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location_trail: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)  # [{lat, lng, ts}]
    guardians_notified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("device_metadata", type_=JSON, nullable=True)  # device info, battery, network
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
