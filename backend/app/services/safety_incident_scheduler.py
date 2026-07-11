"""NISCH-006 — Safety Incident lifecycle sweeper scheduler.

Single APScheduler job: every N seconds, sweep idle ACKNOWLEDGED /
ESCALATED incidents to RESOLVED and idle RESOLVED incidents to
ARCHIVED. Strict scope: NO alerting, NO push — that lives in the
alert pipeline; this is the *terminal closer*.

Defaults (env-overridable in `app.core.config.Settings`):
  * SAFETY_INCIDENT_LIFECYCLE_INTERVAL_SECONDS = 60
  * SAFETY_INCIDENT_ESCALATED_RESOLVE_MINUTES = 30
  * SAFETY_INCIDENT_ACKNOWLEDGED_RESOLVE_MINUTES = 30
  * SAFETY_INCIDENT_RESOLVED_ARCHIVE_MINUTES = 30

Misfire / coalesce / max_instances follow the same shape as every
other interval job in the codebase.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.db.session import async_session
from app.services.safety_incident_engine import sweep_lifecycle
from app.services.stream_initiator import auto_decline_stale_offers
from app.services.ttfa_threshold_alerter import check_and_alert as ttfa_check_and_alert

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


async def _tick() -> None:
    async with async_session() as s:
        try:
            await sweep_lifecycle(
                s,
                escalated_resolve_minutes=settings.safety_incident_escalated_resolve_minutes,
                acknowledged_resolve_minutes=settings.safety_incident_acknowledged_resolve_minutes,
                resolved_archive_minutes=settings.safety_incident_resolved_archive_minutes,
            )
        except Exception:
            logger.exception("[safety_incident_scheduler] tick failed")
            await s.rollback()


async def _ttfa_alert_tick() -> None:
    """5-min cadence: poll TTFA-by-state percentiles and Slack-alert
    on threshold breach. Fail-quiet: any unhandled error is logged and
    swallowed — the alerter must NEVER crash the scheduler loop."""
    async with async_session() as s:
        try:
            await ttfa_check_and_alert(s)
        except Exception:
            logger.exception("[ttfa_threshold_check] tick failed")
            await s.rollback()


async def _stream_offer_sweep_tick() -> None:
    """NISCH-008 — 10s cadence sweeper. Flips StreamSession rows in
    `offered` state older than OFFER_TIMEOUT_S (30s) to `declined`.

    Cheap single-UPDATE; misses are recoverable on the next tick.
    Fail-quiet — the streaming layer must never crash the scheduler."""
    async with async_session() as s:
        try:
            await auto_decline_stale_offers(s)
            await s.commit()
        except Exception:
            logger.exception("[stream_stale_offer_sweep] tick failed")
            await s.rollback()


def start_safety_incident_scheduler() -> None:
    """Idempotent — safe to call from both legacy `all` mode and the
    standalone scheduler runner."""
    global _scheduler
    if _scheduler is not None:
        return
    interval = settings.safety_incident_lifecycle_interval_seconds
    sched = AsyncIOScheduler()
    sched.add_job(
        _tick, "interval", seconds=interval,
        id="safety_incident_lifecycle",
        max_instances=1, coalesce=True, misfire_grace_time=30,
    )
    # NISCH-006 Day 3++ — guardian-responsiveness pager. 5-min cadence
    # is the right balance: tight enough to catch a regression on the
    # NISCH-007 rollout day, loose enough that a single slow incident
    # in a quiet window doesn't immediately page on-call. Per-state
    # cooldown lives in Redis (15min default), so the cadence governs
    # how fast we *detect*, not how fast we *fire*.
    ttfa_alert_seconds = int(
        __import__("os").environ.get("TTFA_ALERT_INTERVAL_SECONDS", "300")
    )
    sched.add_job(
        _ttfa_alert_tick, "interval", seconds=ttfa_alert_seconds,
        id="ttfa_threshold_check",
        max_instances=1, coalesce=True, misfire_grace_time=60,
    )
    # NISCH-008 — Stream offer sweeper. 10s cadence so a missed
    # accept on a busy network doesn't leave guardians waiting on a
    # phantom `offered` row for more than ~40s end-to-end (offer
    # timeout 30s + worst-case sweep latency 10s).
    stream_sweep_seconds = int(
        __import__("os").environ.get("STREAM_OFFER_SWEEP_INTERVAL_SECONDS", "10")
    )
    sched.add_job(
        _stream_offer_sweep_tick, "interval", seconds=stream_sweep_seconds,
        id="stream_stale_offer_sweep",
        max_instances=1, coalesce=True, misfire_grace_time=15,
    )
    sched.start()
    _scheduler = sched
    logger.info(
        f"[safety_incident_scheduler] started — interval={interval}s "
        f"esc_resolve={settings.safety_incident_escalated_resolve_minutes}m "
        f"ack_resolve={settings.safety_incident_acknowledged_resolve_minutes}m "
        f"archive={settings.safety_incident_resolved_archive_minutes}m "
        f"ttfa_alert={ttfa_alert_seconds}s "
        f"stream_offer_sweep={stream_sweep_seconds}s"
    )


def stop_safety_incident_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


__all__ = ["start_safety_incident_scheduler", "stop_safety_incident_scheduler"]
