# Hotspot Trend Engine
# Analyzes how learned hotspot zones change over rolling time windows.
# Classifies each zone as: Emerging, Growing, Stable, Declining, Dormant.

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SEVERITY_WEIGHT = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}

# Trend thresholds
TREND_GROWING = 0.35
TREND_EMERGING = 0.10
TREND_STABLE_LOW = -0.10

WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

TREND_MULTIPLIER = {"growing": 1.25, "emerging": 1.15, "stable": 1.0, "declining": 0.9, "dormant": 0.8}


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _classify(score: float, recent_count: int) -> str:
    if recent_count == 0:
        return "dormant"
    if score > TREND_GROWING:
        return "growing"
    if score > TREND_EMERGING:
        return "emerging"
    if score >= TREND_STABLE_LOW:
        return "stable"
    return "declining"


def _priority(trend_status: str, risk_score: float, severity_ratio: float) -> int:
    if trend_status == "growing" and risk_score >= 5:
        return 1
    if trend_status in ("growing", "emerging") and severity_ratio >= 0.5:
        return 1
    if trend_status in ("stable", "emerging") and risk_score >= 7:
        return 2
    if trend_status == "growing":
        return 2
    return 3


def _filter_near(incidents: list[dict], lat: float, lng: float, radius_m: float) -> list[dict]:
    """Filter incidents within radius of a zone center."""
    deg_approx = (radius_m / 1000.0) * 0.009 + 0.002
    result = []
    for inc in incidents:
        if abs(inc["lat"] - lat) > deg_approx or abs(inc["lng"] - lng) > deg_approx:
            continue
        if _haversine(lat, lng, inc["lat"], inc["lng"]) <= radius_m:
            result.append(inc)
    return result


def _compute_window_stats(incidents: list[dict]) -> dict:
    if not incidents:
        return {"count": 0, "severity_weighted": 0.0, "severity_dist": {},
                "night_count": 0, "type_dist": {}, "high_sev_ratio": 0.0}

    severity_dist = defaultdict(int)
    type_dist = defaultdict(int)
    total_weight = 0.0
    night_count = 0
    for inc in incidents:
        sev = inc["severity"]
        severity_dist[sev] += 1
        type_dist[inc["incident_type"]] += 1
        total_weight += SEVERITY_WEIGHT.get(sev, 1.0)
        if inc["hour"] >= 22 or inc["hour"] < 6:
            night_count += 1

    high_sev = severity_dist.get("critical", 0) + severity_dist.get("high", 0)
    return {
        "count": len(incidents),
        "severity_weighted": round(total_weight, 2),
        "severity_dist": dict(severity_dist),
        "night_count": night_count,
        "type_dist": dict(type_dist),
        "high_sev_ratio": round(high_sev / len(incidents), 2),
    }


def _compute_trend_score(recent: dict, previous: dict) -> float:
    prev_count = max(previous["count"], 1)
    recent_count = recent["count"]
    growth_rate = max(-1.0, min(2.0, (recent_count - prev_count) / prev_count))
    prev_sw = previous["severity_weighted"] / max(prev_count, 1)
    recent_sw = recent["severity_weighted"] / max(recent_count, 1)
    sw_delta = max(-1.0, min(1.0, (recent_sw - prev_sw) / max(prev_sw, 0.5)))
    sev_shift = recent["high_sev_ratio"] - previous["high_sev_ratio"]
    prev_night_ratio = previous["night_count"] / max(prev_count, 1)
    recent_night_ratio = recent["night_count"] / max(recent_count, 1)
    temporal = recent_night_ratio - prev_night_ratio
    return round(0.45 * growth_rate + 0.30 * sw_delta + 0.15 * sev_shift + 0.10 * temporal, 4)


async def _fetch_all_incidents(session: AsyncSession, lookback: timedelta) -> list[dict]:
    """Fetch all geolocated incidents in one query for the max lookback window."""
    now = datetime.now(timezone.utc)
    cutoff = now - lookback
    rows = (await session.execute(text("""
        SELECT li.id, li.latitude, li.longitude, li.incident_type, li.severity, li.created_at
        FROM location_incidents li
        JOIN incidents i ON li.incident_id = i.id
        WHERE li.created_at >= :cutoff AND li.latitude IS NOT NULL
        ORDER BY li.created_at DESC
    """), {"cutoff": cutoff})).fetchall()

    return [{
        "id": r.id, "lat": float(r.latitude), "lng": float(r.longitude),
        "incident_type": r.incident_type, "severity": r.severity,
        "created_at": r.created_at, "hour": r.created_at.hour if r.created_at else 0,
    } for r in rows]


