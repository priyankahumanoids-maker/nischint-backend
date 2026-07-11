"""OCE-01b — Daily AI-confidence snapshot scheduler.

Runs once a day (default 03:30 IST). For every user who has had ANY
activity in the last 24 hours (safety_events, baseline refresh, or a
trained twin), computes the same envelope as the live
`/api/ai/confidence/{user_id}` endpoint and upserts the four sub-scores
+ overall into `ai_confidence_history`.

Design choices:

* Compute is reused — we import the same `_build_envelope` the live
  endpoint uses. One formula, one place to audit.
* The job is idempotent — `INSERT … ON CONFLICT (user_id,
  snapshot_date) DO UPDATE` so a manual `_tick_for_test()` invocation
  for the same day overwrites cleanly.
* Failures per-user are isolated — a single user's compute error logs
  a WARN and continues. Sentry will capture the trace via the global
  handler.
* Schedule is cron-based (3:30 AM IST) to land after the daily
  baseline refresh and before the operator morning standup.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from app.db.session import async_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_JOB_ID = "ai_confidence_snapshot_daily"


# Users with activity worth snapshotting in the last 24 h:
# the union of safety_events authors, users with a refreshed baseline,
# and users with a recently-trained twin. UNION ALL + DISTINCT is
# the cheapest form here (each leg has a dedicated index).
_ACTIVE_USERS_SQL = """
    WITH active AS (
        SELECT user_id FROM safety_events
            WHERE created_at >= NOW() - INTERVAL '24 hours'
        UNION
        SELECT user_id FROM user_signal_baselines
        UNION
        SELECT s.guardian_id AS user_id
            FROM device_digital_twins dt
            JOIN devices d ON d.id = dt.device_id
            JOIN seniors s ON s.id = d.senior_id
            WHERE dt.last_trained_at >= NOW() - INTERVAL '24 hours'
              AND s.guardian_id IS NOT NULL
    )
    SELECT DISTINCT user_id FROM active WHERE user_id IS NOT NULL;
"""


async def _snapshot_one_user(user_id: str, snapshot_date) -> None:
    """Compute envelope for `user_id` and upsert a single row."""
    from app.api.ai_confidence import _build_envelope

    async with async_session() as session:
        envelope = await _build_envelope(session, str(user_id))
        await session.execute(
            text("""
                INSERT INTO ai_confidence_history
                       (user_id, snapshot_date, overall_confidence,
                        twin_confidence, telemetry_quality,
                        behavioral_match, attenuation_factor)
                VALUES (:uid, :date, :overall, :twin, :tel, :behav, :att)
                ON CONFLICT (user_id, snapshot_date) DO UPDATE
                SET overall_confidence = EXCLUDED.overall_confidence,
                    twin_confidence    = EXCLUDED.twin_confidence,
                    telemetry_quality  = EXCLUDED.telemetry_quality,
                    behavioral_match   = EXCLUDED.behavioral_match,
                    attenuation_factor = EXCLUDED.attenuation_factor;
            """),
            {
                "uid":     str(user_id),
                "date":    snapshot_date,
                "overall": envelope["overall_confidence"],
                "twin":    envelope["twin_confidence"],
                "tel":     envelope["telemetry_quality"],
                "behav":   envelope["behavioral_match"],
                "att":     envelope["attenuation_factor"],
            },
        )
        await session.commit()


async def run_snapshot_pass() -> dict:
    """Single full pass — snapshot every active user. Returns a small
    stats dict for the operator console and the daily job report.
    """
    started = datetime.now(timezone.utc)
    snapshot_date = started.date()
    stats = {"users_attempted": 0, "users_written": 0, "users_failed": 0}

    try:
        async with async_session() as session:
            rows = (await session.execute(text(_ACTIVE_USERS_SQL))).fetchall()
            user_ids = [r.user_id for r in rows]
    except Exception as e:
        logger.error(f"[OCE-01b] active-user query failed: {e}")
        return stats

    stats["users_attempted"] = len(user_ids)
    for uid in user_ids:
        try:
            await _snapshot_one_user(uid, snapshot_date)
            stats["users_written"] += 1
        except Exception as e:
            stats["users_failed"] += 1
            logger.warning(f"[OCE-01b] snapshot failed for {uid}: {e}")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        f"[OCE-01b] snapshot pass complete users={stats['users_written']}/"
        f"{stats['users_attempted']} failed={stats['users_failed']} "
        f"elapsed={elapsed:.1f}s"
    )
    return stats


def start_ai_confidence_history_scheduler() -> None:
    """Idempotent — call once at scheduler-process startup."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    if not _scheduler.running:
        # 03:30 IST = 22:00 UTC the previous day. We pick a slot
        # AFTER the nightly baseline refresh (02:00 IST) so the
        # telemetry component is fresh, and BEFORE the operator
        # morning standup so the chip shows updated numbers.
        _scheduler.add_job(
            run_snapshot_pass,
            CronTrigger(hour=22, minute=0, timezone="UTC"),
            id=_JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,  # allow up to 1 h late before skipping
            coalesce=True,
        )
        _scheduler.start()
        logger.info("[OCE-01b] ai_confidence_history_scheduler started — cron 22:00 UTC daily")


def stop_ai_confidence_history_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[OCE-01b] ai_confidence_history_scheduler stopped")
    _scheduler = None
