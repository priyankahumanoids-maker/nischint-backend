"""Persist user profile photos.

Revision ID: pf01_user_profile_photo
Revises: oce01b_ai_confidence_history
"""

from alembic import op
import sqlalchemy as sa


revision = "pf01_user_profile_photo"
down_revision = "oce01b_ai_confidence_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_photo_data", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "profile_photo_data")
