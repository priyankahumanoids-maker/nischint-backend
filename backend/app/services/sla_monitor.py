"""NISCH-008b — Periodic Twilio SLA monitor.

Polls the same metrics that `/api/_dev/twilio/sla` exposes every 60s
and fires `health_alerter.notify_failure` whenever the verdict crosses
a green→amber/red boundary.

Strict design:
  * Pure poll, no DB writes. Reads `ttfa_recorder` + Twilio auth probe.
  * Emits transition events only — staying red doesn't spam the channel
    every minute (the alerter's own dedup also enforces a 5-min
    silence window per (kind, message)).
  * Runs only in the scheduler-role process (single-instance) — same
    gate `runs_schedulers()` as every other scheduler.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_last_status: str = "unknown"
_last_heartbeat_ts: float = 0.0


async def _heartbeat_once() -> None:
    """Emit an info-level heartbeat. Slack/Discord side can configure
    a dead-man's-switch alert if heartbeats stop arriving for >10 min.
    Self-dedup is handled by health_alerter (5-min window) — we override
    with `dedup_key` so each heartbeat is unique and lands every cycle.
    """
    global _last_heartbeat_ts
    import time as _t
    try:
        from app.services.health_alerter import notify_failure
        now = _t.time()
        notify_failure(
            level="info",
            kind="heartbeat",
            message=f"Nischint scheduler heartbeat — alive @ {int(now)}",
            details={
                "uptime_since_last_s": int(now - _last_heartbeat_ts) if _last_heartbeat_ts else None,
            },
            dedup_key=f"heartbeat:{int(now // 60)}",  # one slot per minute, never collides
        )
        _last_heartbeat_ts = now
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[HEARTBEAT] emit failed: {e}")


async def _check_once() -> None:
    """Poll Twilio SLA and emit a transition alert if needed."""
    global _last_status
    try:
        # Lazy imports — avoid pulling sms_service at module import time.
        from app.services import sms_service, ttfa_recorder
        from app.services.health_alerter import notify_failure

        # 1. Auth check (cheap).
        auth_ok = False
        try:
            if sms_service._twilio_client:
                sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
                sms_service._twilio_client.api.accounts(sid).fetch()
                auth_ok = True
        except Exception:
            auth_ok = False

        # 2. Latency stats.
        stats = ttfa_recorder.get_stats(since_s=3600, include_redis=True)
        sms_b   = stats["by_kind"].get("twilio:sms",   {"count": 0, "p95": 0})
        voice_b = stats["by_kind"].get("twilio:voice", {"count": 0, "p95": 0})
        sms_p95   = int(sms_b.get("p95", 0))
        voice_p95 = int(voice_b.get("p95", 0))

        # 3. Verdict (mirrors `/api/_dev/twilio/sla` thresholds).
        status = "green"
        reasons: list[str] = []
        if not auth_ok:
            status = "red"
            reasons.append("auth_failed")
        if sms_b.get("count", 0) and sms_p95 >= 5000:
            status = "red"; reasons.append(f"sms_p95={sms_p95}ms")
        elif sms_b.get("count", 0) and sms_p95 >= 2000:
            if status == "green":
                status = "amber"
            reasons.append(f"sms_p95={sms_p95}ms")
        if voice_b.get("count", 0) and voice_p95 >= 8000:
            status = "red"; reasons.append(f"voice_p95={voice_p95}ms")
        elif voice_b.get("count", 0) and voice_p95 >= 4000:
            if status == "green":
                status = "amber"
            reasons.append(f"voice_p95={voice_p95}ms")

        # 4. Emit only on transitions.
        if status != _last_status:
            prev = _last_status
            _last_status = status
            if prev == "unknown":
                # First reading — only alert if not green.
                if status == "green":
                    return
            level = "critical" if status == "red" else "warn" if status == "amber" else "warn"
            msg = (
                f"Twilio SLA transitioned {prev} → {status}. "
                f"Reasons: {', '.join(reasons) or 'none'}"
            )
            if status == "green":
                msg = f"Twilio SLA recovered: {prev} → green."

            # NISCH-008d: attach last 10 TTFA events on red/amber so the
            # on-call sees *which* alerts went slow without grepping.
            details: dict = {
                "from":      prev,
                "to":        status,
                "auth_ok":   auth_ok,
                "sms_p95":   sms_p95,
                "voice_p95": voice_p95,
                "reasons":   reasons,
            }
            if status in ("amber", "red"):
                try:
                    details["recent_ttfa"] = ttfa_recorder.get_recent_events(10)
                except Exception:
                    pass

            notify_failure(
                level="critical" if status == "red" else "warn",
                kind="sla_transition",
                message=msg,
                details=details,
                dedup_key=f"sla:{prev}->{status}",
            )
            logger.warning(f"[SLA_TRANSITION] {prev} → {status} reasons={reasons}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SLA_MONITOR] check failed: {e}")


def start_sla_monitor() -> None:
    """Start the 60s polling job + 5-min heartbeat. Idempotent."""
    global _scheduler
    if _scheduler:
        return
    interval_s = int(os.environ.get("SLA_MONITOR_INTERVAL_S", "60"))
    heartbeat_s = int(os.environ.get("HEARTBEAT_INTERVAL_S", "300"))
    sched = AsyncIOScheduler()
    sched.add_job(_check_once, "interval", seconds=interval_s, id="twilio_sla_monitor")
    sched.add_job(_heartbeat_once, "interval", seconds=heartbeat_s, id="ops_heartbeat")
    sched.start()
    _scheduler = sched
    logger.info(
        f"SLA monitor started (sla_interval={interval_s}s, heartbeat={heartbeat_s}s)"
    )


def stop_sla_monitor() -> None:
    global _scheduler, _last_status
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
    _last_status = "unknown"


__all__ = ["start_sla_monitor", "stop_sla_monitor"]
