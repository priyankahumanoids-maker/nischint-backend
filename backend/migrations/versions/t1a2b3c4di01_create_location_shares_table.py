"""create location_shares table

Revision ID: t1a2b3c4di01
Revises: s1a2b3c4dh01
Create Date: 2026-02-01 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 't1a2b3c4di01'
down_revision: Union[str, Sequence[str], None] = 's1a2b3c4dh01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'location_shares',
        sa.Column('id', UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', UUID(), sa.ForeignKey('guardian_sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('token', sa.String(64), nullable=False, unique=True),
        sa.Column('share_name', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_location_shares_user_id', 'location_shares', ['user_id'])
    op.create_index('idx_location_shares_token', 'location_shares', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_location_shares_token', table_name='location_shares')
    op.drop_index('idx_location_shares_user_id', table_name='location_shares')
    op.drop_table('location_shares')
