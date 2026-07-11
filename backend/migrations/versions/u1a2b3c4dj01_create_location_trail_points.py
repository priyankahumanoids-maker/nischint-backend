"""create location_trail_points table

Revision ID: u1a2b3c4dj01
Revises: t1a2b3c4di01
Create Date: 2026-03-17 04:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'u1a2b3c4dj01'
down_revision: Union[str, Sequence[str], None] = 't1a2b3c4di01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'location_trail_points',
        sa.Column('id', UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('share_token', sa.String(64), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('speed_kmh', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_stop', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_trail_share_token', 'location_trail_points', ['share_token'])
    op.create_index('idx_trail_recorded_at', 'location_trail_points', ['share_token', 'recorded_at'])


def downgrade() -> None:
    op.drop_index('idx_trail_recorded_at', table_name='location_trail_points')
    op.drop_index('idx_trail_share_token', table_name='location_trail_points')
    op.drop_table('location_trail_points')
