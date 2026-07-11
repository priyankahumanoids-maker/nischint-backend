"""Migration: automated_call spam guard column.

Mirrors `last_louder_push_at` — prevents a single `escalated` alert
from firing Twilio calls every tick while parked at that step.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision = "af1a2b3c4du01"
down_revision = "ae1a2b3c4dt01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guardian_alerts",
        sa.Column(
            "last_automated_call_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("guardian_alerts", "last_automated_call_at")
