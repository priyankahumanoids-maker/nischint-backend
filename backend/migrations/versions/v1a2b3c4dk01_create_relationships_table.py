"""create relationships table

Revision ID: v1a2b3c4dk01
Revises: u1a2b3c4dj01
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "v1a2b3c4dk01"
down_revision = "u1a2b3c4dj01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("guardian_id", sa.Uuid(), nullable=False),
        sa.Column("child_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="accepted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["guardian_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("guardian_id", "child_id", name="uq_guardian_child"),
    )
    op.create_index("ix_relationships_guardian_id", "relationships", ["guardian_id"])
    op.create_index("ix_relationships_child_id", "relationships", ["child_id"])


def downgrade() -> None:
    op.drop_index("ix_relationships_child_id", table_name="relationships")
    op.drop_index("ix_relationships_guardian_id", table_name="relationships")
    op.drop_table("relationships")
