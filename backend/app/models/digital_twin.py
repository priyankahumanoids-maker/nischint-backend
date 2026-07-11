# Device Digital Twin Model — personalized behavioral profile per device
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeviceDigitalTwin(Base):
    __tablename__ = "device_digital_twins"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_digital_twin_device"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    twin_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    wake_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23
    sleep_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23
    peak_activity_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23
    movement_interval_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    typical_inactivity_max_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    daily_rhythm: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    activity_windows: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    profile_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    training_data_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
