"""create_device_baselines_and_anomalies

Revision ID: 0804daf31170
Revises: b92ea9990c34
Create Date: 2026-03-01 13:38:42.918836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0804daf31170'
down_revision: Union[str, Sequence[str], None] = 'b92ea9990c34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('device_anomalies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('metric', sa.String(length=100), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('reason_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_device_anomalies_created_at', 'device_anomalies', ['created_at'])
    op.create_index('ix_device_anomalies_device_id', 'device_anomalies', ['device_id'])

    op.create_table('device_baselines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.UUID(), nullable=False),
        sa.Column('metric', sa.String(length=100), nullable=False),
        sa.Column('window_minutes', sa.Integer(), nullable=False),
        sa.Column('expected_value', sa.Float(), nullable=False),
        sa.Column('lower_band', sa.Float(), nullable=False),
        sa.Column('upper_band', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'metric', name='uq_device_baseline')
    )


def downgrade() -> None:
    op.drop_table('device_baselines')
    op.drop_index('ix_device_anomalies_device_id', table_name='device_anomalies')
    op.drop_index('ix_device_anomalies_created_at', table_name='device_anomalies')
    op.drop_table('device_anomalies')
