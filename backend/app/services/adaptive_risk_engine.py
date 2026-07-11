# Adaptive Risk Learning Engine
# Learns from past incidents to auto-generate hotspot risk zones.
# Uses spatial clustering, temporal decay, severity weighting, and time-of-day patterns.

import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Configuration ──
CLUSTER_RADIUS_M = 500        # Incidents within 500m form a cluster
MIN_INCIDENTS_FOR_HOTSPOT = 2  # Minimum incidents to create a hotspot
DECAY_HALF_LIFE_DAYS = 30     # Risk halves every 30 days
MAX_RISK_SCORE = 9.5           # Cap for learned zones (leave room for manual zones at 10)
RECALC_INTERVAL_HOURS = 6     # Background job interval
INCIDENT_LOOKBACK_DAYS = 180  # Only consider incidents from last 6 months

SEVERITY_WEIGHT = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}

# Time-of-day risk amplifiers (incidents during these hours amplify risk for same hours)
TOD_BUCKETS = {
    "night":     (22, 6),   # 10pm - 6am
    "morning":   (6, 12),
    "afternoon": (12, 18),
    "evening":   (18, 22),
}


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_tod_bucket(hour: int) -> str:
    for name, (start, end) in TOD_BUCKETS.items():
        if start < end:
            if start <= hour < end:
                return name
        else:  # wraps midnight
            if hour >= start or hour < end:
                return name
    return "afternoon"


def _decay_weight(days_ago: float) -> float:
    """Exponential decay: weight = 2^(-days_ago / half_life)."""
    return 2 ** (-days_ago / DECAY_HALF_LIFE_DAYS)


def _cluster_incidents(incidents: list[dict]) -> list[dict]:
    """Simple single-linkage clustering of incidents by proximity."""
    if not incidents:
        return []

    assigned = [False] * len(incidents)
    clusters = []

    for i in range(len(incidents)):
        if assigned[i]:
            continue
        cluster = [incidents[i]]
        assigned[i] = True
        queue = [i]

        while queue:
            current = queue.pop(0)
            clat, clng = incidents[current]["lat"], incidents[current]["lng"]
            for j in range(len(incidents)):
                if assigned[j]:
                    continue
                dist = _haversine(clat, clng, incidents[j]["lat"], incidents[j]["lng"])
                if dist <= CLUSTER_RADIUS_M:
                    assigned[j] = True
                    cluster.append(incidents[j])
                    queue.append(j)

        clusters.append(cluster)

    return clusters


def _compute_hotspot(cluster: list[dict], now: datetime) -> dict | None:
    """Compute a hotspot from a cluster of incidents."""
    if len(cluster) < MIN_INCIDENTS_FOR_HOTSPOT:
        return None

    # Centroid
    lat = sum(i["lat"] for i in cluster) / len(cluster)
    lng = sum(i["lng"] for i in cluster) / len(cluster)

    # Weighted risk score
    total_weight = 0
    tod_counts = defaultdict(int)
    severity_counts = defaultdict(int)
    types = defaultdict(int)

    for inc in cluster:
        days_ago = (now - inc["created_at"]).total_seconds() / 86400
        decay = _decay_weight(days_ago)
        sev_w = SEVERITY_WEIGHT.get(inc["severity"], 1.0)
        total_weight += decay * sev_w

        tod = _get_tod_bucket(inc["created_at"].hour)
        tod_counts[tod] += 1
        severity_counts[inc["severity"]] += 1
        types[inc["incident_type"]] += 1

    # Base risk from weighted incident count
    # 2 incidents = ~3.0, 5 incidents = ~5.5, 10+ incidents = ~8.0
    base_risk = min(MAX_RISK_SCORE, 1.5 + math.log2(1 + total_weight) * 2.0)

    # Dominant time-of-day
    dominant_tod = max(tod_counts, key=tod_counts.get) if tod_counts else "afternoon"
    night_ratio = (tod_counts.get("night", 0) + tod_counts.get("evening", 0)) / max(len(cluster), 1)

    # Factors
    factors = []
    top_type = max(types, key=types.get)
    factors.append(f"{len(cluster)} incidents in area")
    factors.append(f"Most common: {top_type.replace('_', ' ')}")
    if night_ratio > 0.5:
        factors.append("Elevated night risk")
    if severity_counts.get("critical", 0) + severity_counts.get("high", 0) > len(cluster) * 0.5:
        factors.append("High-severity pattern")

    # Compute max spread radius
    max_dist = 0
    for inc in cluster:
        d = _haversine(lat, lng, inc["lat"], inc["lng"])
        if d > max_dist:
            max_dist = d
    radius = max(200, min(800, max_dist + 100))

    return {
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "risk_score": round(base_risk, 1),
        "incident_count": len(cluster),
        "radius_meters": round(radius),
        "factors": factors,
        "tod_distribution": dict(tod_counts),
        "severity_distribution": dict(severity_counts),
        "type_distribution": dict(types),
        "dominant_tod": dominant_tod,
        "night_ratio": round(night_ratio, 2),
        "total_weight": round(total_weight, 2),
    }


