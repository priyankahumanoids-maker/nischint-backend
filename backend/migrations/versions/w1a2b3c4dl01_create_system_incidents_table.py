"""Migration: create `system_incidents` table.

Phase 1.x close-out — historical truth layer for system_health_delta.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# Alembic identifiers
revision = "w1a2b3c4dl01"
down_revision = "v1a2b3c4dk01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_incidents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("severity_peak", sa.String(16), nullable=False),
        sa.Column("trigger_source", sa.String(32), nullable=False),
        sa.Column("trigger_metric", sa.String(64), nullable=True),
        sa.Column("snapshot_json",   JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolution_json", JSONB(), nullable=True),
    )
    op.create_index("ix_system_incidents_status", "system_incidents", ["status"])
    op.create_index("ix_system_incidents_started_at", "system_incidents", ["started_at"])
    # Partial unique-ish: at most one ACTIVE incident at a time.
    op.create_index(
        "ix_system_incidents_active_singleton",
        "system_incidents",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_system_incidents_active_singleton", table_name="system_incidents")
    op.drop_index("ix_system_incidents_started_at", table_name="system_incidents")
    op.drop_index("ix_system_incidents_status", table_name="system_incidents")
    op.drop_table("system_incidents")
