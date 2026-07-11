"""create voice_events table (already applied manually in Neon)

Revision ID: s1a2b3c4dh01
Revises: 1d6a38a1602c
Create Date: 2026-03-13 14:00:00.000000

NOTE: This migration was created AFTER the table was manually built in
Neon production with full schema and 3 indexes. It exists solely to keep
Alembic history in sync. Do NOT run upgrade() again — use `alembic stamp`
to mark it as applied:

    alembic stamp s1a2b3c4dh01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = 's1a2b3c4dh01'
down_revision: Union[str, Sequence[str], None] = '1d6a38a1602c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'voice_events',
        sa.Column('id', UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', UUID(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('distress_score', sa.Float(), nullable=True),
        sa.Column('transcript', sa.Text(), nullable=True),
        sa.Column('audio_duration', sa.Float(), nullable=True),
        sa.Column('audio_url', sa.Text(), nullable=True),
        sa.Column('location_lat', sa.Float(), nullable=True),
        sa.Column('location_lng', sa.Float(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('incident_id', UUID(), nullable=True),
        sa.Column('triggered_sos', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('device_type', sa.String(), nullable=True),
        sa.Column('device_os', sa.String(), nullable=True),
        sa.Column('processing_status', sa.String(), server_default='processed', nullable=True),
        sa.Column('metadata', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_voice_events_user_id', 'voice_events', ['user_id'])
    op.create_index('idx_voice_events_timestamp', 'voice_events', ['timestamp'])
    op.create_index('idx_voice_events_event_type', 'voice_events', ['event_type'])


def downgrade() -> None:
    op.drop_index('idx_voice_events_event_type', table_name='voice_events')
    op.drop_index('idx_voice_events_timestamp', table_name='voice_events')
    op.drop_index('idx_voice_events_user_id', table_name='voice_events')
    op.drop_table('voice_events')
