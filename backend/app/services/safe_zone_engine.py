# Safe Zone Detection Engine
# Consumer-facing safety module — detects whether a user is in a
# SAFE / LOW / HIGH / CRITICAL zone based on composite risk scoring.
# Foundation for Night Guardian, Route Safety, Pickup Safety, Guardian Alerts.

import logging
import math
import time as _time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Scoring Weights ──
W_CRIME_DENSITY = 0.50
W_RECENT_INCIDENTS = 0.30
W_TIME_OF_DAY = 0.10
W_ENVIRONMENT = 0.10

# ── Time-of-Day Multipliers ──
TOD_DAY = 1.0        # 6AM - 8PM
TOD_NIGHT = 1.3       # 8PM - 12AM
TOD_LATE_NIGHT = 1.6  # 12AM - 5AM

# ── Risk Classification ──
RISK_LEVELS = [
    (0, 2, "SAFE"),
    (2, 4, "LOW"),
    (4, 7, "HIGH"),
    (7, 10, "CRITICAL"),
]

RECOMMENDATIONS = {
    "SAFE": {"action": "continue_journey", "message": "Area appears safe. Continue journey."},
    "LOW": {"action": "stay_alert", "message": "Moderate safety risk detected. Stay alert."},
    "HIGH": {"action": "alternative_route", "message": "High risk area. Alternative route available."},
    "CRITICAL": {"action": "leave_immediately", "message": "Dangerous zone detected. Recommend leaving immediately."},
}

# ── In-Memory Cache ──
_zone_cache = {}       # zone_id -> {score, level, data, expires_at}
_user_state_cache = {} # user_id -> {last_zone_id, last_risk_level, timestamp}
CACHE_TTL_S = 300      # 5 minutes
GRID_CELL_SIZE_M = 250


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def generate_zone_id(lat: float, lng: float) -> str:
    """Deterministic zone ID from coordinates."""
    lat_r = round(lat, 3)
    lng_r = round(lng, 3)
    return f"Z_{str(lat_r).replace('.','_')}_{str(lng_r).replace('.','_')}"


def _get_tod_multiplier(hour: int) -> tuple[float, str]:
    if 6 <= hour < 20:
        return TOD_DAY, "day"
    elif 20 <= hour < 24:
        return TOD_NIGHT, "night"
    else:  # 0-5
        return TOD_LATE_NIGHT, "late_night"


def _classify_risk(score: float) -> str:
    for low, high, label in RISK_LEVELS:
        if low <= score < high:
            return label
    return "CRITICAL" if score >= 7 else "SAFE"


def _generate_zone_name(lat: float, lng: float, zones: list[dict]) -> str:
    """Find the nearest named zone or generate from coordinates."""
    nearest = None
    min_dist = float('inf')
    for z in zones:
        d = _haversine(lat, lng, z["lat"], z["lng"])
        if d < min_dist:
            min_dist = d
            nearest = z
    if nearest and min_dist < 1000:
        return nearest.get("zone_name", f"Zone {generate_zone_id(lat, lng)}")
    return f"Grid Zone {round(lat, 3)}, {round(lng, 3)}"


def _cache_get(zone_id: str) -> dict | None:
    entry = _zone_cache.get(zone_id)
    if entry and entry["expires_at"] > _time.time():
        return entry["data"]
    return None


def _cache_set(zone_id: str, data: dict):
    _zone_cache[zone_id] = {"data": data, "expires_at": _time.time() + CACHE_TTL_S}


def _user_state_get(user_id: str) -> dict | None:
    return _user_state_cache.get(user_id)


