"""Add nullable date of birth to users for Family Circle v1.0.

Revision ID: fc01_user_date_of_birth
Revises: gz02_safe_zone_address
"""

from alembic import op
import sqlalchemy as sa


revision = "fc01_user_date_of_birth"
down_revision = "gz02_safe_zone_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "date_of_birth")
