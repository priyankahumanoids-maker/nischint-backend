# Reroute Suggestion DB Model
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, JSON, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, Mapped

from app.db.base import Base


class RerouteSuggestion(Base):
    __tablename__ = "reroute_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Risk context
    trigger_risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    trigger_risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)  # auto | manual
    trigger_signals: Mapped[dict] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Current route snapshot
    current_route_risk: Mapped[float] = mapped_column(Float, nullable=True)
    current_location_lat: Mapped[float] = mapped_column(Float, nullable=False)
    current_location_lng: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lat: Mapped[float] = mapped_column(Float, nullable=True)
    destination_lng: Mapped[float] = mapped_column(Float, nullable=True)

    # Suggested safer route
    suggested_route_geometry: Mapped[dict] = mapped_column(JSON, nullable=True)
    suggested_route_risk: Mapped[float] = mapped_column(Float, nullable=True)
    suggested_route_distance_m: Mapped[float] = mapped_column(Float, nullable=True)
    suggested_route_duration_s: Mapped[float] = mapped_column(Float, nullable=True)
    eta_change_seconds: Mapped[float] = mapped_column(Float, nullable=True)

    # Safety scoring details
    safety_score_details: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | approved | dismissed | expired
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
