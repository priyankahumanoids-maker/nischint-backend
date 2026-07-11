"""SB-02 — user_signal_baselines materialised view.

Why this exists:
  Behavior baselines are stored device-grain (per-device per-hour).
  Every operator/admin read keyed by USER pays the join cost
  `users → seniors → devices → behavior_baselines` on every request.
  At fleet scale this dominates dashboard latency.

What this migration delivers:
  1. `user_signal_baselines` — MATERIALIZED VIEW that pre-joins
     the chain and exposes one row per (user_id, device_id,
     hour_of_day). Read path becomes a single keyed lookup.
  2. UNIQUE index on (user_id, device_id, hour_of_day) — REQUIRED
     for `REFRESH MATERIALIZED VIEW CONCURRENTLY` so the nightly
     refresh never blocks readers.
  3. Secondary indexes for the two operator hot paths:
       * (user_id, hour_of_day) — single-hour lookup
       * (user_id)              — full 24h profile
  4. `user_signal_baselines_meta` — single-row tracking table for
     the refresh scheduler. Stores last_refreshed_at,
     last_refresh_duration_ms, last_refresh_rows, last_status,
     last_error. Read by `GET /api/admin/baselines/status`.

Rollback semantics:
  * Downgrade drops the view + the meta table cleanly.
  * The underlying `behavior_baselines` table is NOT touched.
  * Reads that previously used the matview must fall back to the
    join chain (the service layer keeps both code paths viable).
"""
from __future__ import annotations

from alembic import op


revision = "sb02_user_signal_baselines_mv"
down_revision = "dpdp04_consents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Tracking table for refresh observability ───────────────
    # Single-row table (id=1) so the operator UI can read
    # last-refresh metadata in O(1).
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_signal_baselines_meta (
            id                       INTEGER PRIMARY KEY DEFAULT 1,
            last_refreshed_at        TIMESTAMPTZ,
            last_refresh_duration_ms DOUBLE PRECISION,
            last_refresh_rows        INTEGER,
            last_status              VARCHAR(16) NOT NULL DEFAULT 'unknown',
            last_error               TEXT,
            CONSTRAINT user_signal_baselines_meta_singleton CHECK (id = 1)
        );
    """)
    op.execute("""
        INSERT INTO user_signal_baselines_meta (id, last_status)
        VALUES (1, 'unknown')
        ON CONFLICT (id) DO NOTHING;
    """)

    # ── 2. The materialized view itself ───────────────────────────
    # Strict scope: pre-join, no aggregation. Aggregation per user
    # would lose the device dimension which is still useful on the
    # operator console (per-device drilldown). User-grain reads
    # that don't care about devices can `GROUP BY user_id` cheaply
    # because the rows are already keyed and indexed by user_id.
    # The matview exposes `user_id` (the role-bearing user) but the
    # underlying `seniors` schema names it `guardian_id` (the FK to
    # `users.id` for the guardian/parent role). We rename in the
    # projection so every downstream consumer queries by `user_id`
    # — the conceptual identifier — without coupling to the legacy
    # column name.
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS user_signal_baselines AS
        SELECT
            s.guardian_id          AS user_id,
            s.id                   AS senior_id,
            d.id                   AS device_id,
            d.device_identifier    AS device_identifier,
            d.device_type          AS device_type,
            d.status               AS device_status,
            b.hour_of_day          AS hour_of_day,
            b.avg_movement         AS avg_movement,
            b.std_movement         AS std_movement,
            b.avg_location_switch  AS avg_location_switch,
            b.std_location_switch  AS std_location_switch,
            b.avg_interaction_rate AS avg_interaction_rate,
            b.std_interaction_rate AS std_interaction_rate,
            b.sample_count         AS sample_count,
            b.updated_at           AS baseline_updated_at
        FROM behavior_baselines b
        JOIN devices d ON d.id = b.device_id
        JOIN seniors s ON s.id = d.senior_id
        WHERE s.guardian_id IS NOT NULL;
    """)

    # ── 3. Indexes ────────────────────────────────────────────────
    # The UNIQUE index is the prerequisite for `REFRESH MATERIALIZED
    # VIEW CONCURRENTLY`. (user_id, device_id, hour_of_day) is the
    # natural key — multiple devices per user are first-class.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_user_signal_baselines_uniq
        ON user_signal_baselines (user_id, device_id, hour_of_day);
    """)
    # Operator hot path #1: "give me this user's baseline for the
    # current hour" — single row lookup.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_signal_baselines_user_hour
        ON user_signal_baselines (user_id, hour_of_day);
    """)
    # Operator hot path #2: "give me this user's full 24h profile" —
    # range scan on user_id.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_signal_baselines_user
        ON user_signal_baselines (user_id);
    """)
    # Diagnostic path: reverse lookup by device for debugging.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_signal_baselines_device
        ON user_signal_baselines (device_id);
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS user_signal_baselines CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_signal_baselines_meta;")
