"""Add Family Circle and membership authority for Family Circle v1.0.

Revision ID: fc02_family_circle_authority
Revises: fc01_user_date_of_birth
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fc02_family_circle_authority"
down_revision = "fc01_user_date_of_birth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "family_circles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('active', 'closed')", name="ck_family_circles_status"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_family_circles_owner_user_id", "family_circles", ["owner_user_id"])

    op.create_table(
        "circle_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("circle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('owner', 'co_admin', 'adult_member', 'minor')",
            name="ck_circle_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'left', 'removed')",
            name="ck_circle_memberships_status",
        ),
        sa.ForeignKeyConstraint(["circle_id"], ["family_circles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_circle_memberships_circle_id", "circle_memberships", ["circle_id"])
    op.create_index("ix_circle_memberships_user_id", "circle_memberships", ["user_id"])
    op.create_index(
        "uq_circle_membership_one_active_circle_per_user",
        "circle_memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_circle_membership_one_active_owner",
        "circle_memberships",
        ["circle_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND role = 'owner'"),
    )
    op.create_index(
        "uq_circle_membership_one_active_co_admin",
        "circle_memberships",
        ["circle_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND role = 'co_admin'"),
    )


def downgrade() -> None:
    op.drop_index("uq_circle_membership_one_active_co_admin", table_name="circle_memberships")
    op.drop_index("uq_circle_membership_one_active_owner", table_name="circle_memberships")
    op.drop_index("uq_circle_membership_one_active_circle_per_user", table_name="circle_memberships")
    op.drop_index("ix_circle_memberships_user_id", table_name="circle_memberships")
    op.drop_index("ix_circle_memberships_circle_id", table_name="circle_memberships")
    op.drop_table("circle_memberships")
    op.drop_index("ix_family_circles_owner_user_id", table_name="family_circles")
    op.drop_table("family_circles")
