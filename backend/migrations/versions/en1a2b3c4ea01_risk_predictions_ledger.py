"""Migration: NISCH-010 — risk_predictions ledger.

Creates the immutable prediction ledger backing the Predictive
Risk Engine. Every forecast — successful or not — lands here so
the reconciler can later fill `actual_outcome` and `delta` for
accuracy analysis, regulator audit, and model rollback.

Strict scope: schema only. Behaviour lives in
`services/risk_prediction/`.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "en1a2b3c4ea01"
down_revision = "em1a2b3c4dz01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_predictions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("subject_id", UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("zone_id", UUID(as_uuid=True), nullable=True),

        sa.Column("prediction_window_min", sa.Integer, nullable=False),
        sa.Column("predicted_risk", sa.Float, nullable=False),

        # Reconciler-filled — never set at predict time.
        sa.Column("actual_outcome", sa.Float, nullable=True),
        sa.Column("delta", sa.Float, nullable=True),

        sa.Column("confidence_score", sa.Float, nullable=False),

        # Derived prediction state — stable | rising | volatile |
        # critical_escalation. Computed at predict time, persisted
        # so the operator UI / accuracy reports don't have to
        # recompute it.
        sa.Column("prediction_class", sa.String(30), nullable=True),

        sa.Column(
            "contributing_factors", JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),

        # Snapshot of the inputs that produced the prediction —
        # enables deterministic replay if the same prediction needs
        # to be regenerated for audit. Kept compact (history tail
        # only, not the full 30-day window).
        sa.Column(
            "prediction_context_snapshot", JSONB, nullable=True,
        ),

        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("feature_hash", sa.String(64), nullable=True),

        # Pipeline-level versioning — distinct from `model_version`
        # so the orchestrator can roll independently of the models.
        sa.Column(
            "prediction_pipeline_version", sa.String(20), nullable=True,
        ),

        # Set by the reconciler when it computes outcome. Lets the
        # accuracy report tell apart Phase-1 reconciliation from
        # any future v2 outcome-resolution algorithm.
        sa.Column(
            "outcome_resolution_version", sa.String(20), nullable=True,
        ),

        sa.Column(
            "predicted_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "window_expires_at", sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "outcome_recorded_at", sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_rp_subject", "risk_predictions",
        ["subject_id", sa.text("predicted_at DESC")],
    )
    op.create_index(
        "idx_rp_zone", "risk_predictions",
        ["zone_id", sa.text("predicted_at DESC")],
    )
    op.create_index(
        "idx_rp_accuracy", "risk_predictions", ["delta"],
        postgresql_where=sa.text("delta IS NOT NULL"),
    )
    op.create_index(
        "idx_rp_pending_outcome", "risk_predictions",
        ["window_expires_at"],
        postgresql_where=sa.text("actual_outcome IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_rp_pending_outcome", table_name="risk_predictions")
    op.drop_index("idx_rp_accuracy", table_name="risk_predictions")
    op.drop_index("idx_rp_zone", table_name="risk_predictions")
    op.drop_index("idx_rp_subject", table_name="risk_predictions")
    op.drop_table("risk_predictions")
