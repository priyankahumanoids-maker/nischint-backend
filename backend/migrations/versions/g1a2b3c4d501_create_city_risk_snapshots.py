"""Create city_risk_snapshots table

Revision ID: g1a2b3c4d501
Revises: ee1f0143ad41
Create Date: 2026-03-07

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "g1a2b3c4d501"
down_revision = "ee1f0143ad41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "city_risk_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("city_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("snapshot_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_cells", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_zones", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_incidents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("cells", sa.JSON(), nullable=True),
        sa.Column("delta", sa.JSON(), nullable=True),
        sa.Column("weights", sa.JSON(), nullable=True),
        sa.Column("weight_profile", sa.String(), nullable=True),
        sa.Column("bounds", sa.JSON(), nullable=True),
        sa.Column("computation_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_city_risk_snapshots_city_id", "city_risk_snapshots", ["city_id"])
    op.create_index("ix_city_risk_snapshots_timestamp", "city_risk_snapshots", ["snapshot_timestamp"])


def downgrade() -> None:
    op.drop_table("city_risk_snapshots")
