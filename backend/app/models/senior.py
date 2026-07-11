# Senior Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING, List

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.device import Device
    from app.models.incident import Incident


class Senior(Base):
    __tablename__ = "seniors"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    guardian_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    age: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    medical_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    guardian: Mapped["User"] = relationship(
        "User",
        back_populates="seniors",
    )
    devices: Mapped[List["Device"]] = relationship(
        "Device",
        back_populates="senior",
        cascade="all, delete",
    )
    incidents: Mapped[List["Incident"]] = relationship(
        "Incident",
        back_populates="senior",
        cascade="all, delete",
    )

    def __repr__(self) -> str:
        return f"<Senior {self.full_name}>"
