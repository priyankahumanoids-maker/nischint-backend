"""Migration: ACK engine field-readiness hardening.

Three fixes shipped together — ship them as a unit so the engine
behavior change is atomic in production:

  1. **Acting heartbeat liveness**: a guardian who clicks `acting` but
     then loses connectivity / panics / locks the screen needs to be
     surfaced to operations within 30 s. We track the last heartbeat
     timestamp in a new column.

  2. (No schema needed for misclick guard — it's a request-body flag.)
  3. (No schema needed for risk-weighted timeout — it's a code change.)
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision = "ab1a2b3c4dq01"
down_revision = "aa1a2b3c4dp01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guardian_alerts",
        sa.Column("acting_heartbeat_at",
                  sa.DateTime(timezone=True), nullable=True),
    )
    # Hot-path index: tick scans for acting alerts whose last heartbeat
    # is older than 30 s.
    op.create_index(
        "ix_guardian_alerts_acting_heartbeat",
        "guardian_alerts",
        ["acting_heartbeat_at"],
        postgresql_where=sa.text("ack_type = 'acting'"),
    )


def downgrade() -> None:
    op.drop_index("ix_guardian_alerts_acting_heartbeat",
                  table_name="guardian_alerts")
    op.drop_column("guardian_alerts", "acting_heartbeat_at")
