"""NISCH-010 — risk_predictions ORM model.

Distinct from the pre-existing `predictive_risks` table (which
serves device-level wearable anomaly predictions on a 48 h
horizon). This model serves zone/subject forecasts on a 15 or
60-min horizon — the foundational ledger for the Predictive
Risk Engine.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiskPrediction(Base):
    __tablename__ = "risk_predictions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )  # 'child' | 'zone'
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    prediction_window_min: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_risk: Mapped[float] = mapped_column(Float, nullable=False)

    # Reconciled retrospectively by the reconciler job — when the
    # prediction window expires we compute what actually happened
    # in that window and write it back. `delta = actual - predicted`
    # is the model accuracy signal.
    actual_outcome: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Derived state — one of: stable | rising | volatile |
    # critical_escalation. Persisted so the API never has to
    # recompute it.
    prediction_class: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
    )

    contributing_factors: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )

    # Compact snapshot of the inputs the prediction was made
    # from — supports deterministic replay during model audit.
    prediction_context_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    feature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    prediction_pipeline_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )
    outcome_resolution_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )

    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )
    window_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
