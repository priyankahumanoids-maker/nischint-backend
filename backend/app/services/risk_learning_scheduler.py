# Risk Learning Scheduler
# Periodically runs the adaptive risk engine to update learned hotspot zones.

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import async_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_risk_learning():
    """Background job: analyze incidents and update hotspot zones."""
    try:
        from app.services.adaptive_risk_engine import analyze_and_update_hotspots
        async with async_session() as session:
            stats = await analyze_and_update_hotspots(session)
            logger.info(
                f"Risk Learning: {stats['hotspots_created']} hotspots from "
                f"{stats['incidents_analyzed']} incidents"
            )
    except Exception as e:
        logger.error(f"Risk Learning job error: {e}")


def start_risk_learning_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    # Run every 6 hours, first run after 30 seconds
    _scheduler.add_job(_run_risk_learning, "interval", hours=6, id="risk_learning",
                       next_run_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                       + __import__("datetime").timedelta(seconds=30))
    _scheduler.start()
    logger.info("Risk Learning scheduler started, polling every 6 hours")


def stop_risk_learning_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Risk Learning scheduler stopped")
