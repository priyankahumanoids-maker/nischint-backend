# Live Deviation Engine — Phase 3
#
# Lightweight, real-time projection of how far the user has drifted from
# their behavior baseline (the "30-min batch Digital Twin"). Pure function:
# no DB queries, microsecond compute, safe to call on every location tick.
#
# Inputs:
#   baseline (dict)         — output of `get_or_create_baseline`
#   lat / lng (float)       — current GPS
#   now (datetime, optional) — defaults to UTC now
#   route_deviated (bool)   — from active GuardianSession
#   route_deviation_m       — from active GuardianSession
#   is_idle / idle_duration_s — from active GuardianSession
#
# Output (matches the `digital_twin.live_deviation` slot shipped in v1 envelope):
#   {
#     "status": "normal" | "slight" | "high" | "critical",
#     "score": 0.0..1.0,
#     "confidence": 0.0..1.0,
#     "reason": "human-readable summary" | None,
#     "factors": [{"factor": "...", "weight": 0.0..1.0}],
#     "computed_at": "ISO-8601",
#   }

import math
from datetime import datetime, timezone
from typing import Optional


# Tunable thresholds (kept in one place for ops review)
NEAR_KNOWN_LOCATION_M = 200.0           # within 200m of a common location → 0 deviation
FAR_FROM_KNOWN_M = 2000.0               # >2km → max location deviation
ROUTE_DEVIATION_FULL_M = 500.0          # 500m off planned route → max route signal
IDLE_FULL_SECONDS = 1800.0              # 30 min idle → max idle signal

STATUS_THRESHOLDS = [
    (0.75, "critical"),
    (0.50, "high"),
    (0.25, "slight"),
    (0.0,  "normal"),
]

# Per-signal weights (sum to 1.0)
SIGNAL_WEIGHTS = {
    "time": 0.30,
    "location": 0.30,
    "route": 0.20,
    "idle": 0.20,
}

REASON_PRIORITY = ["route", "idle", "location", "time"]
REASON_LABELS = {
    "time": "Active outside their usual hours",
    "location": "Outside common locations",
    "route": "Off the planned route",
    "idle": "Stationary for an unusual stretch",
}


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two lat/lng pairs."""
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _classify(score: float) -> str:
    for threshold, label in STATUS_THRESHOLDS:
        if score >= threshold:
            return label
    return "normal"


def _time_deviation(baseline: dict, hour: int) -> float:
    """0.0 if hour is `high`/`moderate` activity in baseline, scaling up to 0.7 for `low` at deep night."""
    active_hours = baseline.get("active_hours") or {}
    band = active_hours.get(str(hour), "normal")
    if band in ("high", "moderate"):
        return 0.0
    if band == "low":
        # Deeper night → stronger deviation signal
        if 0 <= hour <= 5 or hour >= 23:
            return 0.7
        return 0.4
    return 0.1  # unknown / "normal" band


def _location_deviation(baseline: dict, lat: float, lng: float) -> float:
    """0 if near a common location, scaling up to 1.0 if very far from any known cluster."""
    common = baseline.get("common_locations") or []
    if not common:
        return 0.0  # No baseline → can't say it's deviation; suppress.
    best_m = float("inf")
    for loc in common:
        try:
            d = _haversine_m(lat, lng, float(loc["lat"]), float(loc["lng"]))
        except (KeyError, TypeError, ValueError):
            continue
        if d < best_m:
            best_m = d
    if best_m == float("inf"):
        return 0.0
    if best_m <= NEAR_KNOWN_LOCATION_M:
        return 0.0
    if best_m >= FAR_FROM_KNOWN_M:
        return 1.0
    # Linear ramp between near and far
    span = FAR_FROM_KNOWN_M - NEAR_KNOWN_LOCATION_M
    return round((best_m - NEAR_KNOWN_LOCATION_M) / span, 3)


def _route_signal(route_deviated: bool, route_deviation_m: float) -> float:
    if not route_deviated:
        return 0.0
    return round(min(max(float(route_deviation_m or 0) / ROUTE_DEVIATION_FULL_M, 0.0), 1.0), 3)


def _idle_signal(is_idle: bool, idle_duration_s: float) -> float:
    if not is_idle:
        return 0.0
    return round(min(max(float(idle_duration_s or 0) / IDLE_FULL_SECONDS, 0.0), 1.0), 3)


def _confidence(baseline: dict) -> float:
    """How much we trust this deviation signal — driven by baseline maturity."""
    if not baseline:
        return 0.0
    days = float(baseline.get("data_days") or 0)
    common_count = len(baseline.get("common_locations") or [])
    base_confidence = float(baseline.get("confidence") or 0.0)
    # Mature baseline (≥7 days + ≥2 common locations) → trust ≥ 0.8
    if days >= 7 and common_count >= 2:
        return max(base_confidence, 0.8)
    if days >= 3:
        return max(base_confidence, 0.5)
    return min(base_confidence, 0.3)


def compute_live_deviation(
    baseline: Optional[dict],
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    now: Optional[datetime] = None,
    route_deviated: bool = False,
    route_deviation_m: float = 0.0,
    is_idle: bool = False,
    idle_duration_s: float = 0.0,
) -> dict:
    """
    Pure live deviation compute. See module docstring for shape.
    """
    now = now or datetime.now(timezone.utc)

    if not baseline:
        return {
            "status": "unknown",
            "score": 0.0,
            "confidence": 0.0,
            "reason": None,
            "factors": [],
            "computed_at": now.isoformat(),
        }

    signals = {
        "time": _time_deviation(baseline, now.hour),
        "location": _location_deviation(baseline, lat, lng) if lat is not None and lng is not None else 0.0,
        "route": _route_signal(route_deviated, route_deviation_m),
        "idle": _idle_signal(is_idle, idle_duration_s),
    }

    # Weighted fusion
    score = 0.0
    for k, v in signals.items():
        score += SIGNAL_WEIGHTS[k] * v
    score = round(min(max(score, 0.0), 1.0), 3)

    # Pick primary reason: highest-priority signal that's non-trivial
    reason = None
    factors = []
    for k in REASON_PRIORITY:
        if signals[k] >= 0.25:
            if reason is None:
                reason = REASON_LABELS[k]
            factors.append({"factor": k, "weight": signals[k]})

    return {
        "status": _classify(score),
        "score": score,
        "confidence": _confidence(baseline),
        "reason": reason,
        "factors": factors,
        "computed_at": now.isoformat(),
    }
