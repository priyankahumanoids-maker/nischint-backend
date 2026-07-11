"""add_simulation_columns_to_telemetries_and_anomalies

Revision ID: c3f1a8b92d01
Revises: 0804daf31170
Create Date: 2026-03-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3f1a8b92d01'
down_revision: Union[str, Sequence[str], None] = '0804daf31170'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('telemetries', sa.Column('is_simulated', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('telemetries', sa.Column('simulation_run_id', sa.String(length=100), nullable=True))
    op.create_index('ix_telemetries_is_simulated', 'telemetries', ['is_simulated'])
    op.create_index('ix_telemetries_simulation_run_id', 'telemetries', ['simulation_run_id'])

    op.add_column('device_anomalies', sa.Column('is_simulated', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('device_anomalies', sa.Column('simulation_run_id', sa.String(length=100), nullable=True))
    op.create_index('ix_device_anomalies_is_simulated', 'device_anomalies', ['is_simulated'])
    op.create_index('ix_device_anomalies_simulation_run_id', 'device_anomalies', ['simulation_run_id'])


def downgrade() -> None:
    op.drop_index('ix_device_anomalies_simulation_run_id', table_name='device_anomalies')
    op.drop_index('ix_device_anomalies_is_simulated', table_name='device_anomalies')
    op.drop_column('device_anomalies', 'simulation_run_id')
    op.drop_column('device_anomalies', 'is_simulated')

    op.drop_index('ix_telemetries_simulation_run_id', table_name='telemetries')
    op.drop_index('ix_telemetries_is_simulated', table_name='telemetries')
    op.drop_column('telemetries', 'simulation_run_id')
    op.drop_column('telemetries', 'is_simulated')
