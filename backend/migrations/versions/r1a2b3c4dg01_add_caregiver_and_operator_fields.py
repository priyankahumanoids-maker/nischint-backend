"""Add caregiver and operator assignment fields

Revision ID: r1a2b3c4dg01
Revises: q1a2b3c4df01
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "r1a2b3c4dg01"
down_revision = "q1a2b3c4df01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Incident assignment fields
    op.add_column("incidents", sa.Column("assigned_to_user_id", sa.Uuid(), nullable=True))
    op.add_column("incidents", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True))

    # Caregiver status table
    op.create_table(
        "caregiver_statuses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), server_default="available", nullable=False),
        sa.Column("facility_id", sa.String(100), nullable=True),
        sa.Column("current_assignment_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_caregiver_statuses_user_id", "caregiver_statuses", ["user_id"])

    # Visit logs
    op.create_table(
        "visit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("senior_id", sa.Uuid(), sa.ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(200), nullable=False),
        sa.Column("status", sa.String(50), server_default="completed", nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Health notes
    op.create_table(
        "health_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("senior_id", sa.Uuid(), sa.ForeignKey("seniors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), server_default="low", nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("follow_up", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("health_notes")
    op.drop_table("visit_logs")
    op.drop_index("ix_caregiver_statuses_user_id", "caregiver_statuses")
    op.drop_table("caregiver_statuses")
    op.drop_column("incidents", "assigned_by_user_id")
    op.drop_column("incidents", "assigned_at")
    op.drop_column("incidents", "assigned_to_user_id")
