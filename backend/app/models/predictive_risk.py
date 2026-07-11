# Predictive Risk Model
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PredictiveRisk(Base):
    __tablename__ = "predictive_risks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    prediction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prediction_score: Mapped[float] = mapped_column(Float, nullable=False)
    prediction_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=48)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    feature_vector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trend_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False,
    )
