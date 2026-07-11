# Device Baseline Model — stores rolling adaptive baselines per device per metric
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DeviceBaseline(Base):
    __tablename__ = "device_baselines"
    __table_args__ = (
        UniqueConstraint("device_id", "metric", name="uq_device_baseline"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    lower_band: Mapped[float] = mapped_column(Float, nullable=False)
    upper_band: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
