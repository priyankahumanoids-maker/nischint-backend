"""REL-04 P1 — uvicorn-side publisher for SQLAlchemy pool stats.

Why a separate publisher?

The backend runs two Python processes:
  - uvicorn (`role=api`)         — handles user HTTP traffic. Has its
                                    own SQLAlchemy engine + connection
                                    pool. Drains under load.
  - `nischint-scheduler` (`role=scheduler`) — runs APScheduler jobs
                                    including `db_pool_monitor`. Has
                                    its own engine + pool, almost
                                    always idle.

Before this publisher existed, `db_pool_monitor` polled only the
scheduler's local pool, so a user-traffic-driven pool exhaustion in
the uvicorn process was invisible to the threshold engine — no
`system_incident(database_pool)` ever fired (verified by the
2026-05-30 DR drill).

This module runs **inside the uvicorn process** and, every
`PUBLISH_INTERVAL_S` seconds, writes the current pool snapshot to a
Redis key. The scheduler-side `db_pool_monitor` then reads that key in
its own tick and feeds the worst-of (local OR uvicorn) into the
threshold engine.

If Redis is unavailable, the publisher is a silent no-op — it must
never crash the request loop. Conversely, if the uvicorn process dies,
the published value will expire after `PUBLISH_KEY_TTL_S` seconds and
the scheduler will simply fall back to its own local reading (same
behaviour as before this publisher existed).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Tick faster than the scheduler-side monitor's 15 s sample so the
# scheduler always has a fresh reading to consume.
PUBLISH_INTERVAL_S = 5

# Slightly longer than 2× publish interval so a single missed tick
# doesn't make the scheduler think the publisher died. The scheduler
# treats an expired/missing key as "no uvicorn data — use local only".
PUBLISH_KEY_TTL_S = 15

# Redis namespace + key used by both the publisher (write) and the
# scheduler-side monitor (read). Keep stable — both processes must
# agree on the key.
REDIS_NAMESPACE = "pool_stats"
REDIS_KEY_UVICORN = "uvicorn"

_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


async def _publish_once() -> None:
    """Single publish cycle: snapshot pool → write to Redis with TTL."""
    try:
        from app.db.pool_stats import get_pool_stats
        from app.services import redis_service
        stats = get_pool_stats()
        if not stats.get("available"):
            return  # pool not initialised yet, skip
        # Tag the payload with `source` so a downstream consumer can
        # tell at a glance who wrote it (useful when we add a second
        # uvicorn worker in the future).
        payload = dict(stats)
        payload["source"] = "uvicorn"
        redis_service.set_json(REDIS_NAMESPACE, REDIS_KEY_UVICORN, payload, ttl=PUBLISH_KEY_TTL_S)
    except Exception as e:
        # Never raise from the publisher. A Redis blip must not crash
        # the API process — Sentry will see this through normal handler
        # paths if Redis is broken broadly.
        logger.debug(f"[pool_stats_publisher] publish failed: {e}")


async def _ticker_loop(stop_event: asyncio.Event) -> None:
    """Forever-loop publisher. Stops cleanly when `stop_event` is set."""
    logger.info(
        "[REL-04-P1] uvicorn pool_stats publisher started "
        f"interval={PUBLISH_INTERVAL_S}s ttl={PUBLISH_KEY_TTL_S}s"
    )
    while not stop_event.is_set():
        await _publish_once()
        try:
            # `wait_for` lets the stop signal interrupt the sleep so a
            # supervisor shutdown doesn't wait the full interval.
            await asyncio.wait_for(stop_event.wait(), timeout=PUBLISH_INTERVAL_S)
        except asyncio.TimeoutError:
            pass  # normal — interval elapsed, loop again
    logger.info("[REL-04-P1] uvicorn pool_stats publisher stopped")


def start_pool_stats_publisher() -> None:
    """Spawn the publisher task on the current event loop.

    Idempotent — calling twice replaces the previous task. Designed to
    be called from the FastAPI startup hook in `server.py`. If called
    outside an async context (no running loop), logs a warning and
    no-ops.
    """
    global _task, _stop_event
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        logger.warning("[REL-04-P1] no running event loop — publisher not started")
        return

    # Stop a previous task before replacing it
    if _task is not None and not _task.done():
        if _stop_event is not None:
            _stop_event.set()

    _stop_event = asyncio.Event()
    _task = loop.create_task(_ticker_loop(_stop_event), name="pool_stats_publisher")


async def stop_pool_stats_publisher() -> None:
    """Cleanly stop the publisher — called from the FastAPI shutdown hook.

    Best-effort. If the task is already done or absent, returns
    immediately.
    """
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug(f"[REL-04-P1] publisher stop error: {e}")
    _task = None
    _stop_event = None
