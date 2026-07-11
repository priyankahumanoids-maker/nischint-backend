"""REL-05 — Periodic WebSocket leak audit.

Once per `SWEEP_INTERVAL_S` seconds, calls
`ws_command_center.sweep_dead_cc_connections()` to:
  1. probe every socket in `_cc_connections` with a ping frame,
  2. discard any that raise WebSocketDisconnect, raise any other
     error during send, or whose `client_state != CONNECTED`.

Without this, a load-balancer-side connection drop (no FIN frame
delivered) can leave dead sockets sitting in `_cc_connections`
forever, slowly leaking memory + producing useless broadcast
attempts. The sweeper bounds the leak window to the interval.

The job uses APScheduler — same pattern as `db_pool_monitor`,
`dpdp_digest`, etc.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# 60 s matches the broadcaster's own dead-socket detection cadence
# (it cleans up on the next send to a dead socket). Tightening below
# 30 s starts to waste CPU; loosening above 120 s leaves dead sockets
# around long enough for a chatty client to notice the orphaned
# broadcasts.
SWEEP_INTERVAL_S = 60

_scheduler = None  # type: ignore[assignment]


async def _tick() -> None:
    """Single sweep — must never raise; APScheduler would auto-retry,
    but a stack-trace per tick is noise the operator doesn't need."""
    try:
        from app.api.ws_command_center import sweep_dead_cc_connections
        await sweep_dead_cc_connections()
    except Exception as e:
        logger.warning(f"[REL-05] cc_ws_sweeper tick failed: {e}")


def start_cc_ws_sweeper() -> None:
    """Register the recurring sweep. Idempotent — calling twice
    replaces the existing job."""
    global _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            _tick,
            IntervalTrigger(seconds=SWEEP_INTERVAL_S),
            id="cc_ws_sweeper",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info(
            f"[REL-05] cc_ws_sweeper registered — interval={SWEEP_INTERVAL_S}s"
        )
    except ImportError:
        logger.warning("[REL-05] apscheduler not available — cc_ws_sweeper disabled")
    except Exception as e:
        logger.error(f"[REL-05] cc_ws_sweeper setup failed: {e}")


def stop_cc_ws_sweeper() -> None:
    global _scheduler
    try:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("[REL-05] cc_ws_sweeper stopped")
    except Exception as e:
        logger.debug(f"[REL-05] cc_ws_sweeper stop failed: {e}")
