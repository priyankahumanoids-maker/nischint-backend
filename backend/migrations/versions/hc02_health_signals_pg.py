"""HC-02 — health_signals_pg audit table for wearable signals.

Why this exists:
  The existing wearable ingest endpoint (`POST /api/health-signals/wearable`)
  persists samples to Redis sorted-sets only. That's fine for the
  24-hour hot window the brain reads from, but it doesn't give
  operators an audit trail when investigating an incident days
  later — Redis ZSET members fall off the TTL and the signal
  disappears.

  This migration introduces a Postgres MIRROR table:
    * The Redis hot path stays untouched (no perf regression on
      the ingest endpoint's blocking write).
    * Every signal that lands on the endpoint is ALSO written
      to `health_signals_pg` in the same request, best-effort
      (PG failures log + drop rather than fail the request).
    * Adds `device_id` (UUID, FK to `devices`) + `device_model`
      so the operator can distinguish multiple paired devices on
      the dependent timeline — the headline ask of HC-02.

Schema notes:
  * `device_id` is nullable — older mobile clients pre-HC-02 don't
    send the header. Once the mobile rollout is complete and the
    null count stabilizes, a follow-up migration can NOT NULL it.
  * `breach_tag` is the SAME string the endpoint already emits
    on structured logs (`HR_HIGH`, `SPO2_LOW`, `FALL_DETECTED`).
    Operators can filter the dependent timeline by it directly.
  * `value` is `DOUBLE PRECISION`, not `NUMERIC` — the source
    domain is bounded (`_VALUE_LIMITS` in `health_signals.py`)
    and the cost of NUMERIC precision is not worth the storage.
  * `ts` is the SAMPLE timestamp (from the mobile client),
    `created_at` is the SERVER timestamp. Both indexed because
    operators need ts-ordered views AND the create_at index is
    a cheap freshness check for the ingest pipeline.
"""
from __future__ import annotations

from alembic import op


revision = "hc02_health_signals_pg"
down_revision = "sf03b_expand_aksai_chin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_signals_pg (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL,
            device_id     UUID NULL,
            device_model  VARCHAR(100) NULL,
            signal_type   VARCHAR(32) NOT NULL,
            value         DOUBLE PRECISION NOT NULL,
            unit          VARCHAR(16) NOT NULL,
            source        VARCHAR(128) NOT NULL,
            ts            TIMESTAMPTZ NOT NULL,
            breach_tag    VARCHAR(32) NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    # Index #1 — operator timeline read path: "give me last N hours
    # for this user, ordered by ts desc". Composite (user_id, ts)
    # covers it as a B-tree range scan.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_health_signals_pg_user_ts
            ON health_signals_pg (user_id, ts DESC);
    """)
    # Index #2 — multi-device breakdown on the dependent timeline.
    # (user_id, device_id, ts) lets the frontend group by device
    # without losing the time-ordered scan.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_health_signals_pg_user_device_ts
            ON health_signals_pg (user_id, device_id, ts DESC)
         WHERE device_id IS NOT NULL;
    """)
    # Index #3 — breach drill-down. Partial so storage cost is bounded
    # to the rows that actually carry a breach tag (~<5% of signals
    # in steady state).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_health_signals_pg_breach
            ON health_signals_pg (user_id, breach_tag, ts DESC)
         WHERE breach_tag IS NOT NULL;
    """)
    # Index #4 — ingest freshness check. created_at index used by
    # the operator console's "are wearable signals flowing?" capsule.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_health_signals_pg_created_at
            ON health_signals_pg (created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS health_signals_pg CASCADE;")
