# Automated Patrol Routing AI Engine
# Generates optimal patrol routes for operators based on a composite score
# derived from forecast, trend, activity, learning, and temporal factors.
# Uses nearest-neighbor heuristic TSP for route optimization.

import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Composite Score Weights ──
W_FORECAST = 0.30   # Predictive risk forecast (48h)
W_TREND = 0.25      # Hotspot trend direction
W_ACTIVITY = 0.20   # Human activity risk
W_LEARNING = 0.15   # Base adaptive risk score
W_TEMPORAL = 0.10   # Time-of-day urgency

# ── Heatmap Boost Config ──
HEATMAP_BOOST_CRITICAL = 1.25  # 25% boost for zones in critical heatmap cells
HEATMAP_BOOST_HIGH = 1.12      # 12% boost for zones in high heatmap cells
HEATMAP_BOOST_MODERATE = 1.0   # No boost
HEATMAP_BOOST_SAFE = 0.9       # 10% reduction for safe areas

# ── Shift Definitions ──
SHIFTS = {
    "morning":   {"start": 6,  "end": 14, "label": "Morning (06:00-14:00)"},
    "afternoon": {"start": 14, "end": 22, "label": "Afternoon (14:00-22:00)"},
    "night":     {"start": 22, "end": 6,  "label": "Night (22:00-06:00)"},
}

# Temporal urgency multipliers by time-of-day bucket
TEMPORAL_URGENCY = {
    "night": 1.4,
    "evening": 1.2,
    "morning": 1.0,
    "afternoon": 0.9,
}


def _haversine(lat1, lng1, lat2, lng2):
    """Distance in meters between two GPS points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_tod_bucket(hour: int) -> str:
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 22:
        return "evening"
    return "night"


def _temporal_urgency_score(zone: dict, shift: str, now: datetime) -> float:
    """Compute temporal urgency factor based on zone's dominant time and current shift."""
    dominant_tod = zone.get("dominant_tod", "afternoon")
    current_hour = now.hour
    current_tod = _get_tod_bucket(current_hour)

    # Base urgency from time of day
    base = TEMPORAL_URGENCY.get(current_tod, 1.0)

    # Bonus if zone's dominant incident time matches current shift
    shift_hours = SHIFTS.get(shift, SHIFTS["morning"])
    start, end = shift_hours["start"], shift_hours["end"]

    # Check if dominant_tod falls in current shift
    tod_hour_map = {"morning": 9, "afternoon": 15, "evening": 20, "night": 2}
    dom_hour = tod_hour_map.get(dominant_tod, 12)

    if start < end:
        in_shift = start <= dom_hour < end
    else:  # night shift wraps
        in_shift = dom_hour >= start or dom_hour < end

    shift_bonus = 1.3 if in_shift else 0.8

    # Night ratio bonus (zones with high night incidents get more urgent at night)
    night_ratio = zone.get("night_ratio", 0)
    night_bonus = 1.0 + (night_ratio * 0.3) if current_tod == "night" else 1.0

    return round(min(10.0, base * shift_bonus * night_bonus * 5.0), 2)


def _compute_composite_score(
    forecast_score: float,
    trend_score: float,
    activity_score: float,
    learning_score: float,
    temporal_score: float,
) -> float:
    """
    Composite Patrol Priority Score = 
        W_FORECAST * forecast_normalized +
        W_TREND * trend_normalized +
        W_ACTIVITY * activity_normalized +
        W_LEARNING * learning_normalized +
        W_TEMPORAL * temporal_normalized
    
    All inputs should be on 0-10 scale. Output is 0-10.
    """
    composite = (
        W_FORECAST * forecast_score +
        W_TREND * trend_score +
        W_ACTIVITY * activity_score +
        W_LEARNING * learning_score +
        W_TEMPORAL * temporal_score
    )
    return round(max(0.0, min(10.0, composite)), 2)


def _normalize_trend_to_score(trend_score: float, trend_status: str) -> float:
    """Convert trend score (-1 to 1 range) + status to 0-10 patrol urgency."""
    status_base = {
        "growing": 7.0,
        "emerging": 5.5,
        "stable": 3.0,
        "declining": 1.5,
        "dormant": 0.5,
    }
    base = status_base.get(trend_status, 3.0)
    # Add trend_score influence (it ranges roughly -1 to 1)
    adjustment = trend_score * 2.0
    return round(max(0.0, min(10.0, base + adjustment)), 2)


