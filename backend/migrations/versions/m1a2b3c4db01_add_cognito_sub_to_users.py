"""add cognito_sub to users

Revision ID: m1a2b3c4db01
Revises: l1a2b3c4da01
Create Date: 2026-03-08 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "m1a2b3c4db01"
down_revision = "l1a2b3c4da01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("cognito_sub", sa.String(255), nullable=True, unique=True))
    op.create_index("ix_users_cognito_sub", "users", ["cognito_sub"], unique=True)


def downgrade():
    op.drop_index("ix_users_cognito_sub", table_name="users")
    op.drop_column("users", "cognito_sub")
