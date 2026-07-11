"""add whisper verification columns to voice_distress_events

Revision ID: k1a2b3c4d901
Revises: j1a2b3c4d801
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'k1a2b3c4d901'
down_revision = 'j1a2b3c4d801'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('voice_distress_events', sa.Column('whisper_confidence', sa.Float(), nullable=True))
    op.add_column('voice_distress_events', sa.Column('verification_status', sa.String(20), server_default='none', nullable=False))
    op.add_column('voice_distress_events', sa.Column('distress_phrases_found', sa.JSON(), nullable=True))
    op.add_column('voice_distress_events', sa.Column('trigger_type', sa.String(20), server_default='on_device', nullable=False))


def downgrade() -> None:
    op.drop_column('voice_distress_events', 'trigger_type')
    op.drop_column('voice_distress_events', 'distress_phrases_found')
    op.drop_column('voice_distress_events', 'verification_status')
    op.drop_column('voice_distress_events', 'whisper_confidence')
