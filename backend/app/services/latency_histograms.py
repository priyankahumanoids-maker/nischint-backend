"""Per-endpoint latency histograms — p50 / p95 / p99 over a rolling
last-N samples window. Redis-backed so percentiles are correct across
uvicorn workers AND across the api / scheduler process split.

Design contract:

  * **Path normalization.** Routes are bucketed by their FastAPI
    *route template* (e.g. `/api/users/{user_id}`), never the raw URL.
    This avoids cardinality blow-up from path params (UUIDs, ids).
    The middleware reads `request.scope["route"].path` and falls back
    to the raw `request.url.path` on 404 / unrouted (those land under a
    bucket like `__unrouted__` so we can see noise without polluting
    real route stats).

  * **Cross-process via Redis.** Every uvicorn worker LPUSHes into a
    per-endpoint list and LTRIMs to `MAX_SAMPLES`. The snapshot reader
    LRANGEs the whole list and computes percentiles. No locks needed
    because the list is append-only (LPUSH) and the read is a one-shot
    range. The hot path stays O(1) per request — no aggregation work.

  * **In-process fallback.** If Redis is unavailable, samples are
    buffered in a per-process `deque(maxlen=MAX_SAMPLES)` so the admin
    endpoint still returns *something* (better than 500). Counters
    keep counting; values are stitched in `get_snapshot` so neither
    storage layer leaks into the response shape.

  * **Hot-path safety.** `record()` *never* raises. Redis errors are
    logged at DEBUG and silently dropped — a synthetic-monitor probe
    failing to record latency must not break the 99.9 % of requests
    that are succeeding.

  * **No telemetry stream.** This module *records* and *reads*. Any
    "alert when p95 > X" decision lives in `health_thresholds.py`, not
    here — same architectural separation we enforced for `ai_metrics`
    and `scheduler_metrics`.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# ── Tunables ───────────────────────────────────────────────────────

# Rolling-window size per endpoint. 500 samples keeps p99 honest at
# 1 % granularity while staying well under Redis memory budgets
# (≈ 8 bytes × 500 × ~200 endpoints = 800 KB worst case).
MAX_SAMPLES = 500

REDIS_NS = "latency_hist"

# Endpoints expected to be high-volume; we expose a small allow-list
# for operator dashboards to highlight in v1. (Anything else is still
# tracked — this is purely a hint for UI sorting.)
HOT_ENDPOINTS = {
    "GET /api/health",
    "GET /api/public/status",
    "POST /api/auth/login",
    "GET /api/operator/command-center/{user_id}",
    "POST /api/safety/share-location",
    "POST /api/sos/trigger",
}


# ── In-process fallback state ──────────────────────────────────────

_lock = Lock()
# Key: "METHOD ROUTE_TEMPLATE" → deque of durations_ms
_local_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
# Cumulative counters (never trimmed) — operators want raw totals too.
_local_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "errors": 0})


def _redis():
    """Best-effort Redis client. Returns None on any failure."""
    try:
        from app.services.redis_service import _get_client
        return _get_client()
    except Exception:
        return None


# ── Public recorder API ────────────────────────────────────────────


def record(method: str, route_template: str, status_code: int, duration_ms: float) -> None:
    """Record one request. NEVER raises.

    `route_template` should be the FastAPI route pattern (e.g.
    `/api/users/{user_id}`) NOT the raw URL — the middleware is
    responsible for that normalization.
    """
    if not route_template or not method:
        return
    if duration_ms < 0:
        duration_ms = 0.0
    key = f"{method.upper()} {route_template}"

    # 1) Local fallback — always update, cheap, never throws.
    with _lock:
        _local_samples[key].append(float(duration_ms))
        _local_counts[key]["total"] += 1
        if status_code >= 500:
            _local_counts[key]["errors"] += 1

    # 2) Redis push — best-effort, swallow on failure.
    c = _redis()
    if c is None:
        return
    try:
        pipe = c.pipeline()
        samples_key = f"nischint:{REDIS_NS}:samples:{key}"
        counts_key = f"nischint:{REDIS_NS}:counts:{key}"
        pipe.lpush(samples_key, f"{duration_ms:.2f}")
        pipe.ltrim(samples_key, 0, MAX_SAMPLES - 1)
        pipe.expire(samples_key, 3600)  # 1h TTL — endpoint going cold drops out
        pipe.hincrby(counts_key, "total", 1)
        if status_code >= 500:
            pipe.hincrby(counts_key, "errors", 1)
        pipe.expire(counts_key, 86400)  # 24h TTL on counters
        pipe.sadd(f"nischint:{REDIS_NS}:index", key)
        pipe.expire(f"nischint:{REDIS_NS}:index", 86400)
        pipe.execute()
    except Exception as e:
        logger.debug(f"latency_histograms redis record failed for {key}: {e}")


# ── Percentile maths ───────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    # Nearest-rank: idx = ceil((pct/100) * n) - 1, clamped.
    idx = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return round(s[idx], 2)


# ── Snapshot reader ────────────────────────────────────────────────


def _list_endpoints() -> list[str]:
    """Union of endpoints known locally + endpoints registered in Redis."""
    local = set(_local_samples.keys())
    c = _redis()
    if c is not None:
        try:
            remote = c.smembers(f"nischint:{REDIS_NS}:index") or set()
            remote = {x.decode() if isinstance(x, bytes) else x for x in remote}
            local |= remote
        except Exception as e:
            logger.debug(f"latency_histograms index read failed: {e}")
    return sorted(local)


def _read_samples(key: str) -> list[float]:
    """Prefer Redis; fall back to in-process if Redis empty or down.

    We don't merge — whichever source has more samples wins, because
    interleaving uvicorn worker samples by ts is non-trivial and
    the percentile is only as honest as its denominator.
    """
    redis_samples: list[float] = []
    c = _redis()
    if c is not None:
        try:
            raw = c.lrange(f"nischint:{REDIS_NS}:samples:{key}", 0, MAX_SAMPLES - 1)
            for v in raw or []:
                try:
                    redis_samples.append(float(v.decode() if isinstance(v, bytes) else v))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"latency_histograms samples read failed for {key}: {e}")
    with _lock:
        local = list(_local_samples.get(key, ()))
    return redis_samples if len(redis_samples) >= len(local) else local


def _read_counts(key: str) -> dict[str, int]:
    """Counters from Redis if present, else local. Counters are cumulative."""
    c = _redis()
    if c is not None:
        try:
            raw = c.hgetall(f"nischint:{REDIS_NS}:counts:{key}") or {}
            if raw:
                decoded = {
                    (k.decode() if isinstance(k, bytes) else k):
                    int(v.decode() if isinstance(v, bytes) else v)
                    for k, v in raw.items()
                }
                if decoded.get("total"):
                    return {"total": decoded.get("total", 0), "errors": decoded.get("errors", 0)}
        except Exception as e:
            logger.debug(f"latency_histograms counts read failed for {key}: {e}")
    with _lock:
        return dict(_local_counts.get(key, {"total": 0, "errors": 0}))


def snapshot_endpoint(key: str) -> dict[str, Any]:
    """One-endpoint snapshot. Cheap — used by tests + the bulk reader."""
    samples = _read_samples(key)
    counts = _read_counts(key)
    return {
        "endpoint": key,
        "samples":  len(samples),
        "p50_ms":   _percentile(samples, 50),
        "p95_ms":   _percentile(samples, 95),
        "p99_ms":   _percentile(samples, 99),
        "min_ms":   round(min(samples), 2) if samples else None,
        "max_ms":   round(max(samples), 2) if samples else None,
        "total_requests": counts.get("total", 0),
        "error_count":    counts.get("errors", 0),
        "error_rate":     round(counts.get("errors", 0) / counts["total"], 4) if counts.get("total") else 0.0,
        "is_hot":   key in HOT_ENDPOINTS,
    }


def get_snapshot(top_n: int | None = None, sort_by: str = "p95_ms") -> dict[str, Any]:
    """Full snapshot of every endpoint we've recorded.

    `sort_by` ∈ {p50_ms, p95_ms, p99_ms, total_requests, error_rate}.
    `top_n` truncates after sort; default returns everything.
    """
    endpoints = [snapshot_endpoint(k) for k in _list_endpoints()]
    valid_sorts = {"p50_ms", "p95_ms", "p99_ms", "total_requests", "error_rate"}
    sort_key = sort_by if sort_by in valid_sorts else "p95_ms"
    # Endpoints with no samples for the chosen pct sort to the bottom.
    endpoints.sort(
        key=lambda e: (e.get(sort_key) is None, -(e.get(sort_key) or 0)),
    )
    if top_n is not None and top_n > 0:
        endpoints = endpoints[:top_n]
    return {
        "captured_at_ms":   int(time.time() * 1000),
        "max_samples_per_endpoint": MAX_SAMPLES,
        "sort_by":          sort_key,
        "endpoint_count":   len(endpoints),
        "endpoints":        endpoints,
    }


# ── Test / admin helpers ───────────────────────────────────────────


def reset_all() -> dict[str, int]:
    """Wipe both the local buffer and the Redis namespace. Returns
    counts of what was cleared so the admin can confirm. Idempotent.
    """
    with _lock:
        local_n = len(_local_samples)
        _local_samples.clear()
        _local_counts.clear()
    redis_n = 0
    c = _redis()
    if c is not None:
        try:
            for kind in ("samples", "counts"):
                cursor = 0
                while True:
                    cursor, keys = c.scan(
                        cursor=cursor, match=f"nischint:{REDIS_NS}:{kind}:*", count=200,
                    )
                    if keys:
                        c.delete(*keys)
                        redis_n += len(keys)
                    if cursor == 0:
                        break
            c.delete(f"nischint:{REDIS_NS}:index")
        except Exception as e:
            logger.warning(f"latency_histograms reset_all redis failed: {e}")
    return {"local_endpoints_cleared": local_n, "redis_keys_cleared": redis_n}
