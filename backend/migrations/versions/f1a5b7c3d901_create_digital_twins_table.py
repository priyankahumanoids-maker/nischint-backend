"""create device_digital_twins table

Revision ID: f1a5b7c3d901
Revises: e7a3c4d2f891
Create Date: 2026-03-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f1a5b7c3d901'
down_revision = 'e7a3c4d2f891'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('device_digital_twins',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('twin_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('wake_hour', sa.Integer(), nullable=True),
        sa.Column('sleep_hour', sa.Integer(), nullable=True),
        sa.Column('peak_activity_hour', sa.Integer(), nullable=True),
        sa.Column('movement_interval_minutes', sa.Float(), nullable=True),
        sa.Column('typical_inactivity_max_minutes', sa.Float(), nullable=True),
        sa.Column('daily_rhythm', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('activity_windows', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('profile_summary', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('training_data_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_trained_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', name='uq_digital_twin_device'),
    )
    op.create_index(op.f('ix_device_digital_twins_device_id'), 'device_digital_twins', ['device_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_device_digital_twins_device_id'), table_name='device_digital_twins')
    op.drop_table('device_digital_twins')
