"""create_simulation_runs_table

Revision ID: d4e2b9c01f23
Revises: c3f1a8b92d01
Create Date: 2026-03-04 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'd4e2b9c01f23'
down_revision: Union[str, Sequence[str], None] = 'c3f1a8b92d01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'simulation_runs',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('simulation_run_id', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('run_type', sa.String(20), nullable=False),
        sa.Column('config_json', JSONB, nullable=False),
        sa.Column('summary_json', JSONB, nullable=False),
        sa.Column('total_devices_affected', sa.Integer, nullable=False),
        sa.Column('anomalies_triggered', sa.Integer, nullable=False),
        sa.Column('scheduler_execution_ms', sa.Integer, nullable=True),
        sa.Column('db_write_volume', sa.Integer, nullable=False),
        sa.Column('executed_by_name', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_simulation_runs_created_at', 'simulation_runs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_simulation_runs_created_at', table_name='simulation_runs')
    op.drop_table('simulation_runs')
