"""Migration: NISCH-011 — Behavioral Baseline + Digital Twin.

Creates two new tables that are distinct from the legacy
`behavior_baselines` / `behavior_anomalies` pair (those serve
the older device-anomaly pipeline). NISCH-011 names them
`behavioral_baselines` / `behavioral_anomalies` so the two
worlds never compete on schema.

Strict scope: schema only. Behaviour lives in
`services/behavioral/`.

Locked invariants:
  * `behavioral_anomalies` is an APPEND-ONLY ledger — every
    detection lands here, immutable except for
    `reconciliation_status` and `linked_prediction_id` patch-up
    (reconciler-only).
  * `linked_prediction_id` links into NISCH-010's
    `risk_predictions` table for cross-engine forensics. Foreign
    key constraint is *not* enforced because a baseline can be
    written before its corresponding prediction exists.
  * `baseline_version` / `anomaly_pipeline_version` track
    independent algorithm rolls so accuracy reports can group
    historical rows by the engine version that produced them.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "eo1a2b3c4eb01"
down_revision = "en1a2b3c4ea01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── behavioral_baselines ─────────────────────────────────────
    op.create_table(
        "behavioral_baselines",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),

        # Compact JSONB blobs — each one is the post-aggregation
        # signature, not a per-event log. The 14-day learner writes
        # them; the detector reads them.
        sa.Column("zone_affinity", JSONB, nullable=True),
        sa.Column("route_entropy", sa.Float, nullable=True),
        sa.Column("dwell_duration", JSONB, nullable=True),
        sa.Column("temporal_signature", JSONB, nullable=True),
        sa.Column("mobility_signature", JSONB, nullable=True),
        sa.Column("ambient_profile", JSONB, nullable=True),
        sa.Column("interaction_cadence", JSONB, nullable=True),
        sa.Column("risk_exposure_averages", JSONB, nullable=True),

        # Per-feature deviation thresholds learned from rolling
        # quantiles — locked here so the detector reads a single
        # source of truth rather than re-quantising at every
        # detection call.
        sa.Column("rolling_deviation_thresholds", JSONB, nullable=True),

        sa.Column("baseline_version", sa.String(30), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("computed_at", sa.DateTime(timezone=True),
                  nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_behavioral_baselines_entity",
        "behavioral_baselines", ["entity_id"], unique=True,
    )

    # ── behavioral_anomalies (immutable ledger) ─────────────────
    op.create_table(
        "behavioral_anomalies",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),

        # Coarse taxonomy — NEVER stringly-typed at the writer
        # boundary; the writer must use a values-only enum so
        # typos can never poison the ledger.
        sa.Column("anomaly_type", sa.String(50), nullable=False),
        sa.Column("anomaly_score", sa.Float, nullable=False),

        # `baseline | drift | irregular | elevated_behavioral_risk
        #  | critical_behavioral_shift`
        sa.Column("deviation_class", sa.String(40), nullable=False),

        sa.Column("contributing_features", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),

        # Cross-engine link — pointer into `risk_predictions.id`
        # for the prediction that was active when this anomaly
        # fired. Not a hard FK so the writer never blocks on a
        # missing prediction.
        sa.Column("linked_prediction_id", UUID(as_uuid=True), nullable=True),
        sa.Column("fused_zone_risk", sa.Float, nullable=True),

        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("explanation_snapshot", JSONB, nullable=True),
        sa.Column("anomaly_pipeline_version", sa.String(30), nullable=False),

        # `pending | reconciled | unresolved`. Reconciler-only
        # mutates this; everything else is immutable.
        sa.Column("reconciliation_status", sa.String(20),
                  nullable=False,
                  server_default=sa.text("'pending'")),

        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("reconciled_at", sa.DateTime(timezone=True),
                  nullable=True),
    )
    op.create_index(
        "ix_behavioral_anomalies_entity_created",
        "behavioral_anomalies",
        ["entity_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_behavioral_anomalies_class",
        "behavioral_anomalies", ["deviation_class"],
    )
    op.create_index(
        "ix_behavioral_anomalies_linked_prediction",
        "behavioral_anomalies", ["linked_prediction_id"],
        postgresql_where=sa.text("linked_prediction_id IS NOT NULL"),
    )
    op.create_index(
        "ix_behavioral_anomalies_pending",
        "behavioral_anomalies", ["created_at"],
        postgresql_where=sa.text("reconciliation_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_behavioral_anomalies_pending",
                  table_name="behavioral_anomalies")
    op.drop_index("ix_behavioral_anomalies_linked_prediction",
                  table_name="behavioral_anomalies")
    op.drop_index("ix_behavioral_anomalies_class",
                  table_name="behavioral_anomalies")
    op.drop_index("ix_behavioral_anomalies_entity_created",
                  table_name="behavioral_anomalies")
    op.drop_table("behavioral_anomalies")
    op.drop_index("ix_behavioral_baselines_entity",
                  table_name="behavioral_baselines")
    op.drop_table("behavioral_baselines")
