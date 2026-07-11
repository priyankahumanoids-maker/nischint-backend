"""add guardian and invite columns to users

Revision ID: 86fa4ea2dbf0
Revises: oce01b_ai_confidence_history
Create Date: 2026-07-09 12:54:36.462437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86fa4ea2dbf0'
down_revision: Union[str, Sequence[str], None] = 'oce01b_ai_confidence_history'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('guardian_id', sa.UUID(), nullable=True))
    op.add_column('users', sa.Column('invite_code', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('invite_code_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_users_invite_code', 'users', ['invite_code'])
    op.create_foreign_key('fk_users_guardian_id', 'users', 'users', ['guardian_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_users_guardian_id', 'users', type_='foreignkey')
    op.drop_constraint('uq_users_invite_code', 'users', type_='unique')
    op.drop_column('users', 'invite_code_expires_at')
    op.drop_column('users', 'invite_code')
    op.drop_column('users', 'guardian_id')
