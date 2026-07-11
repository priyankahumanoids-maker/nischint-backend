"""Migration: Louder Push spam guard.

Adds `last_louder_push_at` to suppress escalation-loop storms — a
parked alert hitting a tick every 5 s would re-broadcast a critical-
channel push 12 times a minute without this guard. We ship one within
any 15 s window, max.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision = "ac1a2b3c4dr01"
down_revision = "ab1a2b3c4dq01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guardian_alerts",
        sa.Column("last_louder_push_at",
                  sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guardian_alerts", "last_louder_push_at")