def _tsp_nearest_neighbor(zones: list[dict], start_lat: float, start_lng: float) -> list[dict]:
    """
    Solve TSP using nearest-neighbor heuristic.
    Returns zones ordered for optimal patrol route starting from given position.
    """
    if len(zones) <= 1:
        return zones

    remaining = list(zones)
    ordered = []
    current_lat, current_lng = start_lat, start_lng

    while remaining:
        # Find nearest unvisited zone
        best_idx = 0
        best_dist = float('inf')
        for i, z in enumerate(remaining):
            d = _haversine(current_lat, current_lng, z["lat"], z["lng"])
            if d < best_dist:
                best_dist = d
                best_idx = i

        next_zone = remaining.pop(best_idx)
        next_zone["distance_from_prev_m"] = round(best_dist)
        ordered.append(next_zone)
        current_lat, current_lng = next_zone["lat"], next_zone["lng"]

    return ordered


def _estimate_patrol_time(ordered_zones: list[dict], dwell_minutes: int = 10) -> dict:
    """Estimate total patrol time: travel + dwell at each zone."""
    total_distance_m = sum(z.get("distance_from_prev_m", 0) for z in ordered_zones)
    # Assume average patrol speed: 30 km/h in urban areas
    travel_minutes = (total_distance_m / 1000.0) / 30.0 * 60.0
    dwell_total = len(ordered_zones) * dwell_minutes
    total_minutes = travel_minutes + dwell_total

    return {
        "total_distance_km": round(total_distance_m / 1000.0, 2),
        "travel_minutes": round(travel_minutes),
        "dwell_minutes_per_zone": dwell_minutes,
        "total_dwell_minutes": dwell_total,
        "total_estimated_minutes": round(total_minutes),
        "total_zones": len(ordered_zones),
    }


async def _fetch_zone_data(session: AsyncSession) -> list[dict]:
    """Fetch all learned hotspot zones with their metadata."""
    rows = (await session.execute(text("""
        SELECT id, zone_name, latitude, longitude, radius_meters,
               risk_score, risk_level, incident_count, factors, last_updated
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
        ORDER BY risk_score DESC
    """))).fetchall()

    zones = []
    for z in rows:
        import json
        fac = z.factors
        if isinstance(fac, str):
            fac = json.loads(fac)

        # Extract trend metadata from factors if present
        trend_meta = {}
        display_factors = []
        for f in (fac or []):
            if isinstance(f, dict) and "trend_status" in f:
                trend_meta = f
            elif isinstance(f, str):
                display_factors.append(f)

        zones.append({
            "zone_id": str(z.id),
            "zone_name": z.zone_name,
            "lat": float(z.latitude),
            "lng": float(z.longitude),
            "radius_meters": float(z.radius_meters),
            "risk_score": float(z.risk_score),
            "risk_level": z.risk_level,
            "incident_count": z.incident_count,
            "factors": display_factors,
            "trend_meta": trend_meta,
            "last_updated": z.last_updated.isoformat() if z.last_updated else None,
        })
    return zones


