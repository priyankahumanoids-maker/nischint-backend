# Pickup Authorization Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PickupAuthorization(Base):
    __tablename__ = "pickup_authorizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    guardian_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    authorized_person_name: Mapped[str] = mapped_column(String(150), nullable=False)
    authorized_person_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    verification_method: Mapped[str] = mapped_column(String(10), default="pin", nullable=False)  # qr | pin
    pickup_code_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    pickup_location_lat: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_location_lng: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_radius_m: Mapped[float] = mapped_column(Float, default=50, nullable=False)
    pickup_location_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    scheduled_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # pending | verified | expired | cancelled

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
