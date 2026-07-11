"""NISCH-011 — Behavioral Baseline + Digital Twin ORM models.

Distinct from the legacy `behavior_baselines` / `behavior_anomalies`
(those serve the older device-anomaly pipeline). NISCH-011 names
its tables `behavioral_*` so the two systems never compete on
schema.

The anomaly ledger is APPEND-ONLY except for two reconciler-
patched columns:
  * `reconciliation_status`  (pending → reconciled | unresolved)
  * `reconciled_at`

Nothing else may mutate a row. Locked at the writer boundary by
`detector.py::write_anomaly` (no update path exists).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BehavioralBaseline(Base):
    __tablename__ = "behavioral_baselines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )

    zone_affinity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    route_entropy: Mapped[float | None] = mapped_column(Float, nullable=True)
    dwell_duration: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    temporal_signature: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mobility_signature: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ambient_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    interaction_cadence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_exposure_averages: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    rolling_deviation_thresholds: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    baseline_version: Mapped[str] = mapped_column(String(30), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )


class BehavioralAnomaly(Base):
    __tablename__ = "behavioral_anomalies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )

    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_class: Mapped[str] = mapped_column(String(40), nullable=False)

    contributing_features: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
    )

    linked_prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    fused_zone_risk: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    explanation_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    anomaly_pipeline_version: Mapped[str] = mapped_column(
        String(30), nullable=False,
    )
    reconciliation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
