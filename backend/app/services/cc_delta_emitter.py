# Command Center Delta Emitter — Phase 5
#
# Single source of truth for emitting structured WS deltas to operators.
# Every payload follows this exact envelope:
#
#   {
#     "type": "COMMAND_CENTER_DELTA",
#     "user_id": "<uuid>",
#     "timestamp": "ISO-8601",
#     "version": "v1",
#     "changes": {
#       "risk.final_score": 7.5,
#       "live_deviation.status": "high",
#       "environment.weather.condition": "thunderstorm"
#     }
#   }
#
# Rules:
#   • Only changed dotted paths are emitted (never the full payload).
#   • Always includes timestamp + version so the frontend can reject stale
#     or wrong-shaped patches.
#   • Per-user diff cache lives in Redis (`cc:state:{user_id}`, 1h TTL) so
#     emitters don't have to track previous state themselves.
#
# This module replaces ad-hoc broadcasts (twin_delta, risk_score_change,
# location_update etc.) with one canonical envelope.

import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services import redis_service
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

DELTA_VERSION = "v1"
DELTA_EVENT_TYPE = "COMMAND_CENTER_DELTA"
REDIS_NAMESPACE = "cc_state"
REDIS_TTL_SECONDS = 60 * 60  # 1h

# ── Phase 6: server-side delta metrics ───────────────────────────────
# Cumulative counters live forever; per-minute buckets give us a rolling
# rate without scanning a list. Each emit/skip/fail bumps both.
METRICS_NAMESPACE = "metrics_cc_delta"


def _record_metric(name: str) -> None:
    """Bump a cumulative counter and the current 60s bucket. Best-effort."""
    try:
        client = redis_service._get_client()  # type: ignore[attr-defined]
        if not client:
            return
        bucket = int(time.time()) // 60
        bucket_key = f"nischint:{METRICS_NAMESPACE}:{name}:b{bucket}"
        total_key = f"nischint:{METRICS_NAMESPACE}:total_{name}"
        client.incr(bucket_key)
        client.expire(bucket_key, 180)
        client.incr(total_key)
    except Exception:
        # Telemetry must never break the hot path
        pass


def get_metrics_snapshot() -> dict:
    """Return cumulative counters + a rolling 1-min rate for emitted deltas."""
    snap = {"emitted": 0, "skipped": 0, "failed": 0, "rate_per_min": 0}
    try:
        client = redis_service._get_client()  # type: ignore[attr-defined]
        if not client:
            return snap
        for k in ("emitted", "skipped", "failed"):
            v = client.get(f"nischint:{METRICS_NAMESPACE}:total_{k}")
            snap[k] = int(v) if v else 0
        # Rate: average of the previous 2 full minutes (smoother than current bucket)
        now_bucket = int(time.time()) // 60
        rates = []
        for offset in (1, 2):
            v = client.get(f"nischint:{METRICS_NAMESPACE}:emitted:b{now_bucket - offset}")
            if v is not None:
                rates.append(int(v))
        if rates:
            snap["rate_per_min"] = round(sum(rates) / len(rates))
    except Exception:
        logger.exception("[CC_DELTA] metrics snapshot failed")
    return snap