async def analyze_and_update_hotspots(session: AsyncSession) -> dict:
    """Main function: analyze incidents and create/update learned risk zones."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=INCIDENT_LOOKBACK_DAYS)

    logger.info("Adaptive Risk Learning: starting hotspot analysis")

    # Fetch all geolocated incidents within lookback window
    rows = (await session.execute(text("""
        SELECT li.id, li.latitude, li.longitude, li.incident_type, li.severity, li.created_at,
               i.status
        FROM location_incidents li
        JOIN incidents i ON li.incident_id = i.id
        WHERE li.created_at >= :cutoff
          AND li.latitude IS NOT NULL AND li.longitude IS NOT NULL
        ORDER BY li.created_at DESC
    """), {"cutoff": cutoff})).fetchall()

    incidents = [{
        "id": r.id,
        "lat": float(r.latitude),
        "lng": float(r.longitude),
        "incident_type": r.incident_type,
        "severity": r.severity,
        "created_at": r.created_at,
        "status": r.status,
    } for r in rows]

    logger.info(f"Adaptive Risk Learning: {len(incidents)} incidents in {INCIDENT_LOOKBACK_DAYS}d window")

    # Cluster incidents
    clusters = _cluster_incidents(incidents)

    # Compute hotspots
    hotspots = []
    for cluster in clusters:
        hotspot = _compute_hotspot(cluster, now)
        if hotspot:
            hotspots.append(hotspot)

    # Sort by risk score descending
    hotspots.sort(key=lambda h: h["risk_score"], reverse=True)

    # Clear old learned zones
    deleted = (await session.execute(text("""
        DELETE FROM location_risk_zones WHERE risk_type = 'learned_hotspot'
        RETURNING id
    """))).fetchall()

    # Insert new learned zones
    for h in hotspots:
        risk_level = "critical" if h["risk_score"] >= 7 else "high" if h["risk_score"] >= 5 else "medium" if h["risk_score"] >= 3 else "low"
        zone_name = f"Learned Hotspot ({h['incident_count']} incidents)"

        await session.execute(text("""
            INSERT INTO location_risk_zones
                (latitude, longitude, geom, radius_meters, risk_score, risk_level,
                 risk_type, factors, zone_name, incident_count, last_updated)
            VALUES
                (:lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                 :radius, :score, :level, 'learned_hotspot', CAST(:factors AS jsonb),
                 :name, :inc_count, NOW())
        """), {
            "lat": h["lat"], "lng": h["lng"],
            "radius": h["radius_meters"],
            "score": h["risk_score"],
            "level": risk_level,
            "factors": __import__("json").dumps(h["factors"]),
            "name": zone_name,
            "inc_count": h["incident_count"],
        })

    await session.commit()

    stats = {
        "incidents_analyzed": len(incidents),
        "clusters_found": len(clusters),
        "hotspots_created": len(hotspots),
        "old_zones_removed": len(deleted),
        "top_hotspots": hotspots[:5],
        "last_updated": now.isoformat(),
    }

    logger.info(f"Adaptive Risk Learning: created {len(hotspots)} hotspot zones from {len(incidents)} incidents")
    return stats


async def get_learning_stats(session: AsyncSession) -> dict:
    """Get current learning statistics."""
    now = datetime.now(timezone.utc)

    # Count learned zones
    learned_count = (await session.execute(text(
        "SELECT COUNT(*) FROM location_risk_zones WHERE risk_type = 'learned_hotspot'"
    ))).scalar() or 0

    # Count manual zones
    manual_count = (await session.execute(text(
        "SELECT COUNT(*) FROM location_risk_zones WHERE risk_type != 'learned_hotspot' OR risk_type IS NULL"
    ))).scalar() or 0

    # Get learned zone details
    learned_zones = (await session.execute(text("""
        SELECT zone_name, risk_score, risk_level, incident_count, factors,
               latitude, longitude, radius_meters, last_updated
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
        ORDER BY risk_score DESC
    """))).fetchall()

    # Incident stats
    cutoff = now - timedelta(days=INCIDENT_LOOKBACK_DAYS)
    total_incidents = (await session.execute(text(
        "SELECT COUNT(*) FROM location_incidents WHERE created_at >= :cutoff"
    ), {"cutoff": cutoff})).scalar() or 0

    geolocated = (await session.execute(text(
        "SELECT COUNT(*) FROM location_incidents WHERE latitude IS NOT NULL AND created_at >= :cutoff"
    ), {"cutoff": cutoff})).scalar() or 0

    import json
    zones = []
    for z in learned_zones:
        fac = z.factors
        if isinstance(fac, str):
            fac = json.loads(fac)
        # Filter out trend metadata objects - only keep string factors
        display_factors = [f for f in (fac or []) if isinstance(f, str)]
        zones.append({
            "zone_name": z.zone_name,
            "risk_score": float(z.risk_score),
            "risk_level": z.risk_level,
            "incident_count": z.incident_count,
            "factors": display_factors,
            "lat": float(z.latitude),
            "lng": float(z.longitude),
            "radius_meters": float(z.radius_meters),
            "last_updated": z.last_updated.isoformat() if z.last_updated else None,
        })

    return {
        "learned_zones_count": learned_count,
        "manual_zones_count": manual_count,
        "total_zones": learned_count + manual_count,
        "incidents_in_window": total_incidents,
        "geolocated_incidents": geolocated,
        "lookback_days": INCIDENT_LOOKBACK_DAYS,
        "cluster_radius_m": CLUSTER_RADIUS_M,
        "min_incidents_for_hotspot": MIN_INCIDENTS_FOR_HOTSPOT,
        "decay_half_life_days": DECAY_HALF_LIFE_DAYS,
        "learned_zones": zones,
        "last_analysis": zones[0]["last_updated"] if zones else None,
    }
