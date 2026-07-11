"""add guardian ai refinement tables

Revision ID: 1d6a38a1602c
Revises: r1a2b3c4dg01
Create Date: 2026-03-09 03:42:22.329336

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1d6a38a1602c'
down_revision: Union[str, Sequence[str], None] = 'r1a2b3c4dg01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('guardian_baselines',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('active_hours', sa.JSON(), nullable=False),
    sa.Column('avg_daily_distance', sa.Float(), nullable=False),
    sa.Column('common_locations', sa.JSON(), nullable=False),
    sa.Column('route_clusters', sa.JSON(), nullable=False),
    sa.Column('avg_device_uptime', sa.Float(), nullable=False),
    sa.Column('avg_battery_drop', sa.Float(), nullable=False),
    sa.Column('avg_signal_loss_events', sa.Float(), nullable=False),
    sa.Column('normal_alerts_per_day', sa.Float(), nullable=False),
    sa.Column('normal_incidents_per_week', sa.Float(), nullable=False),
    sa.Column('avg_caregiver_visits_per_week', sa.Float(), nullable=False),
    sa.Column('data_days', sa.Integer(), nullable=False),
    sa.Column('is_seeded', sa.Boolean(), nullable=False),
    sa.Column('last_computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_guardian_baselines_user_id'), 'guardian_baselines', ['user_id'], unique=True)

    op.create_table('guardian_predictions_v2',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('prediction_type', sa.String(length=50), nullable=False),
    sa.Column('prediction_window_minutes', sa.Integer(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('predicted_risk_level', sa.String(length=20), nullable=False),
    sa.Column('recommended_action', sa.String(length=50), nullable=False),
    sa.Column('reasoning', sa.Text(), nullable=True),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_guardian_predictions_v2_user_id'), 'guardian_predictions_v2', ['user_id'], unique=False)

    op.create_table('guardian_risk_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('baseline_deviation', sa.Float(), nullable=False),
    sa.Column('location_risk', sa.Float(), nullable=False),
    sa.Column('device_risk', sa.Float(), nullable=False),
    sa.Column('environment_risk', sa.Float(), nullable=False),
    sa.Column('response_risk', sa.Float(), nullable=False),
    sa.Column('final_risk_score', sa.Float(), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('top_factors', sa.JSON(), nullable=False),
    sa.Column('recommended_action', sa.String(length=50), nullable=False),
    sa.Column('incident_created', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_guardian_risk_events_timestamp'), 'guardian_risk_events', ['timestamp'], unique=False)
    op.create_index(op.f('ix_guardian_risk_events_user_id'), 'guardian_risk_events', ['user_id'], unique=False)

    op.create_table('guardian_risk_scores',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('behavior_score', sa.Float(), nullable=False),
    sa.Column('location_score', sa.Float(), nullable=False),
    sa.Column('device_score', sa.Float(), nullable=False),
    sa.Column('environment_score', sa.Float(), nullable=False),
    sa.Column('response_score', sa.Float(), nullable=False),
    sa.Column('final_score', sa.Float(), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('top_factors', sa.JSON(), nullable=False),
    sa.Column('recommended_action', sa.String(length=50), nullable=False),
    sa.Column('action_detail', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_guardian_risk_scores_timestamp'), 'guardian_risk_scores', ['timestamp'], unique=False)
    op.create_index(op.f('ix_guardian_risk_scores_user_id'), 'guardian_risk_scores', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('guardian_risk_scores')
    op.drop_table('guardian_risk_events')
    op.drop_table('guardian_predictions_v2')
    op.drop_table('guardian_baselines')
