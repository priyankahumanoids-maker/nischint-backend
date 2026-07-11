# Human Activity Risk AI Engine
# Detects and scores human activity risks at locations based on:
# - Incident clustering patterns (crowd density proxy)
# - Time-of-day activity levels
# - Incident type distribution (SOS = crowd panic, falls = hazardous terrain)
# - Spatial density (incidents/km²)
# - Temporal acceleration (sudden activity spikes)

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Activity risk categories derived from incident patterns
ACTIVITY_CATEGORIES = {
    "crowd_density": {
        "description": "High concentration of incidents suggesting crowded area",
        "weight": 0.30,
    },
    "traffic_corridor": {
        "description": "Incidents along road/path indicating traffic risk",
        "weight": 0.20,
    },
    "temporal_spike": {
        "description": "Sudden increase in incidents at specific hours",
        "weight": 0.20,
    },
    "hazard_zone": {
        "description": "Fall-related incidents indicating physical hazards",
        "weight": 0.15,
    },
    "emergency_cluster": {
        "description": "SOS/critical incidents indicating dangerous area",
        "weight": 0.15,
    },
}

# Incident type → activity signal mapping
INCIDENT_ACTIVITY_MAP = {
    "sos_alert": {"crowd_density": 0.6, "emergency_cluster": 1.0, "traffic_corridor": 0.3},
    "fall_detected": {"hazard_zone": 1.0, "crowd_density": 0.3, "traffic_corridor": 0.2},
    "fall_alert": {"hazard_zone": 1.0, "crowd_density": 0.3, "traffic_corridor": 0.2},
    "device_offline": {"crowd_density": 0.2, "traffic_corridor": 0.1},
    "battery_critical": {"crowd_density": 0.1},
    "geofence_breach": {"traffic_corridor": 0.5, "crowd_density": 0.4},
}

