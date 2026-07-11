"""NISCH-006 Day 3+ — TTFA-by-state percentile aggregation.

Reads `safety_incident_events` and produces per-state p50 / p95 of
*transition latency* (ms between consecutive events on the same
incident). The output drives the operational guardian-responsiveness
KPI surfaced via `GET /api/_dev/ttfa/recent`.

Why a window function and not a stored column:

The `elapsed_ms` shown by `/api/incidents/:id/timeline` is computed
on-the-fly there too. We do NOT persist it on each event row to avoid
backfill complexity and to keep the events table append-only with a
single immutable shape. PostgreSQL's `LAG()` window function gives us
identical semantics on demand.

Genesis events (`from_state IS NULL`, no predecessor) are excluded —
they have no "elapsed" by definition. This matches the timeline
endpoint, where the first event always renders `elapsed_ms: 0` but
that 0 is a UI convention, NOT a real latency sample.

SQLite path: PostgreSQL-only `percentile_cont` + `make_interval` aren't
supported by sqlite3. We probe the bind dialect — under sqlite (test
suite only) we return `{}` so the test environment doesn't lie about
percentiles it can't compute.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Hard ceiling on the lookback window. A wider window is a full-table
# scan against an append-only events log — explicitly capped to keep
# the endpoint cheap and predictable.
MAX_WINDOW_HOURS = 168
DEFAULT_WINDOW_HOURS = 24


_PG_SQL = text(
    """
    WITH events_with_elapsed AS (
        SELECT
            split_part(ttfa_tag, ':', 2)        AS state,
            EXTRACT(EPOCH FROM (
                created_at - LAG(created_at) OVER (
                    PARTITION BY incident_id
                    ORDER BY created_at
                )
            )) * 1000.0                         AS elapsed_ms
        FROM safety_incident_events
        WHERE created_at > now() - make_interval(hours => :window_hours)
          AND ttfa_tag LIKE 'incident_state:%%'
    )
    SELECT
        state,
        COUNT(*)                                    AS samples,
        percentile_cont(0.5)
            WITHIN GROUP (ORDER BY elapsed_ms)      AS p50_ms,
        percentile_cont(0.95)
            WITHIN GROUP (ORDER BY elapsed_ms)      AS p95_ms
    FROM events_with_elapsed
    WHERE elapsed_ms IS NOT NULL
    GROUP BY state
    ORDER BY state
    """
)


async def get_state_stats(
    session: AsyncSession,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    """Return per-state percentile stats over the last `window_hours`.

    Shape:
        {
            "<state>": {"count": int, "p50_ms": int, "p95_ms": int},
            ...
        }

    Empty `{}` on:
      * non-postgres backend (test sqlite — see module docstring)
      * empty window (no events recorded)
      * any DB error (logged, never propagated — this is observability,
        not a data-integrity surface)
    """
    window_hours = max(1, min(int(window_hours), MAX_WINDOW_HOURS))
    try:
        bind = session.bind or session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return {}
    except Exception:
        return {}

    try:
        rows = (await session.execute(_PG_SQL, {"window_hours": window_hours})).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[TTFA_STATE_STATS] query failed (non-fatal): {e}")
        return {}

    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out[r.state] = {
            "count":  int(r.samples or 0),
            "p50_ms": int(r.p50_ms) if r.p50_ms is not None else 0,
            "p95_ms": int(r.p95_ms) if r.p95_ms is not None else 0,
        }
    return out


def computed_at() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "get_state_stats",
    "computed_at",
    "MAX_WINDOW_HOURS",
    "DEFAULT_WINDOW_HOURS",
]
