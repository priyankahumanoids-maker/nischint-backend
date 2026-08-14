"""Persist the human-readable address for safety-zone cards.

Revision ID: gz02_safe_zone_address
Revises: pf01_user_profile_photo
"""

from alembic import op
import sqlalchemy as sa


revision = "gz02_safe_zone_address"
down_revision = "pf01_user_profile_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("safe_zones", sa.Column("address", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("safe_zones", "address")
