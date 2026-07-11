"""REL-04 — pg_stat_activity capture for pool-exhaustion post-mortems.

Runs through the dedicated `app.db.session.get_db_pool()` asyncpg pool
(min_size=2, max_size=10) which is **independent** of the saturated
SQLAlchemy pool. That independence is the whole point of this module:
when the ORM pool tips over 85% we still need a connection to ask
Postgres "what queries are eating you alive?". An asyncpg pool that
shares the same DSN but its own slot budget gives us that escape hatch.

Output shape (each row):
  • pid               — server-side PID, useful for `pg_terminate_backend`
  • duration_ms       — `now() - query_start` in milliseconds (float)
  • state             — 'active' | 'idle in transaction' | 'idle' | ...
  • wait_event_type   — 'Lock' | 'IO' | 'Client' | 'IPC' | NULL
  • wait_event        — specific wait event when wait_event_type != NULL
  • application_name  — client app label
  • usename           — postgres role
  • query             — first 1KB of the query text (truncated to keep
                        snapshot rows JSON-small)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Default: top 5 longest-running queries. Kept as a tunable so future
# callers can dial it down (e.g. for a frequently-firing dashboard
# widget) or up (a forensic post-mortem export).
DEFAULT_LIMIT = 5

# Query text truncation. pg_stat_activity returns the full query, which
# can be megabytes for ORM-generated `IN (...)` blobs. Truncating to
# 1KB keeps the JSONB column compact while still preserving the SQL
# fingerprint.
QUERY_TRUNCATE_BYTES = 1024


_SQL = """
SELECT
    pid,
    EXTRACT(EPOCH FROM (now() - query_start)) * 1000 AS duration_ms,
    state,
    wait_event_type,
    wait_event,
    application_name,
    usename,
    LEFT(query, $1) AS query
FROM pg_stat_activity
WHERE
    pid <> pg_backend_pid()              -- never capture the diagnostic itself
    AND state IS NOT NULL
    AND state <> 'idle'                  -- idle backends aren't holding work
    AND query_start IS NOT NULL
    AND datname = current_database()      -- restrict to our DB only
ORDER BY query_start ASC                  -- oldest start = longest-running
LIMIT $2;
"""


async def capture_top_queries(limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Snapshot the longest-running queries on the current database.

    Returns `[]` on any failure — this is a *diagnostic* path, never
    a hot path, so we never propagate. A noisy WARNING log is the
    price of a missing snapshot row.
    """
    try:
        from app.db.session import get_db_pool
        pool = await get_db_pool()
    except Exception as e:
        logger.debug(f"[pg_diag] could not acquire diagnostic pool: {e}")
        return []

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SQL, QUERY_TRUNCATE_BYTES, limit)
    except Exception as e:
        logger.warning(f"[pg_diag] pg_stat_activity query failed: {e}")
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        # asyncpg returns Record — coerce to plain dict so callers can
        # json.dumps() the result without bespoke encoders.
        dur = r["duration_ms"]
        try:
            dur = round(float(dur), 2) if dur is not None else None
        except (TypeError, ValueError):
            dur = None
        out.append({
            "pid":              r["pid"],
            "duration_ms":      dur,
            "state":            r["state"],
            "wait_event_type":  r["wait_event_type"],
            "wait_event":       r["wait_event"],
            "application_name": r["application_name"],
            "usename":          r["usename"],
            "query":            r["query"],
        })
    return out
