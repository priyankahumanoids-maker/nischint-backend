# Telemetry Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, Any

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.device import Device


class Telemetry(Base):
    __tablename__ = "telemetries"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    metric_value: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    is_simulated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    simulation_run_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="telemetries",
    )

    def __repr__(self) -> str:
        return f"<Telemetry {self.metric_type} @ {self.created_at}>"
