"""create reroute_suggestions table

Revision ID: j1a2b3c4d801
Revises: i1a2b3c4d701
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = 'j1a2b3c4d801'
down_revision = 'i1a2b3c4d701'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'reroute_suggestions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('trigger_risk_score', sa.Float(), nullable=False),
        sa.Column('trigger_risk_level', sa.String(20), nullable=False),
        sa.Column('trigger_type', sa.String(20), nullable=False),
        sa.Column('trigger_signals', JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('current_route_risk', sa.Float(), nullable=True),
        sa.Column('current_location_lat', sa.Float(), nullable=False),
        sa.Column('current_location_lng', sa.Float(), nullable=False),
        sa.Column('destination_lat', sa.Float(), nullable=True),
        sa.Column('destination_lng', sa.Float(), nullable=True),
        sa.Column('suggested_route_geometry', JSON(), nullable=True),
        sa.Column('suggested_route_risk', sa.Float(), nullable=True),
        sa.Column('suggested_route_distance_m', sa.Float(), nullable=True),
        sa.Column('suggested_route_duration_s', sa.Float(), nullable=True),
        sa.Column('eta_change_seconds', sa.Float(), nullable=True),
        sa.Column('safety_score_details', JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_reroute_user_status', 'reroute_suggestions', ['user_id', 'status'])
    op.create_index('ix_reroute_created', 'reroute_suggestions', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_reroute_created')
    op.drop_index('ix_reroute_user_status')
    op.drop_table('reroute_suggestions')
