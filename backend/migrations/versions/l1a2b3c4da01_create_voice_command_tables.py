"""create voice command tables

Revision ID: l1a2b3c4da01
Revises: k1a2b3c4d901
Create Date: 2026-03-08 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "l1a2b3c4da01"
down_revision = "k1a2b3c4d901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "voice_command_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("phrase", sa.String(200), nullable=False),
        sa.Column("linked_action", sa.String(50), nullable=False),
        sa.Column("action_config", sa.Text(), nullable=True),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "voice_trigger_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("command_id", sa.Uuid(), sa.ForeignKey("voice_command_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transcribed_text", sa.Text(), nullable=False),
        sa.Column("matched_phrase", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("linked_action", sa.String(50), nullable=True),
        sa.Column("triggered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(30), nullable=False, server_default="'processed'"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("voice_trigger_logs")
    op.drop_table("voice_command_configs")
