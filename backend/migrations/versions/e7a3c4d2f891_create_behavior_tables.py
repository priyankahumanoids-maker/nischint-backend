"""create behavior baselines and anomalies tables

Revision ID: e7a3c4d2f891
Revises: d4e2b9c01f23
Create Date: 2026-03-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e7a3c4d2f891'
down_revision = 'd4e2b9c01f23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('behavior_baselines',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('hour_of_day', sa.Integer(), nullable=False),
        sa.Column('avg_movement', sa.Float(), nullable=False, server_default='0'),
        sa.Column('std_movement', sa.Float(), nullable=False, server_default='1'),
        sa.Column('avg_location_switch', sa.Float(), nullable=False, server_default='0'),
        sa.Column('std_location_switch', sa.Float(), nullable=False, server_default='1'),
        sa.Column('avg_interaction_rate', sa.Float(), nullable=False, server_default='0'),
        sa.Column('std_interaction_rate', sa.Float(), nullable=False, server_default='1'),
        sa.Column('sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'hour_of_day', name='uq_behavior_baseline_device_hour'),
    )
    op.create_index(op.f('ix_behavior_baselines_device_id'), 'behavior_baselines', ['device_id'])

    op.create_table('behavior_anomalies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('behavior_score', sa.Float(), nullable=False),
        sa.Column('anomaly_type', sa.String(100), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('is_simulated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_behavior_anomalies_device_id'), 'behavior_anomalies', ['device_id'])
    op.create_index(op.f('ix_behavior_anomalies_created_at'), 'behavior_anomalies', ['created_at'])


def downgrade() -> None:
    op.drop_index(op.f('ix_behavior_anomalies_created_at'), table_name='behavior_anomalies')
    op.drop_index(op.f('ix_behavior_anomalies_device_id'), table_name='behavior_anomalies')
    op.drop_table('behavior_anomalies')
    op.drop_index(op.f('ix_behavior_baselines_device_id'), table_name='behavior_baselines')
    op.drop_table('behavior_baselines')
