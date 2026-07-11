"""Migration: add `root_cause_domain` to system_incidents.

Phase 1.x++  Lightweight RCA tag computed from the snapshot at incident
open + refresh on resolve. Pure classification: scheduler | ai | queue.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision = "x1a2b3c4dm01"
down_revision = "w1a2b3c4dl01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_incidents",
        sa.Column("root_cause_domain", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_system_incidents_root_cause_domain",
        "system_incidents",
        ["root_cause_domain"],
    )


def downgrade() -> None:
    op.drop_index("ix_system_incidents_root_cause_domain", table_name="system_incidents")
    op.drop_column("system_incidents", "root_cause_domain")
