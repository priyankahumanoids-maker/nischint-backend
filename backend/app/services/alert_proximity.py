"""NISCH-002B — Co-location suppression.

When a guardian is standing right next to the child, we shouldn't push
them an SSE alert about something *they're already there for*. That's
noise → alert fatigue → the trust tax we're trying to avoid.

Strict design rules:
* **Fail-safe by default**: any uncertainty (no recent fix, stale fix,
  bad data) → return `False` (NOT co-located) → DO notify. Never silence
  on missing data. Every `is_co_located` short-circuit returns False.
* **Pure-ish**: takes coordinates, returns bool. No DB, no Redis. Caller
  is responsible for fetching `User.last_known_*` and passing them in.
* **Never applied to life-safety**: SOS / voice_distress / fall paths
  MUST bypass this filter. Co-location is for warning-tier alerts only
  (geofence_breach, low_battery, etc.). Caller decides.

Threshold: 150 m. Generous enough to cover a single building / parking
lot but tight enough that a guardian one block away still gets the
push.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional


# ── Tunables ────────────────────────────────────────────────────────
DEFAULT_RADIUS_M = 150
DEFAULT_FRESHNESS_S = 5 * 60  # 5 min — older fix → "no idea where they are"


# ── Math (Haversine) ───────────────────────────────────────────────
_EARTH_R_M = 6_371_000


def haversine_m(
    lat1: float, lng1: float,
    lat2: float, lng2: float,
) -> float:
    """Great-circle distance in metres. Plain math; no external libs."""
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlng / 2) ** 2
    )
    return 2 * _EARTH_R_M * math.asin(math.sqrt(min(1.0, max(0.0, a))))


# ── Public API ──────────────────────────────────────────────────────
def is_co_located(
    *,
    guardian_lat: Optional[float],
    guardian_lng: Optional[float],
    guardian_last_at: Optional[datetime],
    child_lat: Optional[float],
    child_lng: Optional[float],
    radius_m: int = DEFAULT_RADIUS_M,
    freshness_s: int = DEFAULT_FRESHNESS_S,
    now: Optional[datetime] = None,
) -> bool:
    """Return True iff guardian is **demonstrably** within `radius_m` of
    the child *right now*.

    All arguments are keyword-only to prevent accidental positional
    misuse on a function whose semantics are safety-critical.

    Returns False (= not co-located → DO notify) on:
      * Any missing coordinate
      * Stale guardian fix (older than `freshness_s`)
      * Any arithmetic edge case
    """
    if guardian_lat is None or guardian_lng is None:
        return False
    if child_lat is None or child_lng is None:
        return False
    if guardian_last_at is None:
        return False

    # Freshness check — old fixes are worse than no fix.
    n = now or datetime.now(timezone.utc)
    last_at = guardian_last_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    age_s = (n - last_at).total_seconds()
    if age_s < 0 or age_s > freshness_s:
        return False

    try:
        d = haversine_m(
            float(guardian_lat), float(guardian_lng),
            float(child_lat),    float(child_lng),
        )
    except (TypeError, ValueError):
        return False

    return d <= radius_m


# Kinds where co-location suppression is allowed. Critical / life-safety
# kinds are **never** suppressed — caller must explicitly opt-in.
SUPPRESSIBLE_KINDS: frozenset[str] = frozenset({
    "geofence_breach",
    "safe_zone_exit",
    "wandering",
    "low_battery",
    "device_offline",
    "minor_deviation",
    "check_in_request",
    "check_in_pending",
    "arrived_safely",
    "resolved",
})


def is_suppressible_kind(kind: str) -> bool:
    """Whether co-location suppression *may* apply to this kind."""
    return (kind or "").strip().lower() in SUPPRESSIBLE_KINDS


__all__ = [
    "is_co_located",
    "is_suppressible_kind",
    "haversine_m",
    "DEFAULT_RADIUS_M",
    "DEFAULT_FRESHNESS_S",
    "SUPPRESSIBLE_KINDS",
]