# Hour-of-day activity level multiplier (0-1)
HOUR_ACTIVITY = {
    0: 0.1, 1: 0.05, 2: 0.05, 3: 0.05, 4: 0.1, 5: 0.2,
    6: 0.4, 7: 0.7, 8: 0.9, 9: 1.0, 10: 0.9, 11: 0.85,
    12: 0.8, 13: 0.75, 14: 0.7, 15: 0.75, 16: 0.8, 17: 0.9,
    18: 1.0, 19: 0.9, 20: 0.7, 21: 0.5, 22: 0.3, 23: 0.2,
}


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _get_nearby_incidents(session: AsyncSession, lat: float, lng: float,
                                 radius_m: float, lookback_days: int) -> list[dict]:
    """Fetch incidents within radius using PostGIS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = (await session.execute(text("""
        SELECT li.id, li.latitude, li.longitude, li.incident_type, li.severity, li.created_at
        FROM location_incidents li
        JOIN incidents i ON li.incident_id = i.id
        WHERE ST_DWithin(
            li.geom::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :radius
        )
        AND li.created_at >= :cutoff
        AND li.latitude IS NOT NULL
        ORDER BY li.created_at DESC
    """), {"lat": lat, "lng": lng, "radius": radius_m, "cutoff": cutoff})).fetchall()

    return [{
        "id": r.id, "lat": float(r.latitude), "lng": float(r.longitude),
        "incident_type": r.incident_type, "severity": r.severity,
        "created_at": r.created_at, "hour": r.created_at.hour if r.created_at else 12,
    } for r in rows]


def _compute_crowd_density(incidents: list[dict], radius_m: float) -> float:
    """Estimate crowd density risk from incident spatial concentration."""
    if not incidents:
        return 0.0
    area_km2 = math.pi * (radius_m / 1000) ** 2
    density = len(incidents) / max(area_km2, 0.01)
    # Normalize: 0-5 incidents/km² = low, 5-20 = medium, 20+ = high
    return min(1.0, density / 25.0)


def _compute_temporal_spike(incidents: list[dict]) -> tuple[float, int]:
    """Detect sudden activity spikes in specific hours."""
    if len(incidents) < 3:
        return 0.0, -1
    hour_counts = defaultdict(int)
    for inc in incidents:
        hour_counts[inc["hour"]] += 1
    if not hour_counts:
        return 0.0, -1
    avg = len(incidents) / 24.0
    peak_hour = max(hour_counts, key=hour_counts.get)
    peak_count = hour_counts[peak_hour]
    spike_ratio = peak_count / max(avg, 0.5)
    # Spike if one hour has 3x the average
    return min(1.0, max(0.0, (spike_ratio - 1.0) / 3.0)), peak_hour


def _compute_type_signals(incidents: list[dict]) -> dict[str, float]:
    """Compute activity category scores from incident type distribution."""
    if not incidents:
        return {cat: 0.0 for cat in ACTIVITY_CATEGORIES}

    category_scores = defaultdict(float)
    for inc in incidents:
        itype = inc["incident_type"]
        signals = INCIDENT_ACTIVITY_MAP.get(itype, {})
        for cat, weight in signals.items():
            category_scores[cat] += weight

    # Normalize each category by incident count
    n = len(incidents)
    return {cat: min(1.0, category_scores.get(cat, 0.0) / max(n * 0.3, 1)) for cat in ACTIVITY_CATEGORIES}


def _compute_acceleration(incidents: list[dict]) -> float:
    """Measure if incident rate is accelerating (recent vs older)."""
    if len(incidents) < 4:
        return 0.0
    now = datetime.now(timezone.utc)
    mid = now - timedelta(days=15)
    recent = sum(1 for i in incidents if i["created_at"] >= mid)
    older = max(len(incidents) - recent, 1)
    ratio = recent / older
    return min(1.0, max(-1.0, (ratio - 1.0) / 2.0))


async def assess_location_activity_risk(
    session: AsyncSession, lat: float, lng: float
) -> dict:
    """Assess human activity risk at a specific location."""
    now = datetime.now(timezone.utc)
    hour = now.hour

    # Fetch incidents in 3 radii for multi-scale analysis
    nearby_500m = await _get_nearby_incidents(session, lat, lng, 500, 30)
    nearby_1km = await _get_nearby_incidents(session, lat, lng, 1000, 30)

    # Core signals
    crowd_density = _compute_crowd_density(nearby_500m, 500)
    spike_score, peak_hour = _compute_temporal_spike(nearby_1km)
    type_signals = _compute_type_signals(nearby_1km)
    acceleration = _compute_acceleration(nearby_1km)
    hour_activity = HOUR_ACTIVITY.get(hour, 0.5)

    # Weighted composite score
    raw_score = (
        ACTIVITY_CATEGORIES["crowd_density"]["weight"] * max(crowd_density, type_signals["crowd_density"])
        + ACTIVITY_CATEGORIES["traffic_corridor"]["weight"] * type_signals["traffic_corridor"]
        + ACTIVITY_CATEGORIES["temporal_spike"]["weight"] * spike_score
        + ACTIVITY_CATEGORIES["hazard_zone"]["weight"] * type_signals["hazard_zone"]
        + ACTIVITY_CATEGORIES["emergency_cluster"]["weight"] * type_signals["emergency_cluster"]
    )

    # Apply hour-of-day multiplier and acceleration boost
    adjusted = raw_score * (0.5 + 0.5 * hour_activity) + max(0, acceleration) * 0.1
    risk_score = round(min(10.0, adjusted * 10.0), 1)

    # Risk level
    risk_level = "critical" if risk_score >= 8 else "high" if risk_score >= 6 else "medium" if risk_score >= 4 else "low"

    # Build factors
    factors = []
    if crowd_density > 0.5:
        factors.append(f"High crowd density ({len(nearby_500m)} incidents in 500m)")
    if spike_score > 0.3:
        factors.append(f"Activity spike at hour {peak_hour}:00")
    if type_signals["hazard_zone"] > 0.4:
        factors.append("Physical hazard zone (fall incidents)")
    if type_signals["emergency_cluster"] > 0.4:
        factors.append("Emergency cluster (SOS alerts)")
    if type_signals["traffic_corridor"] > 0.3:
        factors.append("Traffic corridor risk")
    if acceleration > 0.3:
        factors.append("Accelerating incident rate")
    if hour_activity >= 0.8:
        factors.append(f"Peak activity hour ({hour}:00)")
    if not factors:
        factors.append("Low activity area")

    return {
        "lat": lat,
        "lng": lng,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "factors": factors,
        "signals": {
            "crowd_density": round(crowd_density, 3),
            "temporal_spike": round(spike_score, 3),
            "peak_activity_hour": peak_hour,
            "hazard_zone": round(type_signals["hazard_zone"], 3),
            "emergency_cluster": round(type_signals["emergency_cluster"], 3),
            "traffic_corridor": round(type_signals["traffic_corridor"], 3),
            "acceleration": round(acceleration, 3),
            "hour_activity_level": hour_activity,
        },
        "incident_counts": {
            "within_500m": len(nearby_500m),
            "within_1km": len(nearby_1km),
        },
        "assessed_at": now.isoformat(),
    }


async def get_fleet_activity_risk(session: AsyncSession) -> dict:
    """Assess activity risk around all active devices."""
    now = datetime.now(timezone.utc)

    # Get latest device positions
    devices = (await session.execute(text("""
        SELECT DISTINCT ON (d.id)
            d.id, d.device_identifier as device_name, s.full_name as senior_name,
            dl.latitude, dl.longitude, dl.updated_at as last_seen
        FROM devices d
        JOIN seniors s ON d.senior_id = s.id
        JOIN device_locations dl ON dl.device_id = d.id
        WHERE dl.latitude IS NOT NULL AND dl.longitude IS NOT NULL
        ORDER BY d.id, dl.updated_at DESC
    """))).fetchall()

    assessments = []
    high_risk_count = 0
    for dev in devices:
        assessment = await assess_location_activity_risk(
            session, float(dev.latitude), float(dev.longitude)
        )
        assessment["device_id"] = str(dev.id)
        assessment["device_name"] = dev.device_name
        assessment["senior_name"] = dev.senior_name
        assessments.append(assessment)
        if assessment["risk_score"] >= 6:
            high_risk_count += 1

    assessments.sort(key=lambda x: x["risk_score"], reverse=True)

    return {
        "total_devices": len(assessments),
        "high_risk_count": high_risk_count,
        "assessments": assessments,
        "assessed_at": now.isoformat(),
    }


async def get_activity_hotspots(session: AsyncSession) -> dict:
    """Identify areas with highest human activity risk."""
    now = datetime.now(timezone.utc)

    # Get all learned hotspot zones and assess each
    zones = (await session.execute(text("""
        SELECT id, zone_name, latitude, longitude, radius_meters, risk_score, risk_level
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
        ORDER BY risk_score DESC
    """))).fetchall()

    hotspots = []
    for z in zones:
        lat, lng = float(z.latitude), float(z.longitude)
        assessment = await assess_location_activity_risk(session, lat, lng)
        hotspots.append({
            "zone_id": str(z.id),
            "zone_name": z.zone_name,
            "zone_risk_score": float(z.risk_score),
            "activity_risk_score": assessment["risk_score"],
            "activity_risk_level": assessment["risk_level"],
            "activity_factors": assessment["factors"],
            "activity_signals": assessment["signals"],
            "incident_counts": assessment["incident_counts"],
            "lat": lat,
            "lng": lng,
            "combined_risk": round(min(10.0, float(z.risk_score) * 0.5 + assessment["risk_score"] * 0.5), 1),
        })

    hotspots.sort(key=lambda x: x["combined_risk"], reverse=True)

    high_activity = [h for h in hotspots if h["activity_risk_score"] >= 6]
    crowd_zones = [h for h in hotspots if h["activity_signals"]["crowd_density"] > 0.4]
    hazard_zones = [h for h in hotspots if h["activity_signals"]["hazard_zone"] > 0.3]

    return {
        "total_zones": len(hotspots),
        "high_activity_count": len(high_activity),
        "crowd_zones_count": len(crowd_zones),
        "hazard_zones_count": len(hazard_zones),
        "hotspots": hotspots,
        "analyzed_at": now.isoformat(),
    }
