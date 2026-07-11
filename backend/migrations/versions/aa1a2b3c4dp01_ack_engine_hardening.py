"""Migration: ACK engine production hardening.

Three production-trust fixes shipped together:

  1. **Context bundle**: an immutable JSON snapshot captured at the
     moment an alert demands acknowledgement. So escalations can never
     fire blind — every step carries last-known-location, tracking
     mode, risk level, and guardian reachability.

  2. **Tri-state ACK**: separates *seeing* an alert from *acting on it*
     from *resolving it*. Closes the false-closure problem.

  3. **`seen_deadline`**: drives the 60-second soft re-escalation when
     a guardian acknowledges (`seen`) but doesn't progress to
     `acting` within the window.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "aa1a2b3c4dp01"
down_revision = "z1a2b3c4do01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Immutable context snapshot for blind-escalation prevention.
    op.add_column(
        "guardian_alerts",
        sa.Column("context_json", JSONB,
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    # Tri-state response depth — null until first ACK, then
    # `seen` → `acting` → `resolved`. `seen_lapsed` is a tick-set
    # marker when a `seen` ACK doesn't progress within the window.
    op.add_column(
        "guardian_alerts",
        sa.Column("ack_type", sa.String(16), nullable=True),
    )
    # 60-second window after `seen` for the guardian to commit to
    # `acting`. Lapses fire a soft re-escalation event.
    op.add_column(
        "guardian_alerts",
        sa.Column("seen_deadline", sa.DateTime(timezone=True), nullable=True),
    )
    # Hot-path index for the seen-lapse tick (mirrors the pattern we
    # already use for ack_deadline).
    op.create_index(
        "ix_guardian_alerts_seen_lapse",
        "guardian_alerts",
        ["seen_deadline"],
        postgresql_where=sa.text("ack_type = 'seen'"),
    )


def downgrade() -> None:
    op.drop_index("ix_guardian_alerts_seen_lapse", table_name="guardian_alerts")
    op.drop_column("guardian_alerts", "seen_deadline")
    op.drop_column("guardian_alerts", "ack_type")
    op.drop_column("guardian_alerts", "context_json")
