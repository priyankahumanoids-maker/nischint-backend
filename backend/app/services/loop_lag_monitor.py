"""LT-03 — Loop-lag Sentry/Slack fan-out monitor.

Samples the asyncio event-loop lag every second in a background task.
If lag stays above 500 ms continuously for ≥ 30 seconds, fires ONE
Sentry warning (with fingerprint ["loop-lag-degraded"]). When lag
recovers below 200 ms for ≥ 30 seconds, fires ONE recovery info
event. The fingerprint groups every degraded-then-recovered episode
into a single Sentry issue so the issue page reads as an outage
timeline.

Pattern reused from REL-09 prewarmer transitions:
  * `* → degraded`  → capture_message(level="warning")
  * `degraded → *`  → capture_message(level="info")

Sentry → Slack fan-out is configured at the Sentry project level
(integrations → Slack channel). We do NOT call Slack directly from
this module — same reason REL-09 doesn't. A single Sentry alert rule
with the fingerprint `loop-lag-degraded` routes every loop saturation
episode to the on-call Slack channel.

State machine:
    HEALTHY ──(lag > 500ms for 30s)──→ DEGRADED  ─emit warning─
       ▲                                  │
       └──(lag < 200ms for 30s)──────────┘─emit info─

The 500/200 ms hysteresis prevents flapping when lag oscillates
around a single threshold. 30 s sustained windows prevent false
positives from one-off blocking calls (e.g. a slow DB query).

Configuration via env (all optional, sane defaults):
  LOOP_LAG_DEGRADED_THRESHOLD_MS    default 500
  LOOP_LAG_HEALTHY_THRESHOLD_MS     default 200
  LOOP_LAG_SUSTAINED_WINDOW_S       default 30
  LOOP_LAG_SAMPLE_INTERVAL_S        default 1.0
  LOOP_LAG_MONITOR_DISABLED         default unset (anything truthy disables)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


_DEGRADED_THRESHOLD_MS  = _env_int("LOOP_LAG_DEGRADED_THRESHOLD_MS", 500)
_HEALTHY_THRESHOLD_MS   = _env_int("LOOP_LAG_HEALTHY_THRESHOLD_MS", 200)
_SUSTAINED_WINDOW_S     = _env_int("LOOP_LAG_SUSTAINED_WINDOW_S", 30)
_SAMPLE_INTERVAL_S      = _env_float("LOOP_LAG_SAMPLE_INTERVAL_S", 1.0)
_FINGERPRINT            = ["loop-lag-degraded"]


def _is_disabled() -> bool:
    return os.environ.get("LOOP_LAG_MONITOR_DISABLED", "").lower() in {"1", "true", "yes"}


# ── Sentry SDK (lazy import — matches REL-09 pattern) ────────────

def _sentry():
    """Returns the loaded `sentry_sdk` module, or None if Sentry is not
    configured for this process. Identical lazy-import pattern as
    `sachet_sentry._sentry` so tests can monkeypatch this symbol the
    same way."""
    try:
        import sentry_sdk
        if sentry_sdk.Hub.current.client is None:
            return None
        return sentry_sdk
    except Exception:
        return None


# ── Loop-lag sampling ─────────────────────────────────────────────

async def _sample_loop_lag_ms() -> float:
    """One asyncio.sleep(0) round-trip → measured in ms."""
    t0 = time.monotonic()
    await asyncio.sleep(0)
    return (time.monotonic() - t0) * 1000.0


# ── State machine ─────────────────────────────────────────────────


class _LoopLagState:
    """Tracks degraded-vs-healthy state with sustained-window logic.

    Exposed (not just internal) so tests can drive the state machine
    deterministically without spinning up the asyncio task. The
    sentry-emission side effects are wired through this state's
    `on_degrade` / `on_recover` hooks.
    """

    def __init__(
        self,
        degraded_threshold_ms: int = _DEGRADED_THRESHOLD_MS,
        healthy_threshold_ms: int = _HEALTHY_THRESHOLD_MS,
        sustained_window_s: int = _SUSTAINED_WINDOW_S,
    ):
        self.degraded_threshold_ms = degraded_threshold_ms
        self.healthy_threshold_ms = healthy_threshold_ms
        self.sustained_window_s = sustained_window_s
        # Current state: "healthy" | "degraded"
        self.state: str = "healthy"
        # Wall-clock when current "above threshold" streak started
        # (or current "below threshold" streak, depending on state).
        self._streak_start: Optional[float] = None
        # Peak lag observed in the current streak — included in
        # the Sentry context for the degraded event.
        self._streak_peak_ms: float = 0.0

    def feed(self, lag_ms: float, now: Optional[float] = None) -> Optional[str]:
        """Feed one sample. Returns a transition keyword if the state
        flipped on this sample, otherwise None.

        Returns:
            "degraded"  — flipped healthy→degraded (emit warning)
            "recovered" — flipped degraded→healthy (emit info)
            None        — no transition
        """
        if now is None:
            now = time.monotonic()

        if self.state == "healthy":
            # Looking for sustained breach of the high threshold.
            if lag_ms >= self.degraded_threshold_ms:
                if self._streak_start is None:
                    self._streak_start = now
                    self._streak_peak_ms = lag_ms
                else:
                    self._streak_peak_ms = max(self._streak_peak_ms, lag_ms)
                    if (now - self._streak_start) >= self.sustained_window_s:
                        self.state = "degraded"
                        peak = self._streak_peak_ms
                        self._streak_start = None
                        self._streak_peak_ms = 0.0
                        # Remember the peak so the caller can include
                        # it in the Sentry event context.
                        self._last_transition_peak_ms = peak
                        return "degraded"
            else:
                # Drop the streak — must be CONTINUOUSLY above threshold.
                self._streak_start = None
                self._streak_peak_ms = 0.0

        else:  # state == "degraded"
            # Looking for sustained recovery below the low threshold.
            if lag_ms < self.healthy_threshold_ms:
                if self._streak_start is None:
                    self._streak_start = now
                else:
                    if (now - self._streak_start) >= self.sustained_window_s:
                        self.state = "healthy"
                        self._streak_start = None
                        return "recovered"
            else:
                self._streak_start = None
        return None


# ── Sentry emission ──────────────────────────────────────────────


def _emit_degraded(peak_lag_ms: float, sustained_window_s: int, sample_count: int) -> None:
    """Capture the healthy→degraded warning. Mirrors the REL-09
    `emit_health_transition` shape so the Sentry filter
    `fingerprint:loop-lag-degraded` groups episodes into one issue."""
    sdk = _sentry()
    if sdk is None:
        logger.info(
            "[LT-03 loop-lag] degraded peak=%.1fms (sentry not configured)",
            peak_lag_ms,
        )
        return
    try:
        with sdk.push_scope() as scope:
            scope.set_tag("provider", "loop-lag")
            scope.set_tag("transition", "healthy->degraded")
            scope.set_tag("severity", "p1")
            scope.fingerprint = list(_FINGERPRINT)
            scope.set_context("loop_lag", {
                "peak_lag_ms":          round(peak_lag_ms, 2),
                "degraded_threshold_ms": _DEGRADED_THRESHOLD_MS,
                "sustained_window_s":   sustained_window_s,
                "samples_in_window":    sample_count,
                "pid":                  os.getpid(),
            })
            sdk.capture_message(
                f"Event loop saturated — peak {peak_lag_ms:.0f}ms sustained ≥ {sustained_window_s}s",
                level="warning",
            )
    except Exception as e:  # pragma: no cover — best-effort
        logger.debug("[LT-03 loop-lag] degraded emit failed: %r", e)


def _emit_recovered(sustained_window_s: int) -> None:
    """Capture the degraded→healthy info event. Same fingerprint, so
    the recovery lands on the same Sentry issue page as the outage
    (becomes a 'resolved' marker on the timeline)."""
    sdk = _sentry()
    if sdk is None:
        logger.info("[LT-03 loop-lag] recovered (sentry not configured)")
        return
    try:
        with sdk.push_scope() as scope:
            scope.set_tag("provider", "loop-lag")
            scope.set_tag("transition", "degraded->healthy")
            scope.fingerprint = list(_FINGERPRINT)
            scope.set_context("loop_lag", {
                "healthy_threshold_ms": _HEALTHY_THRESHOLD_MS,
                "sustained_window_s":   sustained_window_s,
                "pid":                  os.getpid(),
            })
            sdk.capture_message(
                f"Event loop recovered — lag < {_HEALTHY_THRESHOLD_MS}ms sustained ≥ {sustained_window_s}s",
                level="info",
            )
    except Exception as e:  # pragma: no cover
        logger.debug("[LT-03 loop-lag] recovered emit failed: %r", e)


# ── Background task ──────────────────────────────────────────────


_monitor_task: Optional[asyncio.Task] = None


async def _monitor_loop() -> None:
    """Background asyncio task. Runs forever (until process exits)
    sampling lag every `_SAMPLE_INTERVAL_S` and feeding the state
    machine. Wraps everything in `try/except` because a crash here
    must not kill the app."""
    logger.info(
        "[LT-03 loop-lag] monitor started: degraded≥%dms healthy<%dms sustained=%ds interval=%.2fs",
        _DEGRADED_THRESHOLD_MS, _HEALTHY_THRESHOLD_MS,
        _SUSTAINED_WINDOW_S, _SAMPLE_INTERVAL_S,
    )
    state = _LoopLagState()
    sample_count_in_window = 0
    while True:
        try:
            lag = await _sample_loop_lag_ms()
            sample_count_in_window += 1
            transition = state.feed(lag)
            if transition == "degraded":
                _emit_degraded(
                    peak_lag_ms=getattr(state, "_last_transition_peak_ms", lag),
                    sustained_window_s=_SUSTAINED_WINDOW_S,
                    sample_count=sample_count_in_window,
                )
                sample_count_in_window = 0
            elif transition == "recovered":
                _emit_recovered(sustained_window_s=_SUSTAINED_WINDOW_S)
                sample_count_in_window = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover — best-effort
            logger.debug("[LT-03 loop-lag] sample failed (ignored): %r", e)
        await asyncio.sleep(_SAMPLE_INTERVAL_S)


def start_monitor() -> Optional[asyncio.Task]:
    """Spawn the monitor as a background task on the running loop.
    Idempotent — safe to call multiple times; subsequent calls return
    the existing task. Returns None if disabled via env."""
    global _monitor_task
    if _is_disabled():
        logger.info("[LT-03 loop-lag] monitor disabled via LOOP_LAG_MONITOR_DISABLED")
        return None
    if _monitor_task is not None and not _monitor_task.done():
        return _monitor_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[LT-03 loop-lag] no running loop; monitor not started")
        return None
    _monitor_task = loop.create_task(_monitor_loop(), name="lt03-loop-lag-monitor")
    return _monitor_task


def stop_monitor() -> None:
    """Cancel the monitor task (used in tests / clean shutdown)."""
    global _monitor_task
    if _monitor_task is not None and not _monitor_task.done():
        _monitor_task.cancel()
    _monitor_task = None


__all__ = [
    "_LoopLagState",
    "_emit_degraded",
    "_emit_recovered",
    "_sentry",
    "start_monitor",
    "stop_monitor",
]
