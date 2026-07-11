# Wandering Event Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WanderingEvent(Base):
    __tablename__ = "wandering_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    safe_zone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("safe_zones.id", ondelete="SET NULL"), nullable=True)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    distance_from_zone: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    time_outside_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    movement_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)  # away|toward|lateral

    wander_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|resolved|escalated

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
