"""SB-02 — `user_signal_baselines` matview refresh scheduler.

Standalone module so it can be started/stopped independently and
discovered by `scheduler_runner.py` the same way every other
SB-* / DPDP-* scheduler is.

Schedule (locked):
  * Daily at **03:00 UTC** (≈ 08:30 IST — off-peak in India).
  * `REFRESH MATERIALIZED VIEW CONCURRENTLY` so reads stay
    unblocked during the refresh.
  * `misfire_grace_time=600` (10 min) — a missed window is
    acceptable, but skipping a whole day isn't.
  * `max_instances=1, coalesce=True` — multiple queued instances
    after a long blackout collapse into one run.

Never raises — refresh exceptions are recorded as metadata and
swallowed inside the service; the scheduler itself is just a
trigger.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import async_session
from app.services.user_signal_baseline_service import (
    refresh_user_signal_baselines,
)

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Locked job id so the scheduler-health metrics layer can find it.
JOB_ID = "user_signal_baselines_refresh"


async def _run_refresh_cycle() -> None:
    """Open a short-lived session, refresh, close. Never raises."""
    try:
        async with async_session() as session:
            result = await refresh_user_signal_baselines(session)
            logger.info(
                "[SB-02] nightly refresh complete status=%s duration_ms=%.0f rows=%d",
                result.get("status"),
                result.get("duration_ms") or 0,
                result.get("rows") or 0,
            )
    except Exception as e:  # noqa: BLE001 — never break the scheduler
        logger.warning("[SB-02] refresh cycle raised: %r", e)


def start_user_signal_baselines_scheduler() -> None:
    """Idempotent — repeat calls are no-ops once the scheduler
    is already running."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_refresh_cycle,
        "cron",
        hour=3, minute=0,
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    _scheduler.start()
    logger.info(
        "[SB-02] user_signal_baselines refresh scheduler started "
        "— daily at 03:00 UTC"
    )


def stop_user_signal_baselines_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


__all__ = [
    "JOB_ID",
    "start_user_signal_baselines_scheduler",
    "stop_user_signal_baselines_scheduler",
]
