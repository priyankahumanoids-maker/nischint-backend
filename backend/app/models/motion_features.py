"""NISCH-012 — `motion_features` ORM model.

Append-only ledger row. Writer = mobile uploader through
`POST /api/sensors/motion/features`. Readers = behavioural
baseline learner (mobility_signature) + risk prewarmer.

Strict invariants:
  * idempotency_key UNIQUE — duplicate uploads collapse to a
    single row via `ON CONFLICT DO NOTHING`.
  * activity_class ∈ locked 5-value enum
    (stationary | walking | running | vehicle | anomalous).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Locked activity-class enum. The mobile classifier emits one of
# these; the writer boundary rejects anything else.
ALLOWED_ACTIVITY_CLASSES: frozenset[str] = frozenset({
    "stationary", "walking", "running", "vehicle", "anomalous",
})

# Pipeline version stamp — bumped when the mobile feature
# extraction or activity-classifier logic changes so historical
# rows stay groupable by the algorithm that produced them.
TELEMETRY_PIPELINE_VERSION = "motion-2026.02.1"


class MotionFeatures(Base):
    __tablename__ = "motion_features"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )

    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    window_duration_s: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60,
    )

    accel_mean_g:    Mapped[float] = mapped_column(Float, nullable=False)
    accel_stddev_g:  Mapped[float] = mapped_column(Float, nullable=False)
    accel_peak_g:    Mapped[float] = mapped_column(Float, nullable=False)
    gyro_variance:   Mapped[float] = mapped_column(Float, nullable=False)

    activity_class:  Mapped[str] = mapped_column(String(20), nullable=False)
    sample_count:    Mapped[int] = mapped_column(Integer, nullable=False)
    sample_rate_hz:  Mapped[float] = mapped_column(Float, nullable=False)

    telemetry_pipeline_version: Mapped[str] = mapped_column(
        String(30), nullable=False,
    )
    device_context: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(120), nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=text("now()"),
    )


__all__ = [
    "MotionFeatures",
    "ALLOWED_ACTIVITY_CLASSES",
    "TELEMETRY_PIPELINE_VERSION",
]
