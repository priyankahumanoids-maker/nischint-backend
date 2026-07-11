"""create_guardian_tables

Revision ID: ee1f0143ad41
Revises: f1a5b7c3d901
Create Date: 2026-03-07 07:22:29.188098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee1f0143ad41'
down_revision: Union[str, Sequence[str], None] = 'f1a5b7c3d901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('guardians',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('relationship', sa.String(length=100), nullable=False),
        sa.Column('notification_pref', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guardians_user_id', 'guardians', ['user_id'])

    op.create_table('guardian_sessions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('destination', sa.JSON(), nullable=True),
        sa.Column('current_location', sa.JSON(), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('zone_name', sa.String(length=255), nullable=True),
        sa.Column('eta_minutes', sa.Float(), nullable=True),
        sa.Column('speed_mps', sa.Float(), nullable=False),
        sa.Column('total_distance_m', sa.Float(), nullable=False),
        sa.Column('location_updates', sa.Integer(), nullable=False),
        sa.Column('escalation_level', sa.String(length=20), nullable=False),
        sa.Column('is_night', sa.Boolean(), nullable=False),
        sa.Column('route_deviated', sa.Boolean(), nullable=False),
        sa.Column('is_idle', sa.Boolean(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guardian_sessions_user_id', 'guardian_sessions', ['user_id'])

    op.create_table('guardian_alerts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('alert_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('location', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['guardian_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_guardian_alerts_session_id', 'guardian_alerts', ['session_id'])


def downgrade() -> None:
    op.drop_index('ix_guardian_alerts_session_id', table_name='guardian_alerts')
    op.drop_table('guardian_alerts')
    op.drop_index('ix_guardian_sessions_user_id', table_name='guardian_sessions')
    op.drop_table('guardian_sessions')
    op.drop_index('ix_guardians_user_id', table_name='guardians')
    op.drop_table('guardians')
