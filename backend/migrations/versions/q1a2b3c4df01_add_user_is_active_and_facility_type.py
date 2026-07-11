"""Add user is_active and facility facility_type columns

Revision ID: q1a2b3c4df01
Revises: p1a2b3c4de01
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "q1a2b3c4df01"
down_revision = "p1a2b3c4de01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("facilities", sa.Column("facility_type", sa.String(50), server_default="home", nullable=False))


def downgrade() -> None:
    op.drop_column("facilities", "facility_type")
    op.drop_column("users", "is_active")
