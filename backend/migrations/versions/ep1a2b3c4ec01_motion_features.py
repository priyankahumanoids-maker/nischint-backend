"""Migration: NISCH-012 — `motion_features` ingestion ledger.

Continuous motion telemetry from the mobile app's 5 Hz subsampled
accelerometer + gyroscope, batched into 60 s feature windows and
uploaded every ~5 min. Immutable ledger pattern — same disposition
as `risk_predictions` and `behavioral_anomalies`.

Strict scope: schema only. Behaviour lives in
`app/api/motion_features.py` and `services/behavioral/baseline.py`.

Why immutable:
  * The mobile uploader is the only writer.
  * The behavioural baseline learner + risk prewarmer are READERS
    only — they aggregate, they never mutate.
  * `idempotency_key = device_id|window_started_at` (UNIQUE) so a
    retried upload after a flaky network never duplicates.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "ep1a2b3c4ec01"
down_revision = "eo1a2b3c4eb01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "motion_features",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),

        # 60-second window aligned at upload time.
        sa.Column(
            "window_started_at", sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("window_duration_s", sa.Integer, nullable=False,
                  server_default=sa.text("60")),

        # Aggregated accelerometer magnitudes over the window.
        sa.Column("accel_mean_g",   sa.Float, nullable=False),
        sa.Column("accel_stddev_g", sa.Float, nullable=False),
        sa.Column("accel_peak_g",   sa.Float, nullable=False),

        # Gyroscope variance — direction-agnostic rotation signal.
        sa.Column("gyro_variance",  sa.Float, nullable=False),

        # Edge-side activity class proxy. Locked enum:
        # stationary | walking | running | vehicle | anomalous
        sa.Column("activity_class", sa.String(20), nullable=False),

        # Sample count + sampling-rate fingerprint so reports can
        # tell apart "5 Hz baseline" from "1 Hz throttled" windows.
        sa.Column("sample_count",   sa.Integer, nullable=False),
        sa.Column("sample_rate_hz", sa.Float,   nullable=False),

        # Pipeline version for forward-compatibility — same idiom
        # as `behavioral_anomalies.anomaly_pipeline_version`.
        sa.Column(
            "telemetry_pipeline_version", sa.String(30), nullable=False,
        ),

        # Optional snapshot for forensic replay. Kept compact.
        sa.Column("device_context", JSONB, nullable=True),

        # `device_id|window_started_at` — UNIQUE — protects the
        # retry-after-flaky-network case from creating duplicates.
        sa.Column("idempotency_key", sa.String(120), nullable=False),

        sa.Column("uploaded_at", sa.DateTime(timezone=True),
                  nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_motion_features_entity_window",
        "motion_features",
        ["entity_id", sa.text("window_started_at DESC")],
    )
    op.create_index(
        "uq_motion_features_idempotency",
        "motion_features", ["idempotency_key"], unique=True,
    )
    op.create_index(
        "ix_motion_features_activity_class",
        "motion_features", ["activity_class"],
    )


def downgrade() -> None:
    op.drop_index("ix_motion_features_activity_class",
                  table_name="motion_features")
    op.drop_index("uq_motion_features_idempotency",
                  table_name="motion_features")
    op.drop_index("ix_motion_features_entity_window",
                  table_name="motion_features")
    op.drop_table("motion_features")
