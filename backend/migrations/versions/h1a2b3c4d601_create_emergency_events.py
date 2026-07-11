"""create emergency_events table

Revision ID: h1a2b3c4d601
Revises: g1a2b3c4d501
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = 'h1a2b3c4d601'
down_revision = 'g1a2b3c4d501'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'emergency_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('trigger_source', sa.String(50), nullable=False),
        sa.Column('severity_level', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('cancel_pin_hash', sa.String(255), nullable=True),
        sa.Column('audio_url', sa.String(500), nullable=True),
        sa.Column('location_trail', JSON(), nullable=False, server_default='[]'),
        sa.Column('guardians_notified', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('device_metadata', JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_emergency_events_status', 'emergency_events', ['status'])
    op.create_index('ix_emergency_events_created_at', 'emergency_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_emergency_events_created_at')
    op.drop_index('ix_emergency_events_status')
    op.drop_table('emergency_events')
