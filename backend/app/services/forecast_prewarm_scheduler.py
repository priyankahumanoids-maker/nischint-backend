# Risk Forecast Pre-Warming Scheduler
# Runs every 10 minutes to pre-compute forecasts for high-traffic zones.
# Ensures cache hit rate > 90% for common locations.

import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import async_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
PREWARM_INTERVAL_MIN = 10


async def _run_prewarm_cycle():
    """Background job: pre-compute forecasts for high-traffic zones."""
    try:
        from app.services.risk_forecast_engine import prewarm_forecasts
        async with async_session() as session:
            result = await prewarm_forecasts(session)
            logger.info(
                f"Forecast Prewarm: {result['warmed']} zones cached, "
                f"{result['errors']} errors"
            )
    except Exception as e:
        logger.error(f"Forecast Prewarm error: {e}", exc_info=True)


def start_forecast_prewarm_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    first_run = datetime.now(timezone.utc) + timedelta(seconds=30)
    _scheduler.add_job(
        _run_prewarm_cycle, "interval",
        minutes=PREWARM_INTERVAL_MIN,
        id="forecast_prewarm_cycle",
        next_run_time=first_run,
    )
    _scheduler.start()
    logger.info(f"Forecast Prewarm Scheduler started — cycle every {PREWARM_INTERVAL_MIN} min")


def stop_forecast_prewarm_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
