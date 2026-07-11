"""Migration: ACK + escalation primitive on `guardian_alerts`.

Phase 1 of the Control Layer (decision engine). Critical-severity
alerts now demand a guardian acknowledgement within a deadline; if
none arrives, the engine escalates through a stepped chain.

Strict scope of this migration: schema only. Behavior lives in
`services/alert_ack_engine.py`.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "z1a2b3c4do01"
down_revision = "y1a2b3c4dn01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guardian_alerts",
                  sa.Column("ack_required", sa.Boolean,
                            nullable=False, server_default=sa.text("false")))
    op.add_column("guardian_alerts",
                  sa.Column("ack_timeout_sec", sa.Integer, nullable=True))
    # `ack_status`: none (default for legacy + non-ack-required) |
    #               pending | acknowledged | escalated
    op.add_column("guardian_alerts",
                  sa.Column("ack_status", sa.String(16),
                            nullable=False, server_default="none"))
    op.add_column("guardian_alerts",
                  sa.Column("ack_deadline", sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column("guardian_alerts",
                  sa.Column("acked_by", UUID(as_uuid=True), nullable=True))
    op.add_column("guardian_alerts",
                  sa.Column("acked_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column("guardian_alerts",
                  sa.Column("escalation_step", sa.Integer,
                            nullable=False, server_default="0"))
    # Append-only audit trail of escalation steps:
    # [{"step": 1, "at": "2026-…", "reason": "ack_timeout"}]
    op.add_column("guardian_alerts",
                  sa.Column("escalation_history", JSONB,
                            nullable=False, server_default=sa.text("'[]'::jsonb")))

    # Hot-path index for the scheduler that scans for expired ACKs.
    op.create_index(
        "ix_guardian_alerts_pending_ack",
        "guardian_alerts",
        ["ack_deadline"],
        postgresql_where=sa.text("ack_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_guardian_alerts_pending_ack", table_name="guardian_alerts")
    for col in ("escalation_history", "escalation_step", "acked_at", "acked_by",
                "ack_deadline", "ack_status", "ack_timeout_sec", "ack_required"):
        op.drop_column("guardian_alerts", col)
