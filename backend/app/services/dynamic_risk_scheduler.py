# Dynamic City Risk Scheduler (Phase 39)
# Runs the risk pipeline every 5 minutes to maintain a live city safety heatmap.
# Architecture: Scheduler → Pipeline → Snapshot → Cache → API

import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import async_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
CYCLE_INTERVAL_MIN = 5


async def _run_dynamic_risk_cycle():
    """Background job: recompute city risk heatmap and update cache."""
    try:
        from app.services.dynamic_risk_engine import compute_city_risk_snapshot
        async with async_session() as session:
            result = await compute_city_risk_snapshot(session, city_id="default")
            delta = result.get("delta", {})
            logger.info(
                f"Dynamic Risk Cycle #{result.get('snapshot_number', 0)}: "
                f"{result['total_cells']} cells, {result['computation_time_ms']}ms, "
                f"escalated={delta.get('escalated_count', 0)}, "
                f"de-escalated={delta.get('de_escalated_count', 0)}"
            )
    except Exception as e:
        logger.error(f"Dynamic Risk Cycle error: {e}", exc_info=True)


def start_dynamic_risk_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    # First run 15 seconds after startup, then every 5 minutes
    first_run = datetime.now(timezone.utc) + timedelta(seconds=15)
    _scheduler.add_job(
        _run_dynamic_risk_cycle, "interval",
        minutes=CYCLE_INTERVAL_MIN,
        id="dynamic_risk_cycle",
        next_run_time=first_run,
        # Heavy CPU job — keep singleton, but absorb missed ticks and
        # collapse pile-up into a single catch-up run.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    _scheduler.start()
    logger.info(f"Dynamic Risk Scheduler started — cycle every {CYCLE_INTERVAL_MIN} min")


def stop_dynamic_risk_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Dynamic Risk Scheduler stopped")
