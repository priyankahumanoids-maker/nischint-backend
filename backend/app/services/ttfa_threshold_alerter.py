"""NISCH-006 Day 3++ — TTFA threshold alerter.

Polls `get_state_stats()` over a rolling window and pages on-call via
the existing `health_alerter` Slack/Discord plumbing when any state's
p95 transition latency breaches its configured threshold.

Operational reading:
  * `escalated p95 > 30s` → guardian responsiveness gap. Either FCM/SMS
    delivery is broken (notification gap) OR guardians aren't engaging
    (UX/trust gap). Both are pageable.
  * `validating p95 > 5s` → upstream pipeline regression — the dedup
    gate or guardian-resolution path is slowing down.
  * `acknowledged p95 > 60s` → guardians ACK'd but aren't resolving.
    Probably a UX issue around the resolve button, not safety-critical
    but eats trust.

Strict design:
  * Per-state cooldown via Redis `SET NX EX 900` — same state can't
    re-alert inside 15 min unless cooldown expires or the state
    recovers. Per-state isolation means an `escalated` breach doesn't
    silence a separate `validating` breach.
  * Redis unavailable → fail OPEN. Duplicate alerts are a smaller cost
    than a missed alert during a Redis outage.
  * `notify_failure` is best-effort and never raises.
  * NO "all clear" message. Recovery is silent — that's noise.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import redis_service
from app.services.health_alerter import notify_failure
from app.services.ttfa_state_stats import get_state_stats

logger = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _thresholds() -> dict[str, int]:
    """Read fresh on every call so env-var hot-tweaks (or test
    monkeypatches) take effect without a process restart."""
    return {
        "validating":   _env_int("TTFA_THRESHOLD_VALIDATING_MS",   5_000),
        "escalated":    _env_int("TTFA_THRESHOLD_ESCALATED_MS",    30_000),
        "acknowledged": _env_int("TTFA_THRESHOLD_ACKNOWLEDGED_MS", 60_000),
    }


def _window_hours() -> int:
    return _env_int("TTFA_ALERT_WINDOW_HOURS", 1)


def _cooldown_seconds() -> int:
    return _env_int("TTFA_ALERT_COOLDOWN_SECONDS", 900)


# ── Cooldown gate ───────────────────────────────────────────────────
COOLDOWN_NAMESPACE = "ttfa_alert_cooldown"


def _try_acquire_cooldown(state: str, ttl_s: int) -> bool:
    """Attempt to acquire the cooldown for `state`.

    Returns:
        True  → cooldown was free, now claimed (caller MAY alert).
        False → cooldown already held — caller MUST stay silent.

    Fail-open contract: any Redis error is treated as "free" (returns
    True). A duplicate Slack ping during a Redis outage is the right
    cost vs. a missed alert.
    """
    try:
        c = redis_service._get_client()
        if c is None:
            return True  # fail open
        full_key = redis_service._key(COOLDOWN_NAMESPACE, state)
        # SET NX EX is atomic — exactly one caller wins the cooldown.
        ok = c.set(full_key, "1", nx=True, ex=ttl_s)
        return bool(ok)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[TTFA_ALERT] cooldown probe failed (fail-open): {e}")
        return True


# ── Slack body composition ──────────────────────────────────────────
def _format_breakdown(
    stats: dict[str, dict[str, int]],
    breached: set[str],
    thresholds: dict[str, int],
) -> str:
    """Single multi-line text block for Slack. States with no events
    in the window render `—` placeholders so on-call sees the full
    map, not a sparse hash."""
    state_order = ["detected", "validating", "escalated",
                   "acknowledged", "resolved", "archived"]
    lines = ["Last %dh state breakdown:" % _window_hours()]
    for st in state_order:
        s = stats.get(st)
        if not s or s.get("count", 0) == 0:
            lines.append(f"  {st:<14} —             —             n=0")
            continue
        marker = "  ⚠️" if st in breached else ""
        thr = thresholds.get(st)
        thr_str = f"  (threshold: {thr:,}ms)" if (st in breached and thr) else ""
        lines.append(
            f"  {st:<14} p50={s['p50_ms']:<6,}ms  "
            f"p95={s['p95_ms']:<7,}ms  n={s['count']}{marker}{thr_str}"
        )
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────
async def check_and_alert(session: AsyncSession) -> dict[str, Any]:
    """Single tick: fetch stats, compare each thresholded state,
    fire Slack on breach (per-state cooldown gated).

    Returns a small audit dict so the scheduler can log + tests can
    assert outcomes without inspecting Slack.
    """
    thresholds = _thresholds()
    window_h   = _window_hours()
    ttl        = _cooldown_seconds()

    stats = await get_state_stats(session, window_hours=window_h)

    breaches: dict[str, dict] = {}
    for state, threshold_ms in thresholds.items():
        s = stats.get(state)
        if not s:
            continue
        p95 = int(s.get("p95_ms") or 0)
        if p95 > threshold_ms:
            breaches[state] = {
                "p95_ms":      p95,
                "p50_ms":      int(s.get("p50_ms") or 0),
                "count":       int(s.get("count") or 0),
                "threshold":   threshold_ms,
            }

    if not breaches:
        return {"breaches": {}, "alerts_fired": 0,
                "stats": stats, "ts": datetime.now(timezone.utc).isoformat()}

    # Acquire cooldowns per-state. Only states that win the cooldown
    # contribute to the alert payload; suppressed states are logged
    # but not paged.
    alertable = {}
    suppressed = []
    for state, info in breaches.items():
        if _try_acquire_cooldown(state, ttl):
            alertable[state] = info
        else:
            suppressed.append(state)

    if not alertable:
        logger.info(
            f"[TTFA_ALERT] all breaches suppressed by cooldown: {suppressed}"
        )
        return {"breaches": breaches, "alerts_fired": 0,
                "suppressed": suppressed, "stats": stats,
                "ts": datetime.now(timezone.utc).isoformat()}

    # Build the message — title line targets the worst breaching state,
    # body shows the full state breakdown so on-call has context.
    worst = max(alertable.items(), key=lambda kv: kv[1]["p95_ms"])
    state, info = worst
    title = (
        f"TTFA threshold breach — `{state}` p95={info['p95_ms']:,}ms "
        f"(threshold: {info['threshold']:,}ms)"
    )
    body = _format_breakdown(stats, set(alertable.keys()), thresholds)

    # `notify_failure` is best-effort; the cooldown is already claimed
    # whether the Slack post succeeds or not — that's intentional. We
    # don't want a flaky Slack endpoint to remove the cooldown and
    # cause a re-alert storm against the same breach.
    notify_failure(
        level="warn",
        kind="ttfa_p95_breach",
        message=title + "\n" + body,
        details={
            "breached_states":  list(alertable.keys()),
            "suppressed":       suppressed,
            "window_hours":     window_h,
            "stats":            stats,
        },
        dedup_key=f"ttfa_p95::{','.join(sorted(alertable.keys()))}",
    )
    logger.warning(
        f"[TTFA_ALERT] FIRED states={list(alertable.keys())} "
        f"suppressed={suppressed}"
    )

    return {
        "breaches":     breaches,
        "alerts_fired": 1,
        "alertable":    alertable,
        "suppressed":   suppressed,
        "stats":        stats,
        "ts":           datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["check_and_alert", "COOLDOWN_NAMESPACE"]
