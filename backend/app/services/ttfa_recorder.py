"""NISCH-003 — Time-To-First-Alert (TTFA) recorder + percentile stats.

A tiny, lock-free, bounded ring buffer of recent alert dispatch latencies.
Populated by `alert_trigger.trigger_alert` (the single front door) and
read by the `/api/_dev/alert-ttfa/stats` admin endpoint.

Why in-process + Redis mirror (not pure logs)?
- Log parsing breaks on rotation, format drift, multi-instance fan-out.
- An in-process deque is O(1) on write and O(n) on percentile compute
  with `n` capped at `_MAX_SAMPLES`. At 1024 samples the p95 query is
  microseconds.
- Redis mirror (LIST + LTRIM) makes the pod-local view aggregate across
  instances. Best-effort — a Redis blip never blocks an alert.

Strict design:
- `record(...)` MUST never raise. It is called inside the alert path.
- Reading is read-only. No mutation from query handlers.
- No bucketing by time on write — we keep raw samples and filter on read
  by `(now - sample.ts) <= since_s`. Simpler, correct.

Sample schema (per entry):
    {
        "kind":      str,      # e.g. "voice_distress"
        "ttfa_ms":   int,
        "ts":        float,    # unix epoch seconds
        "guardians": int,      # how many SSE recipients
        "louder":    bool,
        "priority":  str,      # from formatter envelope
    }
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections import deque
from typing import Iterable, Optional

from app.services import redis_service

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────
_MAX_SAMPLES = 1024            # per-process ring buffer cap
_REDIS_LIST_KEY = "nischint:alert:ttfa:samples"  # mirror key
_REDIS_TRIM_KEEP = 4096         # cross-instance ring cap
_REDIS_TIMEOUT_S = 0.05         # never spend >50ms on the mirror


# ── In-process buffer ───────────────────────────────────────────────
_BUFFER: deque[dict] = deque(maxlen=_MAX_SAMPLES)


def reset_buffer() -> None:
    """Test-only helper. Clears the local ring; does NOT touch Redis."""
    _BUFFER.clear()


def record(
    *,
    kind: str,
    ttfa_ms: int,
    guardians: int = 0,
    louder: bool = False,
    priority: Optional[str] = None,
) -> None:
    """Append one TTFA sample. Best-effort — never raises."""
    try:
        sample = {
            "kind":      str(kind or "unknown").lower(),
            "ttfa_ms":   int(ttfa_ms),
            "ts":        time.time(),
            "guardians": int(guardians),
            "louder":    bool(louder),
            "priority":  str(priority) if priority is not None else None,
        }
        _BUFFER.append(sample)

        # Best-effort Redis mirror — guarded with hard timeout-ish path.
        if redis_service.is_available():
            try:
                client = redis_service._get_client()
                if client is not None:
                    pipe = client.pipeline()
                    pipe.lpush(_REDIS_LIST_KEY, json.dumps(sample))
                    pipe.ltrim(_REDIS_LIST_KEY, 0, _REDIS_TRIM_KEEP - 1)
                    pipe.execute()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[TTFA_RECORD] redis mirror failed: {e}")
    except Exception as e:  # noqa: BLE001
        # Absolutely must not blow up the alert path.
        logger.warning(f"[TTFA_RECORD] record() swallowed exception: {e}")


# ── Read paths ──────────────────────────────────────────────────────
def _redis_samples(limit: int) -> list[dict]:
    """Best-effort fetch from the Redis mirror. Returns [] on any failure."""
    if not redis_service.is_available():
        return []
    try:
        client = redis_service._get_client()
        if client is None:
            return []
        raw_list = client.lrange(_REDIS_LIST_KEY, 0, max(limit - 1, 0))
        out: list[dict] = []
        for raw in raw_list:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[TTFA_READ] redis read failed: {e}")
        return []


def _merge_unique(local: Iterable[dict], remote: Iterable[dict]) -> list[dict]:
    """Combine local + remote samples, deduping on (ts, kind, ttfa_ms).
    Local wins on collision. Order not guaranteed."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for s in list(local) + list(remote):
        key = (round(float(s.get("ts", 0)), 4), s.get("kind"), int(s.get("ttfa_ms", 0)))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _percentile(sorted_vals: list[int], q: float) -> int:
    """Linear-interpolation percentile. q in [0, 100]. Empty → 0."""
    if not sorted_vals:
        return 0
    if q <= 0:
        return sorted_vals[0]
    if q >= 100:
        return sorted_vals[-1]
    rank = (q / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return int(sorted_vals[lo])
    frac = rank - lo
    return int(round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac))


