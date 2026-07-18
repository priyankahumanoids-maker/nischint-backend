# Monitored Route Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MonitoredRoute(Base):
    __tablename__ = "monitored_routes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_guardian_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    origin_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lng: Mapped[float] = mapped_column(Float, nullable=False)
    dest_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    dest_lat: Mapped[float] = mapped_column(Float, nullable=False)
    dest_lng: Mapped[float] = mapped_column(Float, nullable=False)
    corridor_width_m: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
