"""create safety_events table for Safety Brain

Revision ID: i1a2b3c4d701
Revises: h1a2b3c4d601
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = 'i1a2b3c4d701'
down_revision = 'h1a2b3c4d601'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'safety_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('risk_level', sa.String(20), nullable=False),
        sa.Column('signals', JSON(), nullable=False),
        sa.Column('primary_event', sa.String(30), nullable=False),
        sa.Column('location_lat', sa.Float(), nullable=False),
        sa.Column('location_lng', sa.Float(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_safety_events_user_status', 'safety_events', ['user_id', 'status'])
    op.create_index('ix_safety_events_created_at', 'safety_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_safety_events_created_at')
    op.drop_index('ix_safety_events_user_status')
    op.drop_table('safety_events')