async def _fetch_recent_incidents(session: AsyncSession, days: int = 7) -> list[dict]:
    """Fetch recent incidents for temporal analysis."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await session.execute(text("""
        SELECT li.latitude, li.longitude, li.severity, li.incident_type,
               li.created_at, EXTRACT(HOUR FROM li.created_at) as hour
        FROM location_incidents li
        JOIN incidents i ON li.incident_id = i.id
        WHERE li.created_at >= :cutoff
          AND li.latitude IS NOT NULL AND li.longitude IS NOT NULL
        ORDER BY li.created_at DESC
    """), {"cutoff": cutoff})).fetchall()

    return [{
        "lat": float(r.latitude),
        "lng": float(r.longitude),
        "severity": r.severity,
        "incident_type": r.incident_type,
        "created_at": r.created_at,
        "hour": int(r.hour),
    } for r in rows]


def _get_zone_dominant_tod(zone: dict, incidents: list[dict]) -> tuple[str, float]:
    """Get dominant time-of-day and night ratio for a zone."""
    radius = zone.get("radius_meters", 500)
    nearby = [i for i in incidents
              if _haversine(zone["lat"], zone["lng"], i["lat"], i["lng"]) <= radius]

    if not nearby:
        return "afternoon", 0.0

    tod_counts = defaultdict(int)
    for inc in nearby:
        tod = _get_tod_bucket(inc["hour"])
        tod_counts[tod] += 1

    dominant = max(tod_counts, key=tod_counts.get) if tod_counts else "afternoon"
    total = sum(tod_counts.values())
    night_ratio = (tod_counts.get("night", 0) + tod_counts.get("evening", 0)) / max(total, 1)
    return dominant, round(night_ratio, 2)


# Activity signal weights for in-memory scoring
ACTIVITY_SIGNAL_WEIGHT = {
    "SOS": 3.0, "fall_detected": 2.5, "route_deviation": 1.5,
    "geofence_breach": 1.5, "device_offline": 1.0, "low_battery": 0.5,
}

def _compute_zone_activity_score(zone: dict, incidents: list[dict]) -> float:
    """
    Compute activity risk score (0-10) for a zone from pre-fetched incident data.
    Pure in-memory — no database calls.
    Factors: incident density, type severity, temporal concentration.
    """
    radius = zone.get("radius_meters", 500) * 2  # wider search for activity
    nearby = [i for i in incidents
              if _haversine(zone["lat"], zone["lng"], i["lat"], i["lng"]) <= radius]

    if not nearby:
        return 0.0

    # Incident density score (more incidents = higher activity risk)
    density = min(1.0, len(nearby) / 15.0)

    # Type-weighted severity
    type_weight_sum = sum(
        ACTIVITY_SIGNAL_WEIGHT.get(i["incident_type"], 1.0) for i in nearby
    )
    severity_score = min(1.0, type_weight_sum / 20.0)

    # Temporal concentration (clustered times = predictable risk)
    hour_counts = defaultdict(int)
    for i in nearby:
        hour_counts[i["hour"]] += 1
    if hour_counts:
        max_hour = max(hour_counts.values())
        concentration = max_hour / max(len(nearby), 1)
    else:
        concentration = 0.0

    # Composite activity score (0-10)
    raw = density * 4.0 + severity_score * 4.0 + concentration * 2.0
    return round(max(0.0, min(10.0, raw)), 2)



def _build_route_geometry(ordered_zones: list[dict], start_lat: float, start_lng: float) -> dict:
    """Build route geometry for map visualization — ordered lat/lng path + segments."""
    waypoints = [{"lat": start_lat, "lng": start_lng, "type": "start", "label": "Start"}]

    for z in ordered_zones:
        waypoints.append({
            "lat": z["lat"],
            "lng": z["lng"],
            "type": "stop",
            "label": str(z["stop_number"]),
            "zone_id": z["zone_id"],
            "priority": z.get("patrol_priority", "medium"),
        })

    # Build segments (pairs of consecutive waypoints)
    segments = []
    for i in range(len(waypoints) - 1):
        segments.append({
            "from": [waypoints[i]["lat"], waypoints[i]["lng"]],
            "to": [waypoints[i + 1]["lat"], waypoints[i + 1]["lng"]],
            "segment_index": i,
        })

    # Full polyline path
    polyline = [[w["lat"], w["lng"]] for w in waypoints]

    return {
        "waypoints": waypoints,
        "segments": segments,
        "polyline": polyline,
        "total_waypoints": len(waypoints),
    }



def _get_heatmap_boost(zone_lat: float, zone_lng: float, heatmap_cells: list[dict]) -> dict:
    """Look up the nearest heatmap cell for a zone and return boost info."""
    if not heatmap_cells:
        return {"heatmap_score": 0, "heatmap_risk": "none", "heatmap_boost": 1.0}

    nearest = None
    min_dist = float('inf')
    for cell in heatmap_cells:
        d = abs(cell["lat"] - zone_lat) + abs(cell["lng"] - zone_lng)  # Manhattan for speed
        if d < min_dist:
            min_dist = d
            nearest = cell

    if not nearest or min_dist > 0.005:  # ~500m threshold
        return {"heatmap_score": 0, "heatmap_risk": "none", "heatmap_boost": 1.0}

    risk = nearest.get("risk_level", "safe")
    boost_map = {
        "critical": HEATMAP_BOOST_CRITICAL,
        "high": HEATMAP_BOOST_HIGH,
        "moderate": HEATMAP_BOOST_MODERATE,
        "safe": HEATMAP_BOOST_SAFE,
    }
    return {
        "heatmap_score": nearest.get("composite_score", 0),
        "heatmap_risk": risk,
        "heatmap_boost": boost_map.get(risk, 1.0),
        "heatmap_cell_id": nearest.get("grid_id"),
        "heatmap_signals": {
            "forecast": nearest.get("forecast", 0),
            "hotspot": nearest.get("hotspot", 0),
            "trend": nearest.get("trend", 0),
            "activity": nearest.get("activity", 0),
            "patrol": nearest.get("patrol", 0),
        },
    }



async def generate_patrol_route(
    session: AsyncSession,
    shift: str = "morning",
    start_lat: float = None,
    start_lng: float = None,
    max_zones: int = 15,
    dwell_minutes: int = 10,
    use_heatmap: bool = False,
) -> dict:
    """
    Generate an optimized patrol route.
    
    1. Fetch all hotspot zones
    2. Compute composite priority score for each
    3. (Optional) Apply heatmap boost from city heatmap cells
    4. Select top-N zones by priority
    5. Optimize order using nearest-neighbor TSP
    6. Return ordered route with timing estimates
    """
    now = datetime.now(timezone.utc)
    shift_info = SHIFTS.get(shift, SHIFTS["morning"])

    # Fetch zone data
    zones = await _fetch_zone_data(session)
    if not zones:
        return {
            "route": [],
            "summary": _estimate_patrol_time([], dwell_minutes),
            "shift": shift,
            "shift_label": shift_info["label"],
            "generated_at": now.isoformat(),
            "priority_breakdown": {},
            "message": "No hotspot zones available for patrol routing.",
        }

    # Fetch recent incidents for temporal analysis
    incidents = await _fetch_recent_incidents(session)

    # Import engines for scoring (batch-friendly — no per-zone DB calls)
    from app.services.risk_forecast_engine import _compute_zone_forecast, _fetch_all_incidents as fetch_forecast_incidents
    from app.services.hotspot_trend_engine import _compute_zone_trend, _fetch_all_incidents as fetch_trend_incidents

    # Batch fetch data for engines (2 total DB queries for forecast+trend)
    forecast_incidents = await fetch_forecast_incidents(session, timedelta(days=14))
    trend_incidents = await fetch_trend_incidents(session, timedelta(days=60))

    # Optionally fetch heatmap cells for boost scoring
    heatmap_cells = []
    heatmap_stats = None
    if use_heatmap:
        from app.services.city_heatmap_engine import generate_city_heatmap
        heatmap_data = await generate_city_heatmap(session)
        heatmap_cells = heatmap_data.get("cells", [])
        heatmap_stats = heatmap_data.get("stats")

    # Batch fetch activity risk data — lightweight in-memory computation
    # No additional DB queries needed

    scored_zones = []
    for zone in zones:
        # 1. Forecast score (predicted 48h risk, 0-10 scale)
        forecast_data = _compute_zone_forecast(zone, forecast_incidents, now)
        forecast_score = forecast_data.get("predicted_48h", zone["risk_score"])

        # 2. Trend score (convert trend to 0-10 urgency)
        trend_data = _compute_zone_trend(zone, trend_incidents, now)
        trend_status = trend_data.get("trend_status", "stable")
        raw_trend = trend_data.get("trend_score", 0)
        trend_urgency = _normalize_trend_to_score(raw_trend, trend_status)

        # 3. Activity risk score (computed in-memory from fetched incidents, no extra DB)
        activity_score = _compute_zone_activity_score(zone, incidents)

        # 4. Learning score (base risk from adaptive engine, already 0-10)
        learning_score = zone["risk_score"]

        # 5. Temporal urgency
        dominant_tod, night_ratio = _get_zone_dominant_tod(zone, incidents)
        zone["dominant_tod"] = dominant_tod
        zone["night_ratio"] = night_ratio
        temporal_score = _temporal_urgency_score(zone, shift, now)

        # Composite score
        composite = _compute_composite_score(
            forecast_score, trend_urgency, activity_score, learning_score, temporal_score
        )

        # Apply heatmap boost if enabled
        heatmap_info = _get_heatmap_boost(zone["lat"], zone["lng"], heatmap_cells) if use_heatmap else {
            "heatmap_score": 0, "heatmap_risk": "none", "heatmap_boost": 1.0,
        }
        boosted_composite = round(min(10.0, composite * heatmap_info["heatmap_boost"]), 2) if use_heatmap else composite

        scored_zones.append({
            **zone,
            "composite_score": boosted_composite,
            "base_composite_score": composite,
            "heatmap_enhanced": use_heatmap,
            "score_breakdown": {
                "forecast": round(forecast_score, 2),
                "forecast_weighted": round(W_FORECAST * forecast_score, 2),
                "trend": round(trend_urgency, 2),
                "trend_weighted": round(W_TREND * trend_urgency, 2),
                "trend_status": trend_status,
                "activity": round(activity_score, 2),
                "activity_weighted": round(W_ACTIVITY * activity_score, 2),
                "learning": round(learning_score, 2),
                "learning_weighted": round(W_LEARNING * learning_score, 2),
                "temporal": round(temporal_score, 2),
                "temporal_weighted": round(W_TEMPORAL * temporal_score, 2),
                "heatmap_score": round(heatmap_info["heatmap_score"], 2),
                "heatmap_risk": heatmap_info["heatmap_risk"],
                "heatmap_boost": heatmap_info["heatmap_boost"],
                "heatmap_cell_id": heatmap_info.get("heatmap_cell_id"),
            },
            "forecast_category": forecast_data.get("forecast_category", "stable"),
            "forecast_priority": forecast_data.get("forecast_priority", 3),
            "recommendation": forecast_data.get("recommendation", {}),
        })

    # Sort by composite score descending and take top N
    scored_zones.sort(key=lambda z: z["composite_score"], reverse=True)
    selected = scored_zones[:max_zones]

    # Classify patrol priority
    for z in selected:
        s = z["composite_score"]
        if s >= 7.0:
            z["patrol_priority"] = "critical"
        elif s >= 5.0:
            z["patrol_priority"] = "high"
        elif s >= 3.0:
            z["patrol_priority"] = "medium"
        else:
            z["patrol_priority"] = "low"

    # Determine start position (default: centroid of selected zones)
    if start_lat is None or start_lng is None:
        if selected:
            start_lat = sum(z["lat"] for z in selected) / len(selected)
            start_lng = sum(z["lng"] for z in selected) / len(selected)
        else:
            start_lat, start_lng = 0.0, 0.0

    # TSP optimization
    ordered = _tsp_nearest_neighbor(selected, start_lat, start_lng)

    # Add stop numbers
    for i, z in enumerate(ordered):
        z["stop_number"] = i + 1

    # Summary
    summary = _estimate_patrol_time(ordered, dwell_minutes)

    # Priority breakdown
    priority_counts = defaultdict(int)
    for z in ordered:
        priority_counts[z["patrol_priority"]] += 1

    # Score statistics
    scores = [z["composite_score"] for z in ordered]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0
    max_score = max(scores) if scores else 0
    min_score = min(scores) if scores else 0

    return {
        "route": ordered,
        "route_geometry": _build_route_geometry(ordered, start_lat, start_lng),
        "summary": {
            **summary,
            "avg_composite_score": avg_score,
            "max_composite_score": max_score,
            "min_composite_score": min_score,
        },
        "shift": shift,
        "shift_label": shift_info["label"],
        "start_position": {"lat": start_lat, "lng": start_lng},
        "generated_at": now.isoformat(),
        "priority_breakdown": dict(priority_counts),
        "total_zones_analyzed": len(zones),
        "zones_selected": len(ordered),
        "heatmap_enhanced": use_heatmap,
        "heatmap_stats": heatmap_stats if use_heatmap else None,
        "weights": {
            "forecast": W_FORECAST,
            "trend": W_TREND,
            "activity": W_ACTIVITY,
            "learning": W_LEARNING,
            "temporal": W_TEMPORAL,
        },
    }


async def get_patrol_summary(session: AsyncSession) -> dict:
    """Lightweight summary for Command Center integration."""
    now = datetime.now(timezone.utc)
    current_hour = now.hour

    # Determine current shift
    if 6 <= current_hour < 14:
        current_shift = "morning"
    elif 14 <= current_hour < 22:
        current_shift = "afternoon"
    else:
        current_shift = "night"

    zones = await _fetch_zone_data(session)
    total_zones = len(zones)

    # Quick priority assessment based on risk scores
    critical_zones = sum(1 for z in zones if z["risk_score"] >= 7.0)
    high_zones = sum(1 for z in zones if 5.0 <= z["risk_score"] < 7.0)

    return {
        "total_patrol_zones": total_zones,
        "critical_zones": critical_zones,
        "high_zones": high_zones,
        "current_shift": current_shift,
        "shift_label": SHIFTS[current_shift]["label"],
        "analyzed_at": now.isoformat(),
    }
