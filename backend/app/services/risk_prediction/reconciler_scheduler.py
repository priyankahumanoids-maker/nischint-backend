"""NISCH-010 — Prediction-ledger reconciler scheduler.

Runs `reconcile_outcomes` on a 15-min interval. Kept distinct
from the `RiskPredictionPrewarmer` (which is a
`ProviderPrewarmer` subclass on 1-h cadence) because the
reconciler:

  * has nothing to cache — its job is to WRITE actual_outcome
    back to the ledger
  * is not health-state-emitting — it's an audit job, not a
    provider health signal
  * runs more frequently (15 min vs 1 h) so accuracy data
    converges before the operator looks at it

Singleton APScheduler instance — `max_instances=1` blocks
overlapping ticks if the last run is still chewing through a
batch.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.session import async_session
from app.services.risk_prediction.reconciler import reconcile_outcomes

logger = logging.getLogger(__name__)

_SCHEDULER: Optional[AsyncIOScheduler] = None
_JOB_ID = "risk_prediction_reconciler"
RECONCILE_INTERVAL_S = 15 * 60       # 15 minutes
RECONCILE_BATCH_SIZE = 200


async def _run_once() -> None:
    """One reconciliation cycle. Defensive — never raises into
    APScheduler so a bad row doesn't stop future cycles."""
    try:
        async with async_session() as session:
            result = await reconcile_outcomes(
                session, batch_size=RECONCILE_BATCH_SIZE,
            )
            logger.info(
                "risk_prediction_reconciler_tick",
                extra={
                    "event": "risk_prediction_reconciler_tick",
                    "reconciled": result.get("reconciled", 0),
                    "batch_size": result.get("batch_size"),
                    "outcome_resolution_version":
                        result.get("outcome_resolution_version"),
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "risk_prediction_reconciler_tick_failed",
            extra={"event": "risk_prediction_reconciler_tick_failed",
                   "error_type": type(e).__name__},
        )


def start_risk_prediction_reconciler() -> None:
    """Register the 15-min job. Idempotent."""
    global _SCHEDULER
    if _SCHEDULER is not None:
        logger.info("risk_prediction_reconciler already running")
        return
    _SCHEDULER = AsyncIOScheduler()
    _SCHEDULER.add_job(
        _run_once,
        trigger=IntervalTrigger(seconds=RECONCILE_INTERVAL_S),
        id=_JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        replace_existing=True,
    )
    _SCHEDULER.start()
    logger.info(
        "risk_prediction_reconciler started — interval=%ds",
        RECONCILE_INTERVAL_S,
    )


def stop_risk_prediction_reconciler() -> None:
    global _SCHEDULER
    if _SCHEDULER is None:
        return
    try:
        _SCHEDULER.shutdown(wait=False)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "risk_prediction_reconciler_shutdown_failed: %r", e,
        )
    finally:
        _SCHEDULER = None


__all__ = [
    "start_risk_prediction_reconciler",
    "stop_risk_prediction_reconciler",
    "RECONCILE_INTERVAL_S",
    "RECONCILE_BATCH_SIZE",
]