def _compute_zone_trend(zone: dict, all_incidents: list[dict], now: datetime) -> dict:
    """Compute trend for a single zone using pre-fetched incidents (no DB calls)."""
    lat, lng = zone["lat"], zone["lng"]
    radius = zone.get("radius_meters", 500)

    # Filter incidents near this zone once
    nearby = _filter_near(all_incidents, lat, lng, radius)

    windows_data = {}
    for window_name, delta in WINDOWS.items():
        recent_start = now - delta
        previous_start = recent_start - delta

        recent_incs = [i for i in nearby if recent_start <= i["created_at"] <= now]
        previous_incs = [i for i in nearby if previous_start <= i["created_at"] < recent_start]

        recent_stats = _compute_window_stats(recent_incs)
        previous_stats = _compute_window_stats(previous_incs)
        trend_score = _compute_trend_score(recent_stats, previous_stats)
        status = _classify(trend_score, recent_stats["count"])

        windows_data[window_name] = {
            "recent": recent_stats,
            "previous": previous_stats,
            "trend_score": trend_score,
            "trend_status": status,
            "incident_delta": recent_stats["count"] - previous_stats["count"],
            "score_delta": round(recent_stats["severity_weighted"] - previous_stats["severity_weighted"], 2),
            "confidence_delta": round(recent_stats["high_sev_ratio"] - previous_stats["high_sev_ratio"], 2),
            "night_delta": recent_stats["night_count"] - previous_stats["night_count"],
        }

    # Primary trend uses 7d window
    primary = windows_data.get("7d", {})
    primary_status = primary.get("trend_status", "stable")
    high_sev_ratio = primary.get("recent", {}).get("high_sev_ratio", 0)
    priority = _priority(primary_status, zone.get("risk_score", 0), high_sev_ratio)

    # Sparkline: daily counts for last 7 days (from pre-fetched data)
    sparkline = []
    for day_offset in range(6, -1, -1):
        day_start = now - timedelta(days=day_offset + 1)
        day_end = now - timedelta(days=day_offset)
        count = sum(1 for i in nearby if day_start <= i["created_at"] < day_end)
        sparkline.append(count)

    return {
        "zone_id": zone.get("zone_id", ""),
        "zone_name": zone.get("zone_name", ""),
        "risk_score": zone.get("risk_score", 0),
        "risk_level": zone.get("risk_level", ""),
        "lat": lat,
        "lng": lng,
        "radius_meters": radius,
        "incident_count": zone.get("incident_count", 0),
        "factors": zone.get("factors", []),
        "last_updated": zone.get("last_updated"),
        "trend_status": primary_status,
        "trend_score": primary.get("trend_score", 0),
        "recommended_priority": priority,
        "sparkline_7d": sparkline,
        "windows": windows_data,
    }


async def _update_zone_trend_metadata(session: AsyncSession, trends: list[dict]):
    """Persist trend+forecast status into zone factors for route/location risk engines."""
    for t in trends:
        zone_id = t.get("zone_id")
        if not zone_id:
            continue
        status = t.get("trend_status", "stable")
        priority = t.get("recommended_priority", 3)
        trend_score = t.get("trend_score", 0)
        base_mult = TREND_MULTIPLIER.get(status, 1.0)

        # Quick forecast: if growing fast, increase multiplier for route penalty
        # predicted_48h_delta ≈ trend_score * 2 (48h = 2 days)
        predicted_delta = trend_score * 2.0
        predicted_48h = t.get("risk_score", 0) + predicted_delta
        forecast_boost = 0.0
        if predicted_48h >= 7.0 and trend_score > 0.1:
            forecast_boost = 0.1  # extra 10% penalty for zones forecast to be P1
        multiplier = min(1.5, base_mult + forecast_boost)

        meta = json.dumps({
            "trend_status": status,
            "trend_multiplier": round(multiplier, 2),
            "trend_priority": priority,
            "trend_score": trend_score,
            "predicted_48h": round(predicted_48h, 1),
        })

        await session.execute(text("""
            UPDATE location_risk_zones
            SET factors = (
                SELECT jsonb_agg(elem)
                FROM jsonb_array_elements(COALESCE(factors, '[]'::jsonb)) elem
                WHERE NOT (elem ? 'trend_status')
            ) || CAST(:meta AS jsonb)
            WHERE id = :zid
        """), {"zid": int(zone_id), "meta": f'[{meta}]'})

    await session.commit()
    logger.info(f"Updated trend+forecast metadata for {len(trends)} zones")


