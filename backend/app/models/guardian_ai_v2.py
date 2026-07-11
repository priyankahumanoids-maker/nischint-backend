# Guardian AI Refinement Models — baselines, risk scores, predictions, risk events
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, Boolean, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GuardianBaseline(Base):
    """Per-user behavioral baseline profile, updated daily."""
    __tablename__ = "guardian_baselines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # Active hour profile (histogram: hour → activity_level)
    active_hours: Mapped[dict] = mapped_column(type_=JSON, default=dict, nullable=False)
    # Mobility profile
    avg_daily_distance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    common_locations: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)
    route_clusters: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)
    # Device reliability
    avg_device_uptime: Mapped[float] = mapped_column(Float, default=0.95, nullable=False)
    avg_battery_drop: Mapped[float] = mapped_column(Float, default=0.02, nullable=False)
    avg_signal_loss_events: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    # Alert frequency
    normal_alerts_per_day: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    normal_incidents_per_week: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    # Caregiver interaction
    avg_caregiver_visits_per_week: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    # Data quality
    data_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class GuardianRiskScore(Base):
    """Point-in-time multi-factor risk assessment."""
    __tablename__ = "guardian_risk_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True,
    )
    # Sub-scores (0.0 – 1.0)
    behavior_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    location_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    device_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    environment_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Fused
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    # Explainability
    top_factors: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(50), default="monitor", nullable=False)
    action_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class GuardianPrediction(Base):
    """Forward-looking risk prediction (next N minutes)."""
    __tablename__ = "guardian_predictions_v2"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    prediction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    prediction_window_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    predicted_risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="moderate")
    recommended_action: Mapped[str] = mapped_column(String(50), nullable=False, default="monitor")
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class GuardianRiskEvent(Base):
    """Immutable log of every AI evaluation — for ML training and audit."""
    __tablename__ = "guardian_risk_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True,
    )
    baseline_deviation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    location_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    device_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    environment_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    top_factors: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(50), nullable=False, default="monitor")
    incident_created: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
