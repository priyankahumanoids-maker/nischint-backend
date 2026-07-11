# Guardian AI Models — Prediction config and logs
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GuardianAIConfig(Base):
    __tablename__ = "guardian_ai_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    notification_threshold: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    call_threshold: Mapped[float] = mapped_column(Float, default=0.75, nullable=False)
    sos_threshold: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    auto_trigger: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )


class GuardianAIPrediction(Base):
    __tablename__ = "guardian_ai_predictions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(50), nullable=False)
    action_detail: Mapped[dict] = mapped_column(type_=JSON, default=dict, nullable=False)
    risk_factors: Mapped[list] = mapped_column(type_=JSON, default=list, nullable=False)
    layer_scores: Mapped[dict] = mapped_column(type_=JSON, default=dict, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    user_response: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
