# Behavioral Baseline Model — stores per-device per-hour behavioral baselines
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BehaviorBaseline(Base):
    __tablename__ = "behavior_baselines"
    __table_args__ = (
        UniqueConstraint("device_id", "hour_of_day", name="uq_behavior_baseline_device_hour"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23
    avg_movement: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    std_movement: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    avg_location_switch: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    std_location_switch: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    avg_interaction_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    std_interaction_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
