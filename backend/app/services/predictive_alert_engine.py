# Predictive Danger Alert Engine
# Evaluates risk of upcoming route segments and fires alerts before the user enters danger.
# Uses safe_zone_engine for risk scoring, safe_route_engine for alternative routes.

import logging
import math
import time as _time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.safe_zone_engine import (
    _fetch_zones, _compute_crime_density, generate_zone_id,
    _classify_risk, _haversine, _get_tod_multiplier,
)

logger = logging.getLogger(__name__)

# Speed-based lookahead distances (meters)
LOOKAHEAD = {"walking": 250, "bike": 350, "vehicle": 550}  # includes +50m GPS buffer
SPEED_THRESHOLDS = {"walking": 2.0, "bike": 6.0}  # m/s boundaries

# Alert cooldown: 5 min per (user_id, zone_id)
_cooldown: dict[str, float] = {}
COOLDOWN_S = 300

# Route segment cache: route_key -> (timestamp, segments)
_route_cache: dict[str, tuple[float, list]] = {}
ROUTE_CACHE_TTL = 300  # 5 min


def _detect_mode(speed_mps: float) -> str:
    if speed_mps < SPEED_THRESHOLDS["walking"]:
        return "walking"
    if speed_mps < SPEED_THRESHOLDS["bike"]:
        return "bike"
    return "vehicle"


def _is_cooled_down(user_id: str, zone_id: str) -> bool:
    key = f"{user_id}:{zone_id}"
    last = _cooldown.get(key, 0)
    return (_time.time() - last) < COOLDOWN_S


def _mark_alerted(user_id: str, zone_id: str):
    _cooldown[f"{user_id}:{zone_id}"] = _time.time()


def _get_cached_segments(route_key: str) -> list | None:
    entry = _route_cache.get(route_key)
    if entry and (_time.time() - entry[0]) < ROUTE_CACHE_TTL:
        return entry[1]
    return None


def _cache_segments(route_key: str, segments: list):
    _route_cache[route_key] = (_time.time(), segments)


def _segments_ahead(lat: float, lng: float, route_coords: list, lookahead_m: float) -> list[dict]:
    """Extract route segments that are ahead of the user within lookahead distance.
    Uses direction-based filtering: only segments with positive dot product (ahead)."""
    if not route_coords or len(route_coords) < 2:
        return []

    # Find closest point on route to user
    min_dist = float('inf')
    closest_idx = 0
    for i, coord in enumerate(route_coords):
        d = _haversine(lat, lng, coord[1], coord[0])
        if d < min_dist:
            min_dist = d
            closest_idx = i

    # Direction vector from closest point forward
    if closest_idx < len(route_coords) - 1:
        dir_lat = route_coords[closest_idx + 1][1] - route_coords[closest_idx][1]
        dir_lng = route_coords[closest_idx + 1][0] - route_coords[closest_idx][0]
    else:
        dir_lat = route_coords[closest_idx][1] - route_coords[max(0, closest_idx - 1)][1]
        dir_lng = route_coords[closest_idx][0] - route_coords[max(0, closest_idx - 1)][0]

    segments = []
    accum = 0.0
    prev_lat, prev_lng = route_coords[closest_idx][1], route_coords[closest_idx][0]

    for i in range(closest_idx + 1, len(route_coords)):
        c_lat, c_lng = route_coords[i][1], route_coords[i][0]
        seg_dist = _haversine(prev_lat, prev_lng, c_lat, c_lng)
        accum += seg_dist

        if accum > lookahead_m:
            break

        # Direction filter: check dot product
        vec_lat = c_lat - lat
        vec_lng = c_lng - lng
        dot = vec_lat * dir_lat + vec_lng * dir_lng
        if dot < 0:
            prev_lat, prev_lng = c_lat, c_lng
            continue

        dist_from_user = _haversine(lat, lng, c_lat, c_lng)
        segments.append({
            "lat": c_lat, "lng": c_lng,
            "distance_from_user": round(dist_from_user, 1),
            "idx": i,
        })
        prev_lat, prev_lng = c_lat, c_lng

    return segments


