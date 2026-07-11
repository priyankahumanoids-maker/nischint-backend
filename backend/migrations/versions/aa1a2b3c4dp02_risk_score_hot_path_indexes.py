"""Add indexes to support compute_risk_score hot path.

Refactor of `compute_risk_score` (June 2026) batches 5+ scattered
sub-score queries into a single SELECT with 4 scalar-subquery COUNTs +
2 row_to_json fetches. In the preview environment those COUNTs are
trivial sequential scans (tiny tables), but in production each one
benefits from a targeted index. None of these tables are write-heavy
on these columns, so the index overhead is negligible.

Targeted queries (all from `_prefetch_risk_inputs`):
  1. `guardian_alerts WHERE created_at >= NOW() - INTERVAL '24h'`
     → fleet-wide rolling-window count, hits the hottest write-path
       table. Single-column index on `created_at`.

  2. `incidents WHERE created_at >= NOW() - INTERVAL '6h'
                AND incident_type IN ('device_offline', 'low_battery', 'signal_lost')
                AND is_test = false`
     → device-incident count for the last 6h. Composite
       `(created_at, incident_type)` is enough; the `is_test=false`
       filter discards <1% of rows in prod and is fine to evaluate
       on the heap.

  3. `incidents WHERE status='open'
                AND created_at >= NOW() - INTERVAL '2h'
                AND acknowledged_at IS NULL`
     → unacked-alert count. Partial index covers exactly the rows we
       care about (`acknowledged_at IS NULL`) so it stays small even
       as the table grows.

  4. `caregiver_statuses WHERE status='available'`
     → caregiver-availability count. Partial index on the small
       'available' subset is ideal.

All indexes use `IF NOT EXISTS` so the migration is idempotent and
safe to re-run.
"""
from __future__ import annotations

from alembic import op


revision = "aa1a2b3c4dp02"
down_revision = "aa1a2b3c4dp01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. guardian_alerts(created_at) — fleet-wide rolling-window count
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_guardian_alerts_created_at
        ON guardian_alerts (created_at DESC)
    """)

    # 2. incidents(created_at, incident_type) — device incident count
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_incidents_created_at_type
        ON incidents (created_at DESC, incident_type)
    """)

    # 3. incidents partial — unacked open incidents in last 2h
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_incidents_open_unacked
        ON incidents (status, created_at DESC)
        WHERE acknowledged_at IS NULL AND status = 'open'
    """)

    # 4. caregiver_statuses partial — available caregivers
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_caregiver_statuses_available
        ON caregiver_statuses (status)
        WHERE status = 'available'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_caregiver_statuses_available")
    op.execute("DROP INDEX IF EXISTS ix_incidents_open_unacked")
    op.execute("DROP INDEX IF EXISTS ix_incidents_created_at_type")
    op.execute("DROP INDEX IF EXISTS ix_guardian_alerts_created_at")
