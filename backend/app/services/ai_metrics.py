"""AI inference metrics — companion to scheduler_metrics.

Every LiteLLM / LlmChat call should be wrapped via `track()`:

    from app.services.ai_metrics import track
    async with track("guardian_ai_v2.summarize"):
        response = await chat.send_message(...)

Records duration, success/error, and (lazily) percentiles. Cross-process
via Redis so the API process can read what the scheduler/AI worker
process records, and vice-versa. Falls back to in-process state when
Redis is down.

Phase 1 ships with this surface ready; Phase 2 (`ai_worker`) will
relocate the actual call sites without changing the recorder API.
"""

from __future__ import annotations
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REDIS_NS = "ai_metrics"
ROLLING_WINDOW = 100  # last N latencies tracked globally


@dataclass
class _AiState:
    latencies_ms: list[float] = field(default_factory=list)  # rolling window
    success_count: int = 0
    error_count: int = 0
    last_call_at: str | None = None
    last_error: str | None = None
    last_owner: str | None = None
    last_latency_ms: float | None = None


_lock = threading.Lock()
_state = _AiState()


def _redis():
    try:
        from app.services.redis_service import _get_client
        return _get_client()
    except Exception:
        return None


def _persist() -> None:
    c = _redis()
    if not c:
        return
    try:
        c.set(
            f"nischint:{REDIS_NS}:state",
            json.dumps({
                "latencies_ms":   _state.latencies_ms[-ROLLING_WINDOW:],
                "success_count":  _state.success_count,
                "error_count":    _state.error_count,
                "last_call_at":   _state.last_call_at,
                "last_error":     _state.last_error,
                "last_owner":     _state.last_owner,
                "last_latency_ms": _state.last_latency_ms,
            }),
            ex=86400,
        )
    except Exception as e:
        logger.debug(f"ai_metrics persist failed: {e}")


@asynccontextmanager
async def track(owner: str):
    """Context manager — wraps an LLM call and records its outcome.

    Usage:
        async with track("guardian_ai_v2.summarize"):
            response = await chat.send_message(...)
    """
    t0 = time.perf_counter()
    try:
        yield
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        with _lock:
            _state.error_count += 1
            _state.last_error = str(e)[:300]
            _state.last_call_at = datetime.now(timezone.utc).isoformat()
            _state.last_owner = owner
            _state.last_latency_ms = round(ms, 2)
            _persist()
        _maybe_emit_threshold_event()
        raise
    else:
        ms = (time.perf_counter() - t0) * 1000
        with _lock:
            _state.success_count += 1
            _state.last_call_at = datetime.now(timezone.utc).isoformat()
            _state.last_owner = owner
            _state.last_latency_ms = round(ms, 2)
            _state.latencies_ms.append(round(ms, 2))
            if len(_state.latencies_ms) > ROLLING_WINDOW:
                _state.latencies_ms = _state.latencies_ms[-ROLLING_WINDOW:]
            _persist()
        _maybe_emit_threshold_event()


def _maybe_emit_threshold_event() -> None:
    """Per the golden rule (WS = state change, not telemetry stream),
    only the threshold engine decides whether anything is broadcast.
    """
    try:
        snap = get_snapshot()
        from app.services.health_thresholds import evaluate_ai_state
        evaluate_ai_state(
            snap.get("p95_ms"),
            int(snap.get("error_count") or 0),
            int(snap.get("samples") or 0),
        )
    except Exception:
        logger.debug("ai threshold evaluation failed", exc_info=True)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return round(s[k], 2)


def get_snapshot() -> dict:
    """Single-process or cross-process AI inference health."""
    # Pull cross-process state from Redis if available, merge with local.
    latencies = list(_state.latencies_ms)
    success = _state.success_count
    error = _state.error_count
    last_call_at = _state.last_call_at
    last_error = _state.last_error
    last_owner = _state.last_owner
    last_latency = _state.last_latency_ms

    c = _redis()
    if c:
        try:
            raw = c.get(f"nischint:{REDIS_NS}:state")
            if raw:
                d = json.loads(raw)
                redis_latencies = d.get("latencies_ms") or []
                # Prefer Redis when in-process is colder (started later).
                if not latencies or len(redis_latencies) > len(latencies):
                    latencies = redis_latencies
                # Counters always merge by max — they only grow.
                success = max(success, int(d.get("success_count") or 0))
                error = max(error, int(d.get("error_count") or 0))
                if not last_call_at and d.get("last_call_at"):
                    last_call_at = d.get("last_call_at")
                if not last_error:
                    last_error = d.get("last_error")
                if not last_owner:
                    last_owner = d.get("last_owner")
                if last_latency is None:
                    last_latency = d.get("last_latency_ms")
        except Exception as e:
            logger.debug(f"ai_metrics snapshot redis read failed: {e}")

    return {
        "calls_total":     success + error,
        "success_count":   success,
        "error_count":     error,
        "last_call_at":    last_call_at,
        "last_owner":      last_owner,
        "last_latency_ms": last_latency,
        "last_error":      last_error,
        "p50_ms":          _percentile(latencies, 50),
        "p95_ms":          _percentile(latencies, 95),
        "samples":         len(latencies),
    }


def reset() -> dict:
    with _lock:
        _state.latencies_ms.clear()
    c = _redis()
    if c:
        try:
            c.delete(f"nischint:{REDIS_NS}:state")
        except Exception:
            pass
    return {"reset_at": datetime.now(timezone.utc).isoformat()}
