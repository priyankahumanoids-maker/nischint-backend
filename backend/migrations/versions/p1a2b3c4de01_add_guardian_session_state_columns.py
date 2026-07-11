"""Add guardian session state columns for persistent DB sessions

Revision ID: p1a2b3c4de01
Revises: o1a2b3c4dd01
Create Date: 2026-02-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "p1a2b3c4de01"
down_revision = "o1a2b3c4dd01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guardian_sessions", sa.Column("route_points", sa.JSON(), nullable=True))
    op.add_column("guardian_sessions", sa.Column("previous_location", sa.JSON(), nullable=True))
    op.add_column("guardian_sessions", sa.Column("previous_update_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("guardian_sessions", sa.Column("zone_id", sa.String(100), nullable=True))
    op.add_column("guardian_sessions", sa.Column("route_deviation_m", sa.Float(), server_default="0.0", nullable=False))
    op.add_column("guardian_sessions", sa.Column("idle_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("guardian_sessions", sa.Column("idle_duration_s", sa.Float(), server_default="0.0", nullable=False))
    op.add_column("guardian_sessions", sa.Column("alert_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("guardian_sessions", sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("guardian_sessions", sa.Column("safety_check_pending", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("guardian_sessions", sa.Column("safety_check_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("guardian_sessions", "safety_check_sent_at")
    op.drop_column("guardian_sessions", "safety_check_pending")
    op.drop_column("guardian_sessions", "last_alert_at")
    op.drop_column("guardian_sessions", "alert_count")
    op.drop_column("guardian_sessions", "idle_duration_s")
    op.drop_column("guardian_sessions", "idle_since")
    op.drop_column("guardian_sessions", "route_deviation_m")
    op.drop_column("guardian_sessions", "zone_id")
    op.drop_column("guardian_sessions", "previous_update_at")
    op.drop_column("guardian_sessions", "previous_location")
    op.drop_column("guardian_sessions", "route_points")
