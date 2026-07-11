"""NISCH-011 — Four-tier temporal memory.

Locked policy from the product spec:

  5 min   → Redis only (hot window, write-heavy)
  30 min  → Redis (slightly slower decay)
  6 hour  → Postgres (durable, queryable)
  24 hour → Postgres (durable, queryable)

WHY split storage:
  Writing every 5-min update to Postgres for every tracked user
  doesn't scale. Redis absorbs the hot-write load; Postgres holds
  the durable longer-range memory the detector needs for stable
  Z-score baselines.

The 5/30-min windows are sorted-sets keyed by member-timestamp,
so a single ZRANGEBYSCORE call returns the window contents. The
6/24-hour windows are derived live from `safety_incidents` or
the detector's own writes — we DO NOT mirror Redis writes into
Postgres; that would defeat the scale fix.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Iterable, Optional

from app.services import redis_service

logger = logging.getLogger(__name__)


# Window lengths in seconds — locked.
WINDOW_5_MIN_S = 5 * 60
WINDOW_30_MIN_S = 30 * 60
WINDOW_6_HOUR_S = 6 * 3600
WINDOW_24_HOUR_S = 24 * 3600

# TTL on Redis windows = 2× the window length, so a late call
# still finds something useful in the band. Keys auto-evict.
_REDIS_TTL_5_MIN_S = WINDOW_5_MIN_S * 2
_REDIS_TTL_30_MIN_S = WINDOW_30_MIN_S * 2


def _key_5m(entity_id) -> str:
    return f"nischint:behavioral:5m:{entity_id}"


def _key_30m(entity_id) -> str:
    return f"nischint:behavioral:30m:{entity_id}"


def record_event(entity_id, feature_vector: dict,
                 *, now_ts: Optional[float] = None) -> dict:
    """Append a feature observation to the 5-min and 30-min Redis
    windows. Best-effort — Redis errors degrade silently because
    a missed 5-min sample is not safety-critical; the detector
    has the 30-min, 6-hour, and 24-hour fallbacks.

    Returns a dict describing what was written (or skipped) for
    test assertions + structured logging."""
    ts = float(now_ts if now_ts is not None else time.time())
    member = json.dumps(
        {"ts": ts, "f": feature_vector}, separators=(",", ":"),
        default=str,
    )
    result = {"5m": False, "30m": False}
    try:
        r = redis_service._get_client()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "behavioral_temporal_redis_unavailable",
            extra={"event": "behavioral_temporal_redis_unavailable",
                   "error_type": type(e).__name__},
        )
        return result

    if r is None:
        return result

    # 5-min sorted set + trim.
    try:
        k5 = _key_5m(entity_id)
        r.zadd(k5, {member: ts})
        r.zremrangebyscore(k5, "-inf", ts - WINDOW_5_MIN_S)
        r.expire(k5, _REDIS_TTL_5_MIN_S)
        result["5m"] = True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "behavioral_temporal_5m_write_failed",
            extra={"event": "behavioral_temporal_5m_write_failed",
                   "error_type": type(e).__name__},
        )

    # 30-min sorted set + trim.
    try:
        k30 = _key_30m(entity_id)
        r.zadd(k30, {member: ts})
        r.zremrangebyscore(k30, "-inf", ts - WINDOW_30_MIN_S)
        r.expire(k30, _REDIS_TTL_30_MIN_S)
        result["30m"] = True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "behavioral_temporal_30m_write_failed",
            extra={"event": "behavioral_temporal_30m_write_failed",
                   "error_type": type(e).__name__},
        )

    return result


def _decode_members(raw: Iterable) -> list[dict]:
    """Strict decode. Bad payloads are silently skipped — a single
    corrupted entry must not poison the window read."""
    out: list[dict] = []
    for m in raw:
        try:
            if isinstance(m, bytes):
                m = m.decode("utf-8")
            out.append(json.loads(m))
        except Exception:  # noqa: BLE001
            continue
    return out


def read_window(entity_id, *, window_s: int = WINDOW_5_MIN_S,
                now_ts: Optional[float] = None) -> list[dict]:
    """Return the recorded events in [now-window_s, now] for the
    entity's hot Redis window. Returns [] on Redis failure."""
    if window_s not in (WINDOW_5_MIN_S, WINDOW_30_MIN_S):
        raise ValueError(
            f"window_s must be {WINDOW_5_MIN_S} or "
            f"{WINDOW_30_MIN_S}, got {window_s}"
        )
    ts = float(now_ts if now_ts is not None else time.time())
    key = _key_5m(entity_id) if window_s == WINDOW_5_MIN_S \
        else _key_30m(entity_id)
    try:
        r = redis_service._get_client()
        if r is None:
            return []
        raw = r.zrangebyscore(key, ts - window_s, ts)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "behavioral_temporal_read_failed",
            extra={"event": "behavioral_temporal_read_failed",
                   "window_s": window_s,
                   "error_type": type(e).__name__},
        )
        return []
    return _decode_members(raw)


__all__ = [
    "WINDOW_5_MIN_S", "WINDOW_30_MIN_S",
    "WINDOW_6_HOUR_S", "WINDOW_24_HOUR_S",
    "record_event", "read_window",
]
