"""DPDP-04: consents table + indices

Per DPDP Act 2023 §6 ("notice and consent"), each personal-data
category requires a separately-revocable consent record. This table is
the source of truth for whether a user has granted, when, and for which
purpose.

Schema choices:
  * `id` UUID — pk, surrogate.
  * `(user_id, category)` is UNIQUE — at most one row per user per
    category. Grants flip `revoked_at` from non-NULL → NULL; revokes
    flip it back. Historical changes go to a separate `consent_audit`
    table (out of scope for v1; the per-row timestamps are sufficient
    for the current §6 requirement).
  * `category` is a free-string. The application layer constrains it
    to the enum in `app.services.consent_service.CATEGORIES` so we can
    add new categories without a migration.
  * `consent_text_version` is mandatory. Lets us prove which version
    of the consent text the user agreed to (§11.3 — informed consent).

Foreign-key cascade: ON DELETE CASCADE on user_id, so the DPDP-01
erasure flow auto-removes consent rows.

Revision ID: dpdp04_consents
Revises: dpdp01_erasure_requests
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "dpdp04_consents"
down_revision = "dpdp01_erasure_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("app_version", sa.String(40), nullable=True),
        sa.Column("consent_text_version", sa.String(20), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.UniqueConstraint("user_id", "category", name="uq_consents_user_category"),
    )
    op.create_index(
        "ix_consents_active",
        "consents",
        ["user_id", "category"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_consents_active", table_name="consents")
    op.drop_table("consents")
