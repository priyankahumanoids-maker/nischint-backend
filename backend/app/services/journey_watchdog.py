"""Journey Gap Watchdog — downgrade-only inference.

Invariant #3 (LOCKED in /app/memory/SYSTEM_INVARIANTS.md):
  GPS path → ACTIVE only.
  Watchdog → PAUSED / OFFLINE only.
  This module MUST NEVER set is_offline = False.
  Recovery is the GPS path's exclusive responsibility.

Invariant #2:
  Gap math uses the SERVER session clock (`previous_update_at` vs
  `now()`), never device time. A device that hasn't pinged in >30s
  is offline regardless of what its own clock says.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.guardian import GuardianSession

logger = logging.getLogger(__name__)

# Tier-2 threshold: 30s of silence = offline. (Tier 1 = 15s "unstable"
# is set on the GPS path, never the watchdog.)
OFFLINE_AFTER_S = 30
TICK_S = 20  # close to half the threshold so detection is timely


async def tick() -> dict:
    """Scan active sessions whose `previous_update_at` is older than
    OFFLINE_AFTER_S and flip them to is_offline=True. Returns counters
    for observability."""
    from app.db.session import async_session as factory
    from app.services.guardian_mode_engine import _broadcast_journey_event

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=OFFLINE_AFTER_S)
    flipped = 0
    try:
        async with factory() as session:
            rows = (await session.execute(
                select(GuardianSession).where(
                    GuardianSession.status == "active",
                    GuardianSession.is_offline == False,  # noqa: E712
                    GuardianSession.previous_update_at < cutoff,
                ).with_for_update(skip_locked=True)
            )).scalars().all()
            for gs in rows:
                gap_s = int((now - gs.previous_update_at).total_seconds()) \
                    if gs.previous_update_at else 0
                # ↓ DOWNGRADE ONLY (Invariant #3) ↓
                gs.is_offline = True
                gs.offline_gaps = (gs.offline_gaps or 0) + 1
                gs.max_gap_seconds = max(gs.max_gap_seconds or 0, gap_s)
                flipped += 1
                await _broadcast_journey_event(gs, "journey_paused", {
                    "session_id":  str(gs.id),
                    "seq":         int(gs.total_points or 0),
                    "gap_seconds": gap_s,
                    "auto":        True,
                })
                logger.warning(
                    f"[journey_watchdog] OFFLINE session={gs.id} "
                    f"gap={gap_s}s (server-clock)"
                )
            if rows:
                await session.commit()
    except Exception:
        logger.exception("[journey_watchdog] tick failed")
    return {"checked_at": now.isoformat(), "flipped": flipped}


_scheduler: AsyncIOScheduler | None = None


def start_journey_watchdog() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        tick, "interval", seconds=TICK_S,
        id="journey_gap_watchdog",
        max_instances=1, coalesce=True, misfire_grace_time=15,
    )
    _scheduler.start()
    logger.info(f"[journey_watchdog] started — tick every {TICK_S}s, "
                f"offline_after={OFFLINE_AFTER_S}s")


def stop_journey_watchdog() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
