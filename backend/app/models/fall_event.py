# Fall Event Model — Apple Watch-style 5-stage fall detection
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, JSON, ForeignKey, Float, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FallEvent(Base):
    __tablename__ = "fall_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    # 5-stage detection signals
    impact_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    freefall_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    orientation_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    post_impact_motion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    immobility_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Confidence scoring
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0.0 - 1.0

    # Status
    status: Mapped[str] = mapped_column(String(20), default="detected", nullable=False)
    # detected | confirmed | auto_sos | resolved | cancelled
    resolved_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # user_confirmed_safe | user_called_help | auto_sos_triggered | movement_detected | operator_resolved

    # Linked emergency (if auto-SOS triggered)
    emergency_event_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Sensor data for ML training
    sensor_data: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
