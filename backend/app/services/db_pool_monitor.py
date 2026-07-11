"""REL-04 — DB pool monitor scheduler.

Polls `get_pool_stats()` every `POLL_INTERVAL_S` seconds and feeds the
result into the threshold engine's `evaluate_db_pool_state`. The
threshold engine applies the consecutive-readings hysteresis and
fires `system_health_delta` on transitions only.

Why a dedicated polling tick instead of piggy-backing on /runtime-info?
The runtime-info endpoint is operator-driven — there's no guarantee it
fires often enough (or at all) on a quiet day, but pool exhaustion
happens on the busy days when nobody's looking at the dashboard. A
small 15 s tick guarantees coverage.

This module is intentionally thin: it owns the schedule and the
log-level chatter, nothing else. The classification + emission logic
lives in `health_thresholds.evaluate_db_pool_state`.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Tighter than the operator dashboard's 30 s — pool exhaustion can
# escalate fast (every blocked acquire spawns a backlog), so we want
# to see two consecutive over-threshold readings within ~30 s.
POLL_INTERVAL_S = 15

_scheduler = None  # type: ignore[assignment]


def _read_uvicorn_pool_stats() -> dict | None:
    """Fetch the latest uvicorn-process pool snapshot from Redis.

    Returns the parsed dict, or `None` if Redis is unavailable or the
    publisher hasn't written anything in `PUBLISH_KEY_TTL_S` seconds.
    Silent on all errors — the local-only path remains correct.
    """
    try:
        from app.services import redis_service
        from app.services.pool_stats_publisher import (
            REDIS_NAMESPACE, REDIS_KEY_UVICORN,
        )
        return redis_service.get_json(REDIS_NAMESPACE, REDIS_KEY_UVICORN)
    except Exception:
        return None


def _worst_of(local: dict, remote: dict | None) -> dict:
    """Pick whichever snapshot reports HIGHER utilisation.

    The threshold engine looks at `pg_pool_utilization_pct`; "worst-of"
    means the highest util across the two pools, so a saturated uvicorn
    pool wins over an idle scheduler pool (the original bug).

    If `remote` is None or missing the util field, returns `local`
    unchanged — back-compatible with the pre-publisher behaviour.
    """
    if not remote:
        return local
    remote_util = remote.get("pg_pool_utilization_pct")
    local_util = local.get("pg_pool_utilization_pct")
    if remote_util is None:
        return local
    if local_util is None or remote_util > local_util:
        # Pass through the remote snapshot, but tag the source so the
        # incident payload can show *which* pool drove the decision.
        out = dict(remote)
        out["source"] = remote.get("source", "uvicorn")
        return out
    return local


def _tick() -> None:
    """Single poll: read pool stats (local + uvicorn) → hand off to threshold engine.

    Wrapped in a try/except so a transient SQLAlchemy error never kills
    the recurring job. APScheduler would also auto-recover, but
    surfacing the failure as a single WARNING log line is cleaner than
    a stack-trace per tick.
    """
    try:
        from app.db.pool_stats import get_pool_stats
        from app.services.health_thresholds import evaluate_db_pool_state
        local = get_pool_stats()
        if not local.get("available"):
            return
        # Augment with uvicorn-process reading (REL-04 P1)
        remote = _read_uvicorn_pool_stats()
        snapshot = _worst_of(local, remote)
        util = snapshot.get("pg_pool_utilization_pct")
        evaluate_db_pool_state(util, snapshot=snapshot)
    except Exception as e:
        logger.warning(f"[REL-04] db_pool_monitor tick failed: {e}")


def start_db_pool_monitor() -> None:
    """Register the recurring tick. Idempotent — calling twice replaces
    the existing job (same `replace_existing=True` semantics used by
    every other scheduler in this codebase).
    """
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            _tick,
            IntervalTrigger(seconds=POLL_INTERVAL_S),
            id="db_pool_monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info(
            f"[REL-04] db_pool_monitor registered — interval={POLL_INTERVAL_S}s"
        )
    except ImportError:
        logger.warning("[REL-04] apscheduler not available — db_pool_monitor disabled")
    except Exception as e:
        logger.error(f"[REL-04] db_pool_monitor setup failed: {e}")


def stop_db_pool_monitor() -> None:
    """Counterpart for clean shutdown."""
    global _scheduler
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("[REL-04] db_pool_monitor stopped")
    except Exception as e:
        logger.debug(f"[REL-04] db_pool_monitor stop failed: {e}")


# Test seam — invoke a single tick synchronously.
def _tick_for_test() -> None:
    _tick()
