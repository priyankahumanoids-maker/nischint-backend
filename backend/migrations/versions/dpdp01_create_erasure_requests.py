"""DPDP-01: erasure requests + user tombstone columns

Implements the data structures backing the self-serve erasure right
(DPDP Act 2023, §17). Adds:

  * `erasure_requests` — the audit log table. Each row is one request,
    survives the user's hard-delete (user_id is nullable, ON DELETE
    SET NULL) so we retain proof that the erasure was honoured.
  * `users.deleted_at` — soft-delete tombstone. Set at request time;
    cleared on cancel. While non-NULL, the user is "frozen" — reads
    and the cancel endpoint still work, but other writes are refused
    by the dep layer (see `app/api/deps.py`).
  * `users.erasure_status` — denormalised status of the user's active
    erasure request. Lets us answer "is this user mid-erasure?" with
    a single column read in the auth hot path (no JOIN).
  * `users.erasure_scheduled_for` — when the scheduled hard-delete
    job will fire. Indexed (partial) so the daily job can pick the
    due rows in O(due_count) instead of O(N).

Forward-compatible: down_revision points at the current head
`aa1b2c3d4ep01_emergency_stream_recording`.

Revision ID: dpdp01_erasure_requests
Revises: aa1b2c3d4ep01
Create Date: 2026-02-XX
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "dpdp01_erasure_requests"
down_revision = "aa1b2c3d4ep01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users tombstone columns ──────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("erasure_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("erasure_scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index — only ~tiny fraction of rows have a non-NULL value.
    # The daily scheduler reads with `WHERE erasure_scheduled_for <= now()`.
    op.create_index(
        "ix_users_erasure_scheduled_for",
        "users",
        ["erasure_scheduled_for"],
        postgresql_where=sa.text("erasure_scheduled_for IS NOT NULL"),
    )

    # ── erasure_requests table ───────────────────────────────────────
    op.create_table(
        "erasure_requests",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Nullable + ON DELETE SET NULL: when the user is hard-deleted
        # on day 30, we keep the audit row so we can prove the erasure
        # happened. `user_email` below survives for the same reason.
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # Denormalised — must survive the user row's deletion.
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("grace_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        # 'user' | 'admin' — populated when status moves out of 'pending'.
        sa.Column("cancellation_source", sa.String(50), nullable=True),
        # 'scheduled' | 'admin_approve'.
        sa.Column("completion_source", sa.String(50), nullable=True),
        # If admin approved, capture which admin.
        sa.Column(
            "completion_actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Audit metadata (DPDP §11 — proof of request authenticity).
        sa.Column("request_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("request_reason", sa.Text, nullable=True),
        # JSONB summary of what was deleted: tables, row counts, redis
        # keys cleared, mongo docs cleared. Lets us produce a proof-of-
        # erasure receipt later without rerunning the cascade.
        sa.Column("cascade_summary", JSONB, nullable=True),
    )

    # Composite index for the daily scheduler's hot query:
    #   SELECT id FROM erasure_requests
    #   WHERE status = 'pending' AND grace_expires_at <= now()
    op.create_index(
        "ix_erasure_requests_status_grace",
        "erasure_requests",
        ["status", "grace_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_erasure_requests_status_grace", table_name="erasure_requests")
    op.drop_table("erasure_requests")

    op.drop_index("ix_users_erasure_scheduled_for", table_name="users")
    op.drop_column("users", "erasure_scheduled_for")
    op.drop_column("users", "erasure_status")
    op.drop_column("users", "deleted_at")