async def _fetch_zones(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT id, zone_name, risk_score, risk_level, incident_count, factors,
               latitude, longitude, radius_meters, last_updated
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
        ORDER BY risk_score DESC
    """))).fetchall()

    zones = []
    for z in rows:
        fac = z.factors
        if isinstance(fac, str):
            fac = json.loads(fac)
        # Filter out trend metadata objects from display factors
        display_factors = [f for f in (fac or []) if isinstance(f, str)]
        zones.append({
            "zone_id": str(z.id),
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
    return zones


async def get_all_trends(session: AsyncSession) -> dict:
    """Compute trends for all learned hotspot zones (optimized: 2 DB queries total)."""
    now = datetime.now(timezone.utc)

    zones = await _fetch_zones(session)
    if not zones:
        return {"total_zones": 0, "status_counts": {}, "priority_counts": {},
                "trends": [], "top_growing": [], "top_declining": [],
                "emerging_night_risk": [], "analyzed_at": now.isoformat()}

    # Single batch fetch of ALL incidents for max lookback (60 days covers 30d window + 30d previous)
    all_incidents = await _fetch_all_incidents(session, timedelta(days=60))

    # Compute trends in-memory
    trends = [_compute_zone_trend(zone, all_incidents, now) for zone in zones]

    status_counts = defaultdict(int)
    priority_counts = defaultdict(int)
    for t in trends:
        status_counts[t["trend_status"]] += 1
        priority_counts[t["recommended_priority"]] += 1

    growing = sorted([t for t in trends if t["trend_status"] in ("growing", "emerging")],
                     key=lambda x: x["trend_score"], reverse=True)
    declining = sorted([t for t in trends if t["trend_status"] == "declining"],
                       key=lambda x: x["trend_score"])
    night_risk = sorted([t for t in trends if t["windows"].get("7d", {}).get("night_delta", 0) > 0],
                        key=lambda x: x["windows"].get("7d", {}).get("night_delta", 0), reverse=True)

    # Persist trend metadata for integration engines
    await _update_zone_trend_metadata(session, trends)

    return {
        "total_zones": len(trends),
        "status_counts": dict(status_counts),
        "priority_counts": {str(k): v for k, v in priority_counts.items()},
        "trends": trends,
        "top_growing": growing[:5],
        "top_declining": declining[:5],
        "emerging_night_risk": night_risk[:5],
        "analyzed_at": now.isoformat(),
    }


async def get_zone_trend(session: AsyncSession, zone_id: str) -> dict | None:
    """Compute detailed trend for a single zone."""
    now = datetime.now(timezone.utc)

    row = (await session.execute(text("""
        SELECT id, zone_name, risk_score, risk_level, incident_count, factors,
               latitude, longitude, radius_meters, last_updated
        FROM location_risk_zones
        WHERE id = :zid AND risk_type = 'learned_hotspot'
    """), {"zid": int(zone_id)})).fetchone()

    if not row:
        return None

    fac = row.factors
    if isinstance(fac, str):
        fac = json.loads(fac)
    display_factors = [f for f in (fac or []) if isinstance(f, str)]

    zone = {
        "zone_id": str(row.id),
        "zone_name": row.zone_name,
        "risk_score": float(row.risk_score),
        "risk_level": row.risk_level,
        "incident_count": row.incident_count,
        "factors": display_factors,
        "lat": float(row.latitude),
        "lng": float(row.longitude),
        "radius_meters": float(row.radius_meters),
        "last_updated": row.last_updated.isoformat() if row.last_updated else None,
    }

    all_incidents = await _fetch_all_incidents(session, timedelta(days=60))
    return _compute_zone_trend(zone, all_incidents, now)


async def get_trend_summary(session: AsyncSession) -> dict:
    """Get high-level trend statistics (optimized: 2 DB queries)."""
    now = datetime.now(timezone.utc)

    zones = await _fetch_zones(session)
    if not zones:
        return {"total_zones": 0, "status_counts": {}, "priority_counts": {},
                "avg_trend_score": 0, "zones_needing_attention": 0,
                "analyzed_at": now.isoformat()}

    # Single batch fetch for 14 days (7d recent + 7d previous)
    all_incidents = await _fetch_all_incidents(session, timedelta(days=14))

    window = timedelta(days=7)
    recent_start = now - window
    previous_start = recent_start - window

    statuses = []
    priorities = []
    attention_count = 0

    for zone in zones:
        nearby = _filter_near(all_incidents, zone["lat"], zone["lng"], zone.get("radius_meters", 500))
        recent = [i for i in nearby if recent_start <= i["created_at"] <= now]
        previous = [i for i in nearby if previous_start <= i["created_at"] < recent_start]

        r_stats = _compute_window_stats(recent)
        p_stats = _compute_window_stats(previous)
        t_score = _compute_trend_score(r_stats, p_stats)
        status = _classify(t_score, r_stats["count"])
        priority = _priority(status, zone["risk_score"], r_stats["high_sev_ratio"])

        statuses.append((status, t_score))
        priorities.append(priority)
        if priority <= 2:
            attention_count += 1

    status_counts = defaultdict(int)
    priority_counts = defaultdict(int)
    for s, _ in statuses:
        status_counts[s] += 1
    for p in priorities:
        priority_counts[p] += 1

    scores = [s for _, s in statuses]
    avg_score = round(sum(scores) / len(scores), 4) if scores else 0

    return {
        "total_zones": len(zones),
        "status_counts": dict(status_counts),
        "priority_counts": {str(k): v for k, v in priority_counts.items()},
        "avg_trend_score": avg_score,
        "zones_needing_attention": attention_count,
        "analyzed_at": now.isoformat(),
    }
