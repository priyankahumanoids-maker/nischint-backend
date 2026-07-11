"""Migration: NISCH-002B — User.last_known location columns.

Adds `last_known_lat`, `last_known_lng`, `last_known_at` to `users`.

Why: enables co-location suppression in `trigger_alert`'s SSE fan-out.
A guardian standing next to the child shouldn't get a push for a
geofence-breach the child triggered while *with* them — that's noise.

These columns are NULL-able by design. Downstream filters MUST treat
NULL as "no recent fix" → never co-located → always notify (fail-safe).

The mobile heartbeat will populate these on every position update;
populated lazily — older accounts simply stay NULL until next heartbeat.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision = "ag1a2b3c4dv01"
down_revision = "af1a2b3c4du01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_known_lat", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("last_known_lng", sa.Float(), nullable=True))
    op.add_column(
        "users",
        sa.Column("last_known_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_known_at")
    op.drop_column("users", "last_known_lng")
    op.drop_column("users", "last_known_lat")
