"""Incident root-cause classifier — lightweight, snapshot-driven.

Strict scope: classify an incident snapshot into ONE of the
infrastructure domains: ``scheduler | ai | queue | db | redis``.

Why not just trust ``trigger_source``?
  Because the metric that fires the threshold is rarely the root cause.
  A queue back-pressure event often surfaces *first* as AI p95 climbing
  (workers blocked waiting on Redis), which itself surfaces as scheduler
  drift (the dispatch loop blocks on the AI worker handshake). The
  trigger source is a *symptom*. The root cause is usually upstream.

Heuristic — upstream-first ordering:
  queue (most upstream)  →  ai  →  scheduler (most downstream)

We walk that order and pick the FIRST domain that has breached its own
threshold inside the snapshot. If nothing breached (defensive), we fall
back to ``trigger_source`` as the best-available signal.

Auth-source classification (separate axis):
  ``trigger_source == "auth"`` means `get_current_user` p95 crossed
  500 ms — the auth path. Two upstream culprits:
    * **`redis`** — the Upstash Redis serving the user_cache is slow
      or unreachable. Symptom: `redis.ping_ms` is high or
      `redis.available=False` in the snapshot.
    * **`db`**    — the Mumbai pooler is slow, forcing user_cache
      misses to pay the full ~2 s round-trip. Symptom: high
      `auth.misses_window / auth.samples` ratio.
  Default fallback when neither probe is conclusive: ``db`` (Mumbai
  pooler is the historically dominant suspect for this path).

Thresholds mirror the live ones in `health_thresholds.py` so the
classifier and the firing engine never disagree.
"""
from __future__ import annotations
from typing import Literal, Any

# Mirror of health_thresholds.py — keep in sync.
_QUEUE_WARN = 100
_QUEUE_DEGRADED = 500
_AI_P95_DEGRADED_MS = 3000.0
_SCHED_DRIFT_P95_MS = 750.0  # warning band; degraded is 1500

# Auth-domain probe thresholds. Tuned to be conservative — only
# classify "redis" when the signal is clear; default to "db" otherwise.
_REDIS_PING_SLOW_MS = 100.0
_AUTH_MISS_RATE_DB_TRIP = 0.30


Domain = Literal["scheduler", "ai", "queue", "db", "redis"]


def _queue_breach(snap: dict | None) -> bool:
    if not snap:
        return False
    pending = 0
    queues = snap.get("by_stream") or snap.get("queues") or {}
    if isinstance(queues, dict):
        for v in queues.values():
            if isinstance(v, dict):
                pending += int(v.get("pending", 0) or 0)
    # Top-level fallback (newer shape from `get_queue_stats`)
    if not pending and isinstance(snap.get("pending_total"), (int, float)):
        pending = int(snap["pending_total"])
    return pending >= _QUEUE_WARN


def _ai_breach(snap: dict | None) -> bool:
    if not snap:
        return False
    p95 = snap.get("p95_ms")
    errors = int(snap.get("error_count") or snap.get("errors") or 0)
    if isinstance(p95, (int, float)) and p95 >= _AI_P95_DEGRADED_MS:
        return True
    samples = int(snap.get("samples") or 0)
    if errors > 0 and samples > 0 and (errors / samples) >= 0.10:
        return True
    return False


def _scheduler_breach(snap: dict | None) -> bool:
    if not snap:
        return False
    drift = snap.get("drift_p95_ms")
    missed = int(snap.get("missed_total") or snap.get("missed") or 0)
    errors = int(snap.get("error_total") or snap.get("errors") or 0)
    if isinstance(drift, (int, float)) and drift >= _SCHED_DRIFT_P95_MS:
        return True
    if missed > 0 or errors > 0:
        return True
    return False


def _classify_auth(snap: dict) -> Domain:
    """Auth-source classifier — discriminates db vs redis on the
    `get_current_user` slow-path.

    Read priority: most-conclusive signal first.
      1. Redis unreachable or ping_ms > 100 → ``redis``.
      2. user_cache miss-rate > 30 % → ``db`` (every miss pays the
         Mumbai pooler round-trip).
      3. Default → ``db`` (historical dominant suspect for this path).
    """
    auth:  dict[str, Any] = snap.get("auth") or {}
    redis: dict[str, Any] = snap.get("redis") or {}

    # Signal 1 — Redis probe (clearer fault → classify first).
    if redis:
        if redis.get("available") is False:
            return "redis"
        ping = redis.get("ping_ms")
        if isinstance(ping, (int, float)) and ping >= _REDIS_PING_SLOW_MS:
            return "redis"

    # Signal 2 — high cache-miss rate forces full DB lookups.
    samples = int(auth.get("samples") or 0)
    misses  = int(auth.get("misses_window") or 0)
    if samples > 0:
        miss_rate = misses / samples
        if miss_rate >= _AUTH_MISS_RATE_DB_TRIP:
            return "db"

    # Default — Mumbai pooler is the historically dominant suspect.
    return "db"


def classify_root_cause(snapshot: dict | None, *,
                        trigger_source: str | None = None) -> Domain:
    """Return the upstream-most breached domain.

    `snapshot` is the same JSON shape produced by
    `system_incident_engine._capture_snapshot` (i.e. has top-level
    ``scheduler`` / ``ai`` / ``queue`` / ``auth`` / ``redis`` sub-dicts).
    """
    snap = snapshot or {}

    # REL-04 — DB pool exhaustion always classifies as `db`. The
    # symptom space is narrow: SQLAlchemy pool saturation manifests as
    # blocked acquire calls, never as scheduler drift or AI p95.
    if trigger_source == "database_pool":
        return "db"

    # Auth-source incidents are their own classification axis — the
    # symptom (slow `get_current_user`) has well-known root causes
    # that don't overlap with queue/ai/scheduler back-pressure.
    if trigger_source == "auth":
        return _classify_auth(snap)

    sched: dict[str, Any] = snap.get("scheduler") or {}
    ai:    dict[str, Any] = snap.get("ai") or {}
    queue: dict[str, Any] = snap.get("queue") or {}

    # Upstream → downstream order.
    if _queue_breach(queue):
        return "queue"
    if _ai_breach(ai):
        return "ai"
    if _scheduler_breach(sched):
        return "scheduler"

    # Defensive — nothing crossed in the snapshot but the engine still
    # opened an incident. Trust the firing source.
    if trigger_source in ("scheduler", "ai", "queue"):
        return trigger_source  # type: ignore[return-value]
    return "scheduler"
