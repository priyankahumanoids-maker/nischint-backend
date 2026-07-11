"""create facilities table

Revision ID: o1a2b3c4dd01
Revises: n1a2b3c4dc01
Create Date: 2026-03-08 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "o1a2b3c4dd01"
down_revision = "n1a2b3c4dc01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "facilities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), unique=True, nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("facilities")
