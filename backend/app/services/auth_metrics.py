"""Auth latency metrics — observability for `get_current_user`.

Tracks the rolling 30 s p95 of authenticated-request resolution so we
can spot regressions of the user-cache fast path (`app/services/user_cache.py`).

Threshold engine: p95 > 500 ms → `system_health_delta` is emitted with
`source="auth"` so the operator capsule (Phase 1.2 / 1.3 surface) lights
up immediately. Polling reconciles every 30 s.

Periodic log: every 30 s the recorder emits a single line
    `[AUTH_CACHE] p95=<ms>ms hits=<n> misses=<n> samples=<n>`
so SREs can grep the log for regression evidence without hitting the
admin endpoint.

Read-only, never raises into the auth path.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REDIS_NS = "auth_metrics"
WINDOW_S = 30.0           # rolling-p95 window
SUMMARY_INTERVAL_S = 30.0  # periodic [AUTH_CACHE] log cadence


class _Sample:
    __slots__ = ("ts", "ms", "hit")

    def __init__(self, ts: float, ms: float, hit: bool):
        self.ts = ts
        self.ms = ms
        self.hit = hit


_lock = threading.Lock()
_samples: list[_Sample] = []
_hits_total = 0
_misses_total = 0
_summary_thread_started = False


def _redis():
    try:
        from app.services.redis_service import _get_client
        return _get_client()
    except Exception:
        return None


def _prune_locked(now: float) -> None:
    """Drop samples older than the rolling window. Caller holds _lock."""
    cutoff = now - WINDOW_S
    # Samples are appended in time order, so we can pop from the front.
    idx = 0
    for s in _samples:
        if s.ts >= cutoff:
            break
        idx += 1
    if idx:
        del _samples[:idx]


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return round(s[k], 2)


def _persist_snapshot(snap: dict) -> None:
    c = _redis()
    if not c:
        return
    try:
        c.set(f"nischint:{REDIS_NS}:state", json.dumps(snap, default=str), ex=300)
    except Exception as e:
        logger.debug(f"auth_metrics persist failed: {e}")


def record(ms: float, *, cache_hit: bool) -> None:
    """Record a `get_current_user` resolution.

    `cache_hit=True`  → user_cache served the request (~0 ms DB cost).
    `cache_hit=False` → fell through to the DB lookup.
    """
    global _hits_total, _misses_total
    now = time.time()
    with _lock:
        _samples.append(_Sample(now, max(0.0, float(ms)), bool(cache_hit)))
        if cache_hit:
            _hits_total += 1
        else:
            _misses_total += 1
        _prune_locked(now)

    # Threshold evaluation runs OUTSIDE the lock — the threshold engine
    # may try to schedule an async broadcast and we don't want to hold
    # the recorder lock across that.
    _maybe_emit_threshold_event()


def _maybe_emit_threshold_event() -> None:
    try:
        snap = get_snapshot()
        from app.services.health_thresholds import evaluate_auth_state
        evaluate_auth_state(
            snap.get("p95_ms"),
            int(snap.get("samples") or 0),
        )
    except Exception:
        logger.debug("auth threshold evaluation failed", exc_info=True)


def get_snapshot() -> dict:
    """Rolling-30s snapshot of auth latency. Safe to call from any thread."""
    now = time.time()
    with _lock:
        _prune_locked(now)
        latencies = [s.ms for s in _samples]
        hits_window = sum(1 for s in _samples if s.hit)
        misses_window = sum(1 for s in _samples if not s.hit)
        hits_total = _hits_total
        misses_total = _misses_total

    samples = len(latencies)
    hit_rate = (hits_window / samples) if samples else None

    return {
        "p50_ms":        _percentile(latencies, 50),
        "p95_ms":        _percentile(latencies, 95),
        "samples":       samples,
        "window_s":      WINDOW_S,
        "hits_window":   hits_window,
        "misses_window": misses_window,
        "hit_rate":      round(hit_rate, 3) if hit_rate is not None else None,
        "hits_total":    hits_total,
        "misses_total":  misses_total,
        "computed_at":   datetime.now(timezone.utc).isoformat(),
    }


def reset() -> dict:
    global _hits_total, _misses_total
    with _lock:
        _samples.clear()
        _hits_total = 0
        _misses_total = 0
    c = _redis()
    if c:
        try:
            c.delete(f"nischint:{REDIS_NS}:state")
        except Exception:
            pass
    return {"reset_at": datetime.now(timezone.utc).isoformat()}


# ── Periodic summary logger ──────────────────────────────────────────
# Runs in a daemon thread (one per process) so the log line lands even
# if no admin endpoint is being hit. Cheap: one snapshot + one log.

def _summary_loop() -> None:
    while True:
        try:
            time.sleep(SUMMARY_INTERVAL_S)
            snap = get_snapshot()
            _persist_snapshot(snap)
            if snap.get("samples", 0) == 0:
                logger.info("[AUTH_CACHE] p95=— samples=0 (no authenticated traffic this window)")
                continue
            logger.info(
                "[AUTH_CACHE] p95=%sms p50=%sms samples=%s hits=%s misses=%s hit_rate=%s",
                snap.get("p95_ms"),
                snap.get("p50_ms"),
                snap.get("samples"),
                snap.get("hits_window"),
                snap.get("misses_window"),
                snap.get("hit_rate"),
            )
        except Exception:
            logger.debug("auth_metrics summary loop iteration failed", exc_info=True)


def start_summary_thread() -> None:
    """Idempotently start the 30 s summary logger. Called from server
    startup; safe to call multiple times — only the first wins."""
    global _summary_thread_started
    with _lock:
        if _summary_thread_started:
            return
        _summary_thread_started = True
    t = threading.Thread(target=_summary_loop, name="auth_metrics_summary", daemon=True)
    t.start()
    logger.info("[AUTH_CACHE] periodic 30s p95 logger started")