def _flatten(obj: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Flatten a nested dict into dotted-path leaves. Lists are kept whole."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                _flatten(v, key, out)
            else:
                out[key] = v
    else:
        out[prefix] = obj
    return out


def diff_paths(
    old: dict[str, Any] | None,
    new: dict[str, Any],
    *,
    include_only: Iterable[str] | None = None,
) -> dict[str, Any]:
    """
    Return only the dotted-path leaves that changed (or are new) in `new`
    relative to `old`. If `include_only` is given, restrict to those top-level
    namespaces (e.g. ["risk", "live_deviation"]).
    """
    old_flat = _flatten(old or {})
    new_flat = _flatten(new or {})
    changes: dict[str, Any] = {}
    for k, v in new_flat.items():
        if include_only and not any(k == ns or k.startswith(ns + ".") for ns in include_only):
            continue
        if old_flat.get(k) != v:
            changes[k] = v
    return changes


async def emit_cc_delta(
    user_id: str,
    changes: dict[str, Any],
    *,
    timestamp: datetime | None = None,
    scope: str | None = None,
) -> bool:
    """
    Broadcast a `COMMAND_CENTER_DELTA` envelope to the operator channel.
    Returns True when broadcast succeeded.

    `scope`: optional string (e.g. "fleet"). When set, the envelope includes
    a `scope` field so frontend handlers can route fleet-level updates
    differently from per-user updates. Default (None) is per-user, matching
    Phase 5 behavior.
    """
    if not changes:
        logger.debug(
            "[CC_DELTA] skip user=%s reason=no_changes",
            user_id,
        )
        _record_metric("skipped")
        return False

    ts = timestamp or datetime.now(timezone.utc)
    envelope_data = {
        "user_id": str(user_id),
        "timestamp": ts.isoformat(),
        "version": DELTA_VERSION,
        "changes": changes,
    }
    if scope:
        envelope_data["scope"] = scope

    try:
        await broadcaster.broadcast_to_operators(DELTA_EVENT_TYPE, envelope_data)
        logger.info(
            "[CC_DELTA] emit user=%s paths=%s ts=%s",
            user_id, list(changes.keys()), ts.isoformat(),
        )
        _record_metric("emitted")
        return True
    except Exception:
        logger.exception("[CC_DELTA] broadcast_failed user=%s paths=%s", user_id, list(changes.keys()))
        _record_metric("failed")
        return False


def cache_state_slice(user_id: str, namespace: str, value: Any) -> None:
    """Store the latest snapshot for a top-level namespace (e.g. 'risk').

    Chaos-safe: if Redis is unavailable, the next emitter call will treat the
    cache as cold (full diff) — never raises.
    """
    try:
        ok = redis_service.set_json(
            REDIS_NAMESPACE,
            f"{user_id}:{namespace}",
            value,
            ttl=REDIS_TTL_SECONDS,
        )
        if not ok:
            logger.warning("[CC_DELTA] cache_miss_write user=%s ns=%s reason=redis_unavailable", user_id, namespace)
    except Exception:
        logger.exception("[CC_DELTA] cache_state_slice failed user=%s ns=%s", user_id, namespace)


def get_state_slice(user_id: str, namespace: str) -> Any:
    """Read the previously broadcast snapshot for a namespace.

    Chaos-safe: returns None on Redis failure → emitter falls back to a
    full diff against an empty baseline (still correct, just larger payload).
    """
    try:
        val = redis_service.get_json(REDIS_NAMESPACE, f"{user_id}:{namespace}")
        if val is None:
            logger.debug("[CC_DELTA] cache_miss user=%s ns=%s", user_id, namespace)
        else:
            logger.debug("[CC_DELTA] cache_hit user=%s ns=%s", user_id, namespace)
        return val
    except Exception:
        logger.exception("[CC_DELTA] cache_get_failed user=%s ns=%s", user_id, namespace)
        return None


async def emit_namespaced_delta(
    user_id: str,
    namespace: str,
    new_value: dict[str, Any],
) -> bool:
    """
    Helper: diff `new_value` against the cached snapshot for `namespace`, emit
    only the changed dotted paths under that namespace, then update the
    cache. No-op when nothing changed.
    """
    if not isinstance(new_value, dict):
        return False
    prev = get_state_slice(user_id, namespace) or {}
    raw_changes = diff_paths(prev, new_value)
    if not raw_changes:
        logger.debug("[CC_DELTA] skip user=%s ns=%s reason=no_diff", user_id, namespace)
        _record_metric("skipped")
        return False
    namespaced = {f"{namespace}.{k}": v for k, v in raw_changes.items()}
    cache_state_slice(user_id, namespace, new_value)
    return await emit_cc_delta(user_id, namespaced)
