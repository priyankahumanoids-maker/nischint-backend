"""add facility_id to users

Revision ID: n1a2b3c4dc01
Revises: m1a2b3c4db01
Create Date: 2026-03-08 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "n1a2b3c4dc01"
down_revision = "m1a2b3c4db01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("facility_id", sa.String(100), nullable=True))
    op.create_index("ix_users_facility_id", "users", ["facility_id"])


def downgrade():
    op.drop_index("ix_users_facility_id", table_name="users")
    op.drop_column("users", "facility_id")