def _user_state_set(user_id: str, zone_id: str, risk_level: str):
    _user_state_cache[user_id] = {
        "last_zone_id": zone_id,
        "last_risk_level": risk_level,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _detect_transition(user_id: str, new_zone_id: str, new_risk_level: str) -> dict:
    """Detect if user has transitioned to a different/riskier zone."""
    prev = _user_state_get(user_id)
    if not prev:
        return {"transitioned": True, "type": "new_entry", "previous_zone": None, "previous_risk": None}

    if prev["last_zone_id"] == new_zone_id and prev["last_risk_level"] == new_risk_level:
        return {"transitioned": False, "type": "same_zone", "previous_zone": prev["last_zone_id"], "previous_risk": prev["last_risk_level"]}

    risk_order = {"SAFE": 0, "LOW": 1, "HIGH": 2, "CRITICAL": 3}
    prev_rank = risk_order.get(prev["last_risk_level"], 0)
    new_rank = risk_order.get(new_risk_level, 0)

    if new_rank > prev_rank:
        t_type = "escalation"
    elif new_rank < prev_rank:
        t_type = "de_escalation"
    else:
        t_type = "zone_change"

    return {
        "transitioned": True,
        "type": t_type,
        "previous_zone": prev["last_zone_id"],
        "previous_risk": prev["last_risk_level"],
    }


async def _fetch_zones(session: AsyncSession) -> list[dict]:
    import json
    rows = (await session.execute(text("""
        SELECT id, zone_name, latitude, longitude, radius_meters,
               risk_score, risk_level, incident_count, factors
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
    """))).fetchall()

    return [{
        "zone_id": str(z.id),
        "zone_name": z.zone_name,
        "lat": float(z.latitude),
        "lng": float(z.longitude),
        "radius_meters": float(z.radius_meters),
        "risk_score": float(z.risk_score),
        "risk_level": z.risk_level,
        "incident_count": z.incident_count,
        "factors": json.loads(z.factors) if isinstance(z.factors, str) else (z.factors or []),
    } for z in rows]


async def _fetch_nearby_incidents(session: AsyncSession, lat: float, lng: float, radius_m: float = 500, days: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await session.execute(text("""
        SELECT li.latitude, li.longitude, li.severity, li.incident_type,
               li.created_at, EXTRACT(HOUR FROM li.created_at) as hour
        FROM location_incidents li
        JOIN incidents i ON li.incident_id = i.id
        WHERE li.created_at >= :cutoff
          AND li.latitude IS NOT NULL AND li.longitude IS NOT NULL
          AND ABS(li.latitude - :lat) < 0.006
          AND ABS(li.longitude - :lng) < 0.006
        ORDER BY li.created_at DESC
        LIMIT 100
    """), {"cutoff": cutoff, "lat": lat, "lng": lng})).fetchall()

    return [r for r in [
        {"lat": float(r.latitude), "lng": float(r.longitude), "severity": r.severity,
         "incident_type": r.incident_type, "created_at": r.created_at, "hour": int(r.hour)}
        for r in rows
    ] if _haversine(lat, lng, r["lat"], r["lng"]) <= radius_m]


def _compute_crime_density(lat: float, lng: float, zones: list[dict]) -> float:
    """Crime density score (0-10) based on nearby hotspot zones."""
    influence = 0.0
    for z in zones:
        dist = _haversine(lat, lng, z["lat"], z["lng"])
        radius = z.get("radius_meters", 500) * 1.5
        if dist <= radius:
            proximity = 1.0 - (dist / radius)
            influence += z["risk_score"] * proximity
    return round(min(10.0, influence), 2)


def _compute_incident_score(incidents: list[dict]) -> float:
    """Recent incident score (0-10) based on count and severity."""
    if not incidents:
        return 0.0
    sev_weights = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
    total = sum(sev_weights.get(i["severity"], 1.0) for i in incidents)
    return round(min(10.0, total / 3.0), 2)


def _compute_time_score(hour: int) -> float:
    """Time-of-day risk score (0-10)."""
    multiplier, _ = _get_tod_multiplier(hour)
    base = 3.0 if multiplier == TOD_DAY else 6.0 if multiplier == TOD_NIGHT else 8.0
    return round(base, 2)


def _compute_environment_score(hour: int) -> float:
    """Environment risk score (0-10) — visibility, lighting proxy."""
    if 6 <= hour < 18:
        return 1.5  # Daylight
    elif 18 <= hour < 21:
        return 4.0  # Dusk/evening
    else:
        return 7.0  # Dark


async def check_zone(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    timestamp: datetime | None = None,
) -> dict:
    """
    Main entry point: check the safety zone for a user's current location.
    Returns zone status, risk score, recommendations, and transition alerts.
    """
    now = timestamp or datetime.now(timezone.utc)
    hour = now.hour

    zone_id = generate_zone_id(lat, lng)

    # Check cache first
    cached = _cache_get(zone_id)
    if cached:
        # Still apply time multiplier and transition detection
        tod_mult, tod_label = _get_tod_multiplier(hour)
        final_score = round(min(10.0, cached["base_score"] * tod_mult), 2)
        risk_level = _classify_risk(final_score)
        transition = _detect_transition(user_id, zone_id, risk_level)
        _user_state_set(user_id, zone_id, risk_level)
        rec = RECOMMENDATIONS.get(risk_level, RECOMMENDATIONS["SAFE"])

        return {
            "zone_id": zone_id,
            "zone_name": cached["zone_name"],
            "zone_status": f"{risk_level}_RISK" if risk_level != "SAFE" else "SAFE",
            "risk_level": risk_level,
            "risk_score": final_score,
            "base_score": cached["base_score"],
            "time_multiplier": tod_mult,
            "time_period": tod_label,
            "recommendation": rec["action"],
            "recommendation_message": rec["message"],
            "safe_route_available": risk_level in ("HIGH", "CRITICAL"),
            "incident_density": cached["incident_density"],
            "score_breakdown": {**cached["score_breakdown"], "time_of_day": _compute_time_score(hour)},
            "transition": transition,
            "alert_triggered": transition["transitioned"] and transition["type"] in ("escalation", "new_entry"),
            "cached": True,
            "checked_at": now.isoformat(),
        }

    # Cache miss — compute from scratch
    zones = await _fetch_zones(session)
    incidents = await _fetch_nearby_incidents(session, lat, lng)
    zone_name = _generate_zone_name(lat, lng, zones)

    # Score components
    crime_density = _compute_crime_density(lat, lng, zones)
    incident_score = _compute_incident_score(incidents)
    time_score = _compute_time_score(hour)
    env_score = _compute_environment_score(hour)

    # Base composite (before time multiplier)
    base_score = round(
        W_CRIME_DENSITY * crime_density +
        W_RECENT_INCIDENTS * incident_score +
        W_TIME_OF_DAY * time_score +
        W_ENVIRONMENT * env_score, 2
    )

    # Apply time-of-day multiplier
    tod_mult, tod_label = _get_tod_multiplier(hour)
    final_score = round(min(10.0, base_score * tod_mult), 2)
    risk_level = _classify_risk(final_score)

    # Cache the base data (without time-sensitive parts)
    _cache_set(zone_id, {
        "base_score": base_score,
        "zone_name": zone_name,
        "incident_density": len(incidents),
        "score_breakdown": {
            "crime_density": crime_density,
            "recent_incidents": incident_score,
            "environment": env_score,
        },
    })

    # Transition detection
    transition = _detect_transition(user_id, zone_id, risk_level)
    _user_state_set(user_id, zone_id, risk_level)

    rec = RECOMMENDATIONS.get(risk_level, RECOMMENDATIONS["SAFE"])

    return {
        "zone_id": zone_id,
        "zone_name": zone_name,
        "zone_status": f"{risk_level}_RISK" if risk_level != "SAFE" else "SAFE",
        "risk_level": risk_level,
        "risk_score": final_score,
        "base_score": base_score,
        "time_multiplier": tod_mult,
        "time_period": tod_label,
        "recommendation": rec["action"],
        "recommendation_message": rec["message"],
        "safe_route_available": risk_level in ("HIGH", "CRITICAL"),
        "incident_density": len(incidents),
        "score_breakdown": {
            "crime_density": crime_density,
            "recent_incidents": incident_score,
            "time_of_day": time_score,
            "environment": env_score,
        },
        "transition": transition,
        "alert_triggered": transition["transitioned"] and transition["type"] in ("escalation", "new_entry"),
        "cached": False,
        "checked_at": now.isoformat(),
    }


async def get_zone_map(session: AsyncSession) -> dict:
    """Return all active risk zones for map rendering."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    tod_mult, tod_label = _get_tod_multiplier(hour)

    zones = await _fetch_zones(session)

    map_zones = []
    for z in zones:
        zone_id = generate_zone_id(z["lat"], z["lng"])
        adjusted = round(min(10.0, z["risk_score"] * tod_mult), 2)
        risk_level = _classify_risk(adjusted)
        map_zones.append({
            "zone_id": zone_id,
            "zone_name": z["zone_name"],
            "lat": z["lat"],
            "lng": z["lng"],
            "radius_m": z["radius_meters"],
            "risk_score": adjusted,
            "base_risk_score": z["risk_score"],
            "risk_level": risk_level,
            "incident_count": z["incident_count"],
        })

    map_zones.sort(key=lambda z: z["risk_score"], reverse=True)

    stats = defaultdict(int)
    for z in map_zones:
        stats[z["risk_level"]] += 1

    return {
        "zones": map_zones,
        "total_zones": len(map_zones),
        "time_multiplier": tod_mult,
        "time_period": tod_label,
        "stats": {
            "CRITICAL": stats.get("CRITICAL", 0),
            "HIGH": stats.get("HIGH", 0),
            "LOW": stats.get("LOW", 0),
            "SAFE": stats.get("SAFE", 0),
        },
        "generated_at": now.isoformat(),
    }