def _summarize(samples: list[dict]) -> dict:
    """Compute summary stats over a flat list of samples."""
    n = len(samples)
    if n == 0:
        return {
            "count": 0, "p50": 0, "p95": 0, "p99": 0,
            "min": 0, "max": 0, "mean": 0,
            "louder_ratio": 0.0,
        }
    vals = sorted(int(s.get("ttfa_ms", 0)) for s in samples)
    louder_count = sum(1 for s in samples if s.get("louder"))
    return {
        "count":  n,
        "p50":    _percentile(vals, 50),
        "p95":    _percentile(vals, 95),
        "p99":    _percentile(vals, 99),
        "min":    vals[0],
        "max":    vals[-1],
        "mean":   int(round(sum(vals) / n)),
        "louder_ratio": round(louder_count / n, 4),
    }


def get_stats(
    *,
    since_s: int = 3600,
    kind: Optional[str] = None,
    include_redis: bool = True,
) -> dict:
    """Return TTFA percentile stats.

    Args:
        since_s:        only consider samples newer than `now - since_s`.
                        Default 1 hour. 0 = no time filter.
        kind:           if set, restrict to that kind in addition to the
                        always-emitted `by_kind` breakdown.
        include_redis:  also pull cross-instance samples from the Redis
                        mirror. Default True.

    Returns:
        {
            "since_s": int,
            "now_ts": float,
            "samples_considered": int,
            "overall": {count, p50, p95, p99, min, max, mean, louder_ratio},
            "by_kind": { kind: {...same shape...} },
            "filter_kind": str | None,
            "filter_kind_stats": {...} | None,
            "sources": { "local": int, "redis": int },
        }
    """
    now = time.time()
    cutoff = now - since_s if since_s and since_s > 0 else 0.0

    local = list(_BUFFER)
    remote = _redis_samples(_REDIS_TRIM_KEEP) if include_redis else []
    merged = _merge_unique(local, remote)

    in_window = [s for s in merged if float(s.get("ts", 0)) >= cutoff]

    by_kind: dict[str, list[dict]] = {}
    for s in in_window:
        by_kind.setdefault(str(s.get("kind", "unknown")), []).append(s)

    out = {
        "since_s":             int(since_s),
        "now_ts":              now,
        "samples_considered":  len(in_window),
        "overall":             _summarize(in_window),
        "by_kind":             {k: _summarize(v) for k, v in sorted(by_kind.items())},
        "filter_kind":         kind,
        "filter_kind_stats":   None,
        "sources": {
            "local":  len(local),
            "redis":  len(remote),
        },
    }
    if kind:
        out["filter_kind_stats"] = _summarize(by_kind.get(kind.lower(), []))
    return out


def get_recent_events(n: int = 10) -> list[dict]:
    """Return the most recent `n` TTFA samples, oldest → newest.

    Used by `sla_monitor` to attach context to red/amber SLA transitions
    so the on-call engineer reads "what slowed down" directly in the
    Slack/Discord message instead of grepping logs.

    Pure read against the in-process ring buffer. Excludes the Redis
    mirror (cross-instance ordering isn't trustworthy) — local view is
    fine because the SLA transition is itself a local-process verdict.
    """
    if n <= 0:
        return []
    snap = list(_BUFFER)[-n:]
    return [
        {
            "kind":     s.get("kind"),
            "ttfa_ms":  int(s.get("ttfa_ms", 0)),
            "ts":       float(s.get("ts", 0)),
            "priority": s.get("priority"),
            "louder":   bool(s.get("louder", False)),
            "guardians": int(s.get("guardians", 0)),
            "status":   "fail" if s.get("priority") == "warning" and str(s.get("kind", "")).startswith("twilio:") else "ok",
        }
        for s in snap
    ]


__all__ = ["record", "get_stats", "get_recent_events", "reset_buffer"]