async def evaluate_predictive_risk(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    route_coords: list | None = None,
    speed_mps: float = 1.5,
    timestamp: datetime | None = None,
) -> dict:
    """Main entry: evaluate upcoming risk and generate predictive alert."""
    now = timestamp or datetime.now(timezone.utc)
    mode = _detect_mode(speed_mps)
    lookahead = LOOKAHEAD[mode]
    hour = now.hour
    tod_mult, tod_label = _get_tod_multiplier(hour)

    # If no route provided, create a simple forward projection
    if not route_coords or len(route_coords) < 2:
        route_coords = _project_forward(lat, lng, speed_mps, lookahead)

    # Get segments ahead using cache
    route_key = f"{user_id}:{hash(str(route_coords[:5]))}"
    ahead = _segments_ahead(lat, lng, route_coords, lookahead)
    if not ahead:
        return _no_alert_response(user_id, lat, lng, mode, lookahead, tod_label)

    # Fetch zones for risk scoring
    zones = await _fetch_zones(session)

    # Score each segment ahead
    danger_segments = []
    max_risk = 0.0

    for seg in ahead:
        # Check cached forecast first (avoids recomputation)
        from app.services.risk_forecast_engine import get_point_forecast_cached
        cached_fc = get_point_forecast_cached(seg["lat"], seg["lng"])
        if cached_fc and cached_fc.get("risk_score") is not None:
            adjusted_risk = round(min(10.0, cached_fc["risk_score"] * tod_mult), 2)
            base_risk = cached_fc["risk_score"]
        else:
            crime_density = _compute_crime_density(seg["lat"], seg["lng"], zones)
            base_risk = round(min(10.0, crime_density), 2)
            adjusted_risk = round(min(10.0, base_risk * tod_mult), 2)

        risk_level = _classify_risk(adjusted_risk)
        zone_id = generate_zone_id(seg["lat"], seg["lng"])

        seg["risk"] = adjusted_risk
        seg["base_risk"] = base_risk
        seg["risk_level"] = risk_level
        seg["zone_id"] = zone_id

        if risk_level in ("HIGH", "CRITICAL"):
            danger_segments.append(seg)
        if adjusted_risk > max_risk:
            max_risk = adjusted_risk

    # No danger ahead
    if not danger_segments:
        return _no_alert_response(user_id, lat, lng, mode, lookahead, tod_label)

    # Check cooldown for the nearest danger zone
    nearest_danger = min(danger_segments, key=lambda s: s["distance_from_user"])
    if _is_cooled_down(user_id, nearest_danger["zone_id"]):
        return {
            "alert": False,
            "reason": "cooldown_active",
            "user_id": user_id,
            "location": {"lat": lat, "lng": lng},
            "mode": mode, "lookahead_m": lookahead,
            "time_period": tod_label,
            "nearest_danger": {
                "zone_id": nearest_danger["zone_id"],
                "distance": nearest_danger["distance_from_user"],
                "risk_score": nearest_danger["risk"],
                "risk_level": nearest_danger["risk_level"],
            },
            "cooldown_remaining_s": round(COOLDOWN_S - (_time.time() - _cooldown.get(f"{user_id}:{nearest_danger['zone_id']}", 0))),
        }

    # Alert!
    _mark_alerted(user_id, nearest_danger["zone_id"])
    severity = _classify_alert_severity(nearest_danger["risk_level"], len(danger_segments))

    # Build alert message
    dist = round(nearest_danger["distance_from_user"])
    if nearest_danger["risk_level"] == "CRITICAL":
        message = f"Dangerous zone ahead in {dist}m"
        recommendation = "Recommended safer route available"
    elif nearest_danger["risk_level"] == "HIGH":
        message = f"High-risk area ahead in {dist}m"
        recommendation = "Stay alert or consider alternative route"
    else:
        message = f"Caution: elevated risk ahead in {dist}m"
        recommendation = "Stay alert"

    if len(danger_segments) > 1:
        message += f" (route passes through {len(danger_segments)} risk zones)"

    return {
        "alert": True,
        "severity": severity,
        "message": message,
        "recommendation": recommendation,
        "distance_to_risk": dist,
        "risk_score": nearest_danger["risk"],
        "risk_level": nearest_danger["risk_level"],
        "zone_id": nearest_danger["zone_id"],
        "danger_zones_ahead": len(danger_segments),
        "alternative_route_available": True,
        "user_id": user_id,
        "location": {"lat": lat, "lng": lng},
        "mode": mode,
        "lookahead_m": lookahead,
        "time_period": tod_label,
        "danger_segments": [{
            "lat": s["lat"], "lng": s["lng"],
            "distance": s["distance_from_user"],
            "risk": s["risk"], "risk_level": s["risk_level"],
            "zone_id": s["zone_id"],
        } for s in danger_segments],
        "checked_at": now.isoformat(),
    }


def _classify_alert_severity(risk_level: str, danger_count: int) -> str:
    if risk_level == "CRITICAL":
        return "CRITICAL"
    if risk_level == "HIGH" and danger_count >= 2:
        return "CRITICAL"
    if risk_level == "HIGH":
        return "HIGH"
    return "LOW"


def _no_alert_response(user_id, lat, lng, mode, lookahead, tod_label):
    return {
        "alert": False,
        "reason": "safe_ahead",
        "user_id": user_id,
        "location": {"lat": lat, "lng": lng},
        "mode": mode, "lookahead_m": lookahead,
        "time_period": tod_label,
        "message": "Route ahead appears safe",
    }


def _project_forward(lat: float, lng: float, speed_mps: float, distance_m: float) -> list:
    """Create a simple straight-line forward projection when no route is available."""
    # Default heading: northeast
    bearing = math.radians(45)
    steps = max(5, int(distance_m / 50))
    coords = []
    R = 6371000
    for i in range(steps + 1):
        d = (distance_m / steps) * i
        lat_r = math.radians(lat)
        lng_r = math.radians(lng)
        new_lat = math.asin(
            math.sin(lat_r) * math.cos(d / R) +
            math.cos(lat_r) * math.sin(d / R) * math.cos(bearing)
        )
        new_lng = lng_r + math.atan2(
            math.sin(bearing) * math.sin(d / R) * math.cos(lat_r),
            math.cos(d / R) - math.sin(lat_r) * math.sin(new_lat)
        )
        coords.append([math.degrees(new_lng), math.degrees(new_lat)])
    return coords
