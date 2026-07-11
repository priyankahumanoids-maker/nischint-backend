"""OCE-01b — `ai_confidence_history` table.

One row per (user_id, snapshot_date). The daily scheduler writes one
row per active user; the `/api/ai/confidence/{user_id}` endpoint reads
back the last 7 days for a sparkline + trend.

Why a separate table (not e.g. a Redis sorted set):
  * Persistent across Redis restarts / cache flushes.
  * Operator queryable (joinable with users, seniors) for ad-hoc
    investigation: "show me users whose AI confidence dropped > 0.1
    yesterday".
  * Cheap — at fleet scale (10K active users × 365 days = 3.6M rows
    with TINY rows ~80 bytes; the index is the dominant cost).
"""
from __future__ import annotations

from alembic import op


revision = "oce01b_ai_confidence_history"
down_revision = "sf03d_arunachal_union"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_confidence_history (
            user_id            UUID NOT NULL,
            snapshot_date      DATE NOT NULL,
            overall_confidence DOUBLE PRECISION NOT NULL,
            twin_confidence    DOUBLE PRECISION NOT NULL,
            telemetry_quality  DOUBLE PRECISION NOT NULL,
            behavioral_match   DOUBLE PRECISION NOT NULL,
            attenuation_factor DOUBLE PRECISION NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, snapshot_date)
        );
    """)
    # Hot path: read last 7 days for a single user — already covered
    # by the PK (user_id is leading column). Add an index on date
    # alone for the operator-side "show me everyone who regressed
    # yesterday" query.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_ai_confidence_history_date
            ON ai_confidence_history (snapshot_date DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_confidence_history;")
