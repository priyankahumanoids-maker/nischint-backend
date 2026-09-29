"""Add Family Circle plan, seat and trial authority.

Revision ID: fc03_circle_plan_seat_trial
Revises: fc02_family_circle_authority
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "fc03_circle_plan_seat_trial"
down_revision = "fc02_family_circle_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("family_circles", sa.Column("plan", sa.String(length=20), nullable=True))
    op.add_column("family_circles", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("family_circles", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_family_circles_plan",
        "family_circles",
        "plan IS NULL OR plan IN ('trial', 'individual', 'family')",
    )

    op.add_column("circle_memberships", sa.Column("seat", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_circle_memberships_seat",
        "circle_memberships",
        "seat IS NULL OR seat IN ('protected', 'guardian', 'member')",
    )

    op.create_table(
        "family_trial_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("circle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("device_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["circle_id"], ["family_circles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_family_trial_claims_circle_id", "family_trial_claims", ["circle_id"])
    op.create_index("uq_family_trial_claim_phone", "family_trial_claims", ["phone_fingerprint"], unique=True)
    op.create_index("uq_family_trial_claim_device", "family_trial_claims", ["device_fingerprint"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_family_trial_claim_device", table_name="family_trial_claims")
    op.drop_index("uq_family_trial_claim_phone", table_name="family_trial_claims")
    op.drop_index("ix_family_trial_claims_circle_id", table_name="family_trial_claims")
    op.drop_table("family_trial_claims")
    op.drop_constraint("ck_circle_memberships_seat", "circle_memberships", type_="check")
    op.drop_column("circle_memberships", "seat")
    op.drop_constraint("ck_family_circles_plan", "family_circles", type_="check")
    op.drop_column("family_circles", "trial_ends_at")
    op.drop_column("family_circles", "trial_started_at")
    op.drop_column("family_circles", "plan")
