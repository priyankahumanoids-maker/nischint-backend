"""Migration: shadow tracking + push token reachability.

Two safety/observability primitives bundled into one migration because
they're both small and ship together:

  1. `shadow_location_pings` — failsafe trail. If a GPS ping arrives
     and the session can't be honored (no row found, terminal state,
     24-hour hard cap), we still capture the (user_id, lat, lng, ts)
     so we have a forensic trail and a way to recover. **Never blocks**
     on session-layer failures.

  2. `push_tokens` reachability columns — per-token operational health
     so the Command Center can render a guardian-reachability badge
     without scanning logs.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "y1a2b3c4dn01"
down_revision = "x1a2b3c4dm01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Shadow location pings (failsafe trail) ───────────────────────
    op.create_table(
        "shadow_location_pings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        # Why the ping landed in shadow:
        #   no_session       → session_id resolved to no row
        #   session_ended    → user-intent terminal (ended/completed)
        #   session_age_cap  → 24h zombie protection fired
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("ts",         sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_shadow_location_pings_user_ts",
                    "shadow_location_pings", ["user_id", "ts"])
    op.create_index("ix_shadow_location_pings_source",
                    "shadow_location_pings", ["source"])

    # ── push_tokens reachability columns ─────────────────────────────
    op.add_column("push_tokens",
                  sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("push_tokens",
                  sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("push_tokens",
                  sa.Column("consecutive_failures", sa.Integer,
                            nullable=False, server_default="0"))
    op.add_column("push_tokens",
                  sa.Column("last_failure_reason", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("push_tokens", "last_failure_reason")
    op.drop_column("push_tokens", "consecutive_failures")
    op.drop_column("push_tokens", "last_failure_at")
    op.drop_column("push_tokens", "last_success_at")
    op.drop_index("ix_shadow_location_pings_source",
                  table_name="shadow_location_pings")
    op.drop_index("ix_shadow_location_pings_user_ts",
                  table_name="shadow_location_pings")
    op.drop_table("shadow_location_pings")
