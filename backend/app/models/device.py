# Device Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.senior import Senior
    from app.models.telemetry import Telemetry
    from app.models.incident import Incident


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    senior_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seniors.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_identifier: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    device_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="offline",
        nullable=False,
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    senior: Mapped["Senior"] = relationship(
        "Senior",
        back_populates="devices",
    )
    telemetries: Mapped[List["Telemetry"]] = relationship(
        "Telemetry",
        back_populates="device",
        cascade="all, delete",
    )
    incidents: Mapped[List["Incident"]] = relationship(
        "Incident",
        back_populates="device",
        cascade="all, delete",
    )

    def __repr__(self) -> str:
        return f"<Device {self.device_identifier}>"
