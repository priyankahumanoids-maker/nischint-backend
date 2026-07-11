"""REL-04 — Postgres connection-pool introspection helpers.

Exposed as a small module of its own so any caller (the
`/admin/monitoring/runtime-info` endpoint, the threshold engine, the
incident-engine snapshotter, debug REPL sessions) can grab a fresh
read without re-implementing the SQLAlchemy pool plumbing.

Returns a plain dict — easy to JSON-serialise, easy to embed in the
snapshot table without a Pydantic schema dance.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_pool_stats() -> dict[str, Any]:
    """Snapshot the SQLAlchemy async engine's connection pool.

    Returns a stable shape — clients that read it from the runtime
    endpoint can treat missing keys as `None` (the engine may not be
    fully initialised yet during very early startup, in which case we
    return zeros + `available=False`).

    Keys:
      • pg_pool_size               — configured `pool_size`
      • pg_pool_max_overflow       — configured `max_overflow`
      • pg_pool_checked_out        — connections currently checked out
      • pg_pool_checked_in         — connections currently idle in pool
      • pg_pool_overflow           — extra connections beyond pool_size
                                    (0 = pool itself is not exhausted)
      • pg_pool_total_capacity     — pool_size + max_overflow (hard cap)
      • pg_pool_utilization_pct    — checked_out / total_capacity * 100
      • pg_pool_wait_count         — best-effort count of asyncio tasks
                                    currently blocked on
                                    `acquire()` (0 if not introspectable)
      • available                  — True iff the engine exposed its
                                    pool successfully
    """
    out: dict[str, Any] = {
        "pg_pool_size":            None,
        "pg_pool_max_overflow":    None,
        "pg_pool_checked_out":     None,
        "pg_pool_checked_in":      None,
        "pg_pool_overflow":        None,
        "pg_pool_total_capacity":  None,
        "pg_pool_utilization_pct": None,
        "pg_pool_wait_count":      None,
        "available":               False,
    }

    try:
        from app.db.session import engine
        # `engine.pool` is the sync_engine's pool — SQLAlchemy async
        # engines wrap a sync pool internally and expose it here.
        pool = engine.pool
    except Exception as e:
        logger.debug(f"[pool_stats] engine import failed: {e}")
        return out

    try:
        # Configured limits. `_pool` is the QueuePool's underlying
        # `queue.Queue` — its `maxsize` is the configured pool_size.
        pool_size = pool.size()
        # `_max_overflow` is private but stable across SQLAlchemy 1.4+/2.x.
        # We probe via getattr so a future refactor doesn't crash us.
        max_overflow = getattr(pool, "_max_overflow", None)
        checked_out = pool.checkedout()
        checked_in = pool.checkedin()
        overflow = pool.overflow()
        if max_overflow is not None and max_overflow >= 0:
            total_capacity = pool_size + max_overflow
        else:
            # max_overflow == -1 means unbounded; treat capacity as
            # current usage so utilization can't pretend to be 0.
            total_capacity = max(pool_size, checked_out + checked_in)
        if total_capacity > 0:
            util_pct = round(100.0 * checked_out / total_capacity, 2)
        else:
            util_pct = 0.0

        # Wait count — SQLAlchemy QueuePool doesn't directly expose a
        # "number of greenlets blocked on get()", but on the async
        # adapter (`AsyncAdaptedQueuePool`) the underlying asyncio
        # primitive has a `_waiters` list. Best-effort: read it if
        # present, default to 0.
        wait_count = 0
        try:
            # SQLAlchemy 2.x async pool exposes `_queue` (Queue) which
            # has a `_getters` deque on its asyncio.Queue.
            q = getattr(pool, "_queue", None) or getattr(pool, "_pool", None)
            getters = getattr(q, "_getters", None) if q is not None else None
            if getters is not None:
                wait_count = len(getters)
        except Exception:
            wait_count = 0

        out.update({
            "pg_pool_size":            int(pool_size),
            "pg_pool_max_overflow":    int(max_overflow) if max_overflow is not None else None,
            "pg_pool_checked_out":     int(checked_out),
            "pg_pool_checked_in":      int(checked_in),
            "pg_pool_overflow":        int(overflow),
            "pg_pool_total_capacity":  int(total_capacity),
            "pg_pool_utilization_pct": util_pct,
            "pg_pool_wait_count":      int(wait_count),
            "available":               True,
        })
    except Exception as e:
        logger.debug(f"[pool_stats] introspection failed: {e}")

    return out
