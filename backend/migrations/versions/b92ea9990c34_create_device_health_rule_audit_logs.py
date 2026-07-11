"""create_device_health_rule_audit_logs

Revision ID: b92ea9990c34
Revises: 54b31423359a
Create Date: 2026-02-28 12:37:19.903903

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b92ea9990c34'
down_revision: Union[str, Sequence[str], None] = '54b31423359a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('device_health_rule_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rule_name', sa.String(length=100), nullable=False),
        sa.Column('changed_by', sa.UUID(), nullable=False),
        sa.Column('changed_by_name', sa.String(length=150), nullable=True),
        sa.Column('change_type', sa.String(length=20), nullable=False),
        sa.Column('old_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('new_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('device_health_rule_audit_logs')
