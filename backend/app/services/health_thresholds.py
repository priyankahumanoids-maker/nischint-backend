"""System-health threshold engine — emits `system_health_delta` ONLY on
state transitions, never on every tick.

Golden rule (locked in PRD):
    WS is for state change, not telemetry stream.

The capsule polls every 30 s for the full snapshot. This module is the
*only* path that pushes a real-time event, and it does so under
strict guards:

  • Per-source (scheduler / ai / queue) we cache the last emitted
    `severity` in Redis. A new event is published *only* if the new
    severity differs from the cached one, OR a new threshold crossing
    is detected (e.g. drift_p95 just exceeded its SLA, missed_count
    just incremented above zero).
  • Two thresholds → at most two events per source in a sustained
    drift episode (one when crossing into degraded, one when crossing
    back to healthy). No event spam.
  • Cross-process safe via Redis — the scheduler process records,
    the API process broadcasts, neither sees duplicates.

If thresholds need tuning, edit the constants below. Everything else
in the system reads from `get_snapshot()` and stays internally
consistent.
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Thresholds (mirrored in the snapshot endpoint logic) ──────────────
SCHED_DRIFT_P95_MS = 1000           # scheduler drift_p95 SLA
AI_P95_MS         = 3000             # AI inference p95 SLA
AUTH_P95_MS       = 500              # get_current_user p95 SLA (post user_cache)
QUEUE_WARN        = 100              # queue depth → warning
QUEUE_DEGRADED    = 500              # queue depth → degraded

# REL-04 — DB pool utilization. 85% is the warn-but-not-yet-broken
# band: at 17/20 checked-out we still have 3 connections + max_overflow
# in reserve, but a single slow query will push us over. We require
# `DB_POOL_CONSECUTIVE_READINGS` (2) >85% samples before flipping to
# `degraded` to filter out single-spike noise. Recovery is symmetrical:
# 2 consecutive ≤85% readings flip us back to `healthy`.
DB_POOL_UTIL_PCT_DEGRADED   = 85.0
DB_POOL_CONSECUTIVE_READINGS = 2

# SB-02 — user_signal_baselines matview staleness threshold.
# Mirrors `STALENESS_THRESHOLD_S` from `user_signal_baseline_service`.
# 36 h gives one full nightly refresh window of slack (a 24 h refresh
# that runs ~30 min late shouldn't read as stale). Anything older
# means a refresh skipped completely → degraded.
BASELINES_STALENESS_THRESHOLD_S = 36 * 3600

# Auth-domain noise floor. Cold-start cache misses on the very first
# requests in a fresh process LEGITIMATELY exceed 500 ms (the in-process
# LRU hasn't warmed yet, every miss pays the full ~2 s Mumbai pooler
# round-trip). Suppress alerts until:
#   1. enough samples landed in the rolling 30 s window, AND
#   2. the process has been up long enough that startup warm-up is done.
AUTH_MIN_SAMPLES_DEGRADED = 10
AUTH_STARTUP_GRACE_S      = 60.0

# Process-start timestamp. Used by the auth classifier to suppress
# startup-noise alerts. Captured at module import time — close enough
# to FastAPI's actual cold-start moment to be useful, and never reset
# during the process lifetime (so hot-reloads in dev DON'T re-arm it).
_PROCESS_START_TS = time.time()

# How long to cool down between identical-severity emits even if a
# different metric flipped — guards against flip-flap loops.
EMIT_COOLDOWN_S = 5.0

# Redis key prefix for previous-severity cache
REDIS_NS = "system_health_state"


def _read_prev(source: str) -> dict | None:
    """Read previous health state with Redis -> in-memory fallback."""
    try:
        from app.services.redis_service import get_json
        value = get_json(REDIS_NS, source)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _write_prev(source: str, payload: dict) -> None:
    """Persist previous health state with Redis -> in-memory fallback."""
    try:
        from app.services.redis_service import set_json
        set_json(REDIS_NS, source, payload, ttl=86400)
    except Exception as e:
        logger.debug(f"health_thresholds state write failed: {e}")


def _classify_scheduler(drift_p95_ms: float | None, missed: int, errors: int) -> tuple[str, str | None, float | None]:
    """Return (severity, dominant_metric, dominant_value)."""
    if missed and missed > 0:
        return "degraded", "missed_jobs", float(missed)
    if drift_p95_ms is not None and drift_p95_ms > SCHED_DRIFT_P95_MS:
        return "degraded", "drift_p95", float(drift_p95_ms)
    if errors and errors > 0:
        return "warning", "error_count", float(errors)
    return "healthy", None, None


def _classify_ai(p95_ms: float | None, errors: int, samples: int) -> tuple[str, str | None, float | None]:
    if errors and errors > 0:
        return "warning", "error_count", float(errors)
    if samples and samples >= 3 and p95_ms is not None and p95_ms > AI_P95_MS:
        return "degraded", "p95_ms", float(p95_ms)
    return "healthy", None, None


def _classify_queue(pending: int) -> tuple[str, str | None, float | None]:
    if pending >= QUEUE_DEGRADED:
        return "degraded", "pending_total", float(pending)
    if pending >= QUEUE_WARN:
        return "warning", "pending_total", float(pending)
    return "healthy", None, None


def _emit(payload: dict) -> None:
    """Schedule a broadcast on the running event loop without blocking
    the caller (which may be a sync APScheduler listener)."""
    try:
        from app.services.event_broadcaster import broadcaster
    except Exception:
        return

    async def _send():
        try:
            await broadcaster.broadcast_to_operators("system_health_delta", payload)
        except Exception:
            logger.exception("system_health_delta broadcast failed")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_send())
        else:
            asyncio.run(_send())
    except RuntimeError:
        # No event loop in this thread — common for APScheduler. Run in a
        # short-lived loop in the same thread; cheap because broadcast is
        # in-memory + a Redis publish.
        try:
            asyncio.new_event_loop().run_until_complete(_send())
        except Exception:
            logger.debug("system_health_delta emit could not schedule send")


def _evaluate(source: str, severity: str, metric: str | None, value: float | None,
              threshold: float | None, extra: dict | None = None) -> None:
    """Compare against previous severity for this source; emit on transition."""
    prev = _read_prev(source) or {}
    prev_sev = prev.get("severity")
    prev_metric = prev.get("metric")
    prev_ts = float(prev.get("ts") or 0)
    now = time.time()

    # Cold start at healthy is not a "transition" — record silently and bail.
    if prev_sev is None and severity == "healthy":
        _write_prev(source, {"severity": severity, "metric": metric, "ts": now})
        return

    # No transition → no event. Even if the metric changed inside the same
    # severity band, we stay silent — that's the golden rule.
    if prev_sev == severity and prev_metric == metric:
        return

    # Cooldown — block flip-flap loops, but ONLY when both severity AND
    # metric are the same. A new threshold crossing (different metric)
    # is always informative even within the same severity band.
    if (now - prev_ts) < EMIT_COOLDOWN_S and prev_sev == severity and prev_metric == metric:
        return

    payload = {
        "type":      "system_health_delta",
        "ts":        int(now),
        "iso":       datetime.now(timezone.utc).isoformat(),
        "severity":  severity,        # healthy | warning | degraded
        "source":    source,          # scheduler | ai | queue
        "metric":    metric,          # which threshold drove it (None on healthy)
        "value":     value,
        "threshold": threshold,
        "previous_severity": prev_sev,
    }
    if extra:
        payload.update(extra)

    _write_prev(source, {"severity": severity, "metric": metric, "ts": now})
    _emit(payload)
    logger.info(
        f"[system_health_delta] {source} {prev_sev or '∅'}→{severity} "
        f"({metric}={value} threshold={threshold})"
    )

    # Hand the transition to the historical Incident State Engine.
    # The engine is write-only + snapshot-based + transition-triggered;
    # it never feeds back into this module.
    try:
        from app.services.system_incident_engine import handle_transition, cancel_pending
        if severity == "healthy":
            cancel_pending(source)
        # Schedule the async handler from this potentially-sync caller.
        async def _hand_off():
            try:
                await handle_transition(
                    prev_severity=prev_sev,
                    new_severity=severity,
                    source=source,
                    metric=metric,
                )
            except Exception:
                logger.exception("incident engine handle_transition failed")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_hand_off())
            else:
                asyncio.run(_hand_off())
        except RuntimeError:
            try:
                asyncio.new_event_loop().run_until_complete(_hand_off())
            except Exception:
                logger.debug("incident engine could not schedule handler")
    except Exception:
        logger.exception("incident engine wiring failed")


# ── Public hooks (called by the recorders) ────────────────────────────
def evaluate_scheduler_state(drift_p95_ms: float | None, missed: int, errors: int,
                              job_id: str | None = None) -> None:
    sev, metric, value = _classify_scheduler(drift_p95_ms, missed, errors)
    threshold = None
    if metric == "drift_p95":
        threshold = float(SCHED_DRIFT_P95_MS)
    elif metric == "missed_jobs":
        threshold = 0.0
    extra = {"job_id": job_id} if job_id else None
    _evaluate("scheduler", sev, metric, value, threshold, extra)


def evaluate_ai_state(p95_ms: float | None, errors: int, samples: int) -> None:
    sev, metric, value = _classify_ai(p95_ms, errors, samples)
    threshold = float(AI_P95_MS) if metric == "p95_ms" else None
    _evaluate("ai", sev, metric, value, threshold)


def _classify_auth(p95_ms: float | None, samples: int) -> tuple[str, str | None, float | None]:
    """Auth latency only degrades on p95 — a single slow request is noise,
    a sustained slow window means the user_cache fast path regressed.

    Cold-start noise floor (locked):
      • Suppress entirely while process uptime < `AUTH_STARTUP_GRACE_S`
        (60 s). The in-process LRU hasn't warmed yet; every miss
        legitimately pays the full Mumbai-pooler round-trip.
      • Require `samples >= AUTH_MIN_SAMPLES_DEGRADED` (10) so a single
        slow request on a quiet pod can't flip the dot.

    Both gates have to be cleared before degraded ever fires. The 30 s
    poll on the system-health endpoint continues to refresh the
    capsule with the correct steady-state once warm-up finishes.
    """
    # Startup grace window — pure time-based gate, independent of samples.
    if (time.time() - _PROCESS_START_TS) < AUTH_STARTUP_GRACE_S:
        return "healthy", None, None
    if samples and samples >= AUTH_MIN_SAMPLES_DEGRADED and p95_ms is not None and p95_ms > AUTH_P95_MS:
        return "degraded", "p95_ms", float(p95_ms)
    return "healthy", None, None


def evaluate_auth_state(p95_ms: float | None, samples: int) -> None:
    sev, metric, value = _classify_auth(p95_ms, samples)
    threshold = float(AUTH_P95_MS) if metric == "p95_ms" else None
    _evaluate("auth", sev, metric, value, threshold)


def evaluate_queue_state(pending: int) -> None:
    sev, metric, value = _classify_queue(pending)
    threshold = float(QUEUE_DEGRADED if value and value >= QUEUE_DEGRADED else QUEUE_WARN) \
        if metric else None
    _evaluate("queue", sev, metric, value, threshold)


# ── REL-04: DB pool exhaustion ──────────────────────────────────────
#
# In-memory consecutive-readings counter (per-process). We deliberately
# do NOT cache this in Redis — the threshold engine's job is to filter
# *this process's* observation of the pool, and SQLAlchemy pools are
# per-process anyway. Cross-process correlation happens upstream in the
# system_health_delta envelope itself (each process emits its own
# transition).

_db_pool_high_readings = 0    # consecutive ticks at/above DEGRADED util
_db_pool_low_readings  = 0    # consecutive ticks below DEGRADED util


def _classify_db_pool(util_pct: float | None) -> tuple[str, str | None, float | None]:
    """Pure-function classifier used by tests AND the production tick.

    Always evaluates the threshold; the consecutive-readings hysteresis
    is applied by `evaluate_db_pool_state` after this call, so this
    function stays trivially testable.
    """
    if util_pct is None:
        return "healthy", None, None
    if util_pct >= DB_POOL_UTIL_PCT_DEGRADED:
        return "degraded", "utilization_pct", float(util_pct)
    return "healthy", None, None


def evaluate_db_pool_state(util_pct: float | None,
                           snapshot: dict | None = None) -> None:
    """REL-04 — Fire `system_health_delta` only after
    `DB_POOL_CONSECUTIVE_READINGS` consecutive readings above the
    threshold (debounced rise) and below it (debounced recovery).

    `snapshot` is forwarded as `extra` on the event so the operator
    capsule can show checked_out / wait_count without a second hop.
    """
    global _db_pool_high_readings, _db_pool_low_readings

    sev, metric, value = _classify_db_pool(util_pct)

    if sev == "degraded":
        _db_pool_high_readings += 1
        _db_pool_low_readings = 0
        # Only emit once we've crossed the consecutive-readings bar.
        if _db_pool_high_readings < DB_POOL_CONSECUTIVE_READINGS:
            return
    else:
        _db_pool_low_readings += 1
        _db_pool_high_readings = 0
        # Symmetric debounce on the way back to healthy — guards against
        # a single momentary dip below 85% during a sustained spike.
        if _db_pool_low_readings < DB_POOL_CONSECUTIVE_READINGS:
            return

    threshold = float(DB_POOL_UTIL_PCT_DEGRADED) if metric else None
    extra: dict = {}
    if snapshot:
        # Embed the raw pool numbers so the capsule's flyout can show
        # "17/30 checked-out, 2 waiting" without polling /runtime-info.
        for k in (
            "pg_pool_size", "pg_pool_max_overflow", "pg_pool_total_capacity",
            "pg_pool_checked_out", "pg_pool_checked_in", "pg_pool_overflow",
            "pg_pool_wait_count",
        ):
            if k in snapshot:
                extra[k] = snapshot[k]
    _evaluate("database_pool", sev, metric, value, threshold, extra or None)


def reset_db_pool_counters() -> None:
    """Test seam — reset the consecutive-readings state between cases."""
    global _db_pool_high_readings, _db_pool_low_readings
    _db_pool_high_readings = 0
    _db_pool_low_readings = 0


# ── SB-02: user_signal_baselines matview health ─────────────────────
#
# A matview that is more than 36 h old reads as `stale` to the
# operator capsule — `degraded` on this domain. A failed last
# refresh (`last_status == 'failure'`) is also `degraded`,
# regardless of timestamp: the most recent attempt didn't write a
# successful snapshot, so consumers may be reading divergent data.
#
# Unknown / cold-start (no metadata row, or `last_status == 'unknown'`
# with no timestamp yet) → warning. The system isn't broken, we just
# don't have evidence of a clean run yet. Recovery to healthy
# requires both `last_status == 'success'` AND fresh timestamp.


def _classify_baselines(
    last_status: str | None,
    last_refreshed_at,                       # datetime | None
    now=None,
) -> tuple[str, str | None, float | None]:
    """Pure classifier — unit-tested in `test_baselines_threshold.py`.

    Returns (severity, dominant_metric, dominant_value):
      * `(degraded, 'last_status', failure_int)` — refresh failed.
      * `(degraded, 'staleness_s', age_seconds)` — matview drifted
        past the 36 h freshness window.
      * `(warning,  'no_refresh_recorded', None)` — cold start, no
        successful refresh on record yet.
      * `(healthy,  None, None)` — fresh, success.

    The `failure_int` value is purely informational (1.0) so the
    capsule has a numeric to render in its tile — the qualitative
    state is what drives operator action.
    """
    if (last_status or "").lower() == "failure":
        return "degraded", "last_status", 1.0
    # Staleness check — covers "matview drifted past 36 h".
    if last_refreshed_at is not None:
        n = now or datetime.now(timezone.utc)
        last = last_refreshed_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_s = (n - last).total_seconds()
        if age_s > BASELINES_STALENESS_THRESHOLD_S:
            return "degraded", "staleness_s", float(age_s)
        return "healthy", None, None
    # No timestamp yet — cold start; warn but not degraded.
    return "warning", "no_refresh_recorded", None


def evaluate_baselines_state(
    last_status: str | None,
    last_refreshed_at,                       # datetime | None
    extra: dict | None = None,
) -> None:
    """SB-02 — fire `system_health_delta` on baselines state transitions
    (refresh failure OR matview drifted past 36 h).

    `extra` is forwarded to the event payload so the capsule's
    flyout can render duration / rows / error without a second hop."""
    sev, metric, value = _classify_baselines(last_status, last_refreshed_at)
    threshold: float | None = None
    if metric == "staleness_s":
        threshold = float(BASELINES_STALENESS_THRESHOLD_S)
    _evaluate("baselines", sev, metric, value, threshold, extra)
