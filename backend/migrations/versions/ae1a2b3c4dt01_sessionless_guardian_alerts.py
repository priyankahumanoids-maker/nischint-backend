"""Migration: session-less GuardianAlert support.

Per the safety-domain requirement: a help-request that arrives when
the child has NO active `guardian_session` (e.g. journey not started,
or session already auto-completed by the 24h zombie cap) must STILL
land in `guardian_alerts` so the ACK engine can escalate it and the
audit trail is complete.

Changes (Option A — minimal disruption, single table, no new state):
  1. `session_id` becomes NULLABLE.
  2. New `user_id UUID` column — the child the alert is about. Always
     populated. Backfilled from the linked session for existing rows.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "ae1a2b3c4dt01"
down_revision = "ad1a2b3c4ds01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Allow session-less alerts.
    op.alter_column("guardian_alerts", "session_id", nullable=True)

    # 2. Add user_id (child the alert is about).
    op.add_column(
        "guardian_alerts",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
    )

    # 3. Backfill from linked session.
    op.execute(
        """
        UPDATE guardian_alerts a
           SET user_id = s.user_id
          FROM guardian_sessions s
         WHERE a.session_id = s.id
           AND a.user_id IS NULL
        """
    )

    # 4. Tighten — every alert must know its subject. Any orphan
    #    rows (alerts whose session was deleted before backfill ran)
    #    are dropped: they're already context-less and useless.
    op.execute("DELETE FROM guardian_alerts WHERE user_id IS NULL")
    op.alter_column("guardian_alerts", "user_id", nullable=False)

    # 5. Hot-path index for "all alerts for child X" queries (the new
    #    session-less audit path uses this).
    op.create_index(
        "ix_guardian_alerts_user_id_created_at",
        "guardian_alerts",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_guardian_alerts_user_id_created_at",
                  table_name="guardian_alerts")
    op.drop_column("guardian_alerts", "user_id")
    # session_id -> NOT NULL again. Drop session-less alerts first to
    # respect the constraint.
    op.execute("DELETE FROM guardian_alerts WHERE session_id IS NULL")
    op.alter_column("guardian_alerts", "session_id", nullable=False)
