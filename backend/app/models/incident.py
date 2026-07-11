# Incident Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.senior import Senior
    from app.models.device import Device
    from app.models.notification import Notification


# Default escalation time in minutes by severity
DEFAULT_ESCALATION_MINUTES = {
    "critical": 5,
    "high": 15,
    "medium": 30,
    "low": 60,
}


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    senior_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seniors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="open",
        nullable=False,
    )
    escalation_minutes: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    escalated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_via: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    escalation_level: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    level2_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    level3_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    escalation_processing: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
    )
    is_test: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Relationships
    senior: Mapped["Senior"] = relationship(
        "Senior",
        back_populates="incidents",
    )
    device: Mapped["Device"] = relationship(
        "Device",
        back_populates="incidents",
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="incident",
        cascade="all, delete",
    )

    def __repr__(self) -> str:
        return f"<Incident {self.incident_type} [{self.severity}]>"
