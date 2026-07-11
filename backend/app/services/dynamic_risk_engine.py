# Dynamic City Risk Engine (Phase 39)
# Production-grade risk pipeline with 8 signal layers, adaptive weights,
# snapshot storage, delta detection, and cache management.
# Architecture: Signal Aggregator → Risk Scoring → Snapshot Store → Cache Layer

import logging
import math
import time as _time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Grid Configuration ──
GRID_CELL_SIZE_M = 250
GRID_PADDING_M = 500

# ── Risk Classification ──
RISK_CRITICAL = 7.0
RISK_HIGH = 5.0
RISK_MODERATE = 3.0

# ── Severity Weights ──
SEVERITY_W = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}

# ── Activity Signal Weights ──
ACTIVITY_W = {
    "SOS": 3.0, "fall_detected": 2.5, "route_deviation": 1.5,
    "geofence_breach": 1.5, "device_offline": 1.0, "low_battery": 0.5,
}

# ── Adaptive Weight Profiles ──
# Weights shift based on time-of-day to improve accuracy
WEIGHT_PROFILES = {
    "day": {
        "forecast": 0.25, "hotspot": 0.20, "trend": 0.15, "activity": 0.12,
        "patrol": 0.10, "environment": 0.05, "session_density": 0.08, "mobility_anomaly": 0.05,
    },
    "night": {
        "forecast": 0.20, "hotspot": 0.18, "trend": 0.12, "activity": 0.18,
        "patrol": 0.08, "environment": 0.10, "session_density": 0.06, "mobility_anomaly": 0.08,
    },
    "late_night": {
        "forecast": 0.18, "hotspot": 0.15, "trend": 0.10, "activity": 0.20,
        "patrol": 0.07, "environment": 0.12, "session_density": 0.05, "mobility_anomaly": 0.13,
    },
}

RISK_RANK = {"safe": 0, "moderate": 1, "high": 2, "critical": 3}
TIMELINE_MAX = 12  # Keep last 12 snapshots (1 hour at 5-min intervals)

# ── In-Memory Fallback Cache + Redis Primary ──
_risk_cache = {}  # Fallback only if Redis unavailable


def _get_cache(city_id: str = "default") -> dict:
    """Get cache from Redis first, then fall back to in-memory."""
    from app.services.redis_service import get_heatmap_live, get_heatmap_delta, get_heatmap_timeline, get_heatmap_meta

    meta = get_heatmap_meta()
    if meta and meta.get("city_id") == city_id:
        # Redis has data — reconstruct cache structure
        return {
            "current": get_heatmap_live(),
            "previous": None,  # Not stored in Redis (only needed for delta computation)
            "delta": get_heatmap_delta(),
            "timeline": get_heatmap_timeline() or [],
            "computed_at": meta.get("computed_at"),
            "count": meta.get("count", 0),
        }

    # Fallback to in-memory
    if city_id not in _risk_cache:
        _risk_cache[city_id] = {
            "current": None, "previous": None, "delta": None,
            "timeline": [], "computed_at": None, "count": 0,
        }
    return _risk_cache[city_id]


def _update_cache(city_id: str, result: dict, delta: dict, timeline: list, count: int, now):
    """Write cache to Redis (primary) and in-memory (fallback)."""
    from app.services.redis_service import (
        cache_heatmap_live, cache_heatmap_delta,
        cache_heatmap_timeline, cache_heatmap_meta,
        cache_safety_score_grid, is_available,
    )

    # Extract grid scores for percentile ranking
    grid_scores = [c["composite_score"] for c in result.get("cells", [])]

    if is_available():
        cache_heatmap_live(result)
        cache_heatmap_delta(delta)
        cache_heatmap_timeline(timeline)
        cache_heatmap_meta({
            "city_id": city_id,
            "computed_at": now.isoformat() if hasattr(now, 'isoformat') else str(now),
            "count": count,
            "total_cells": result.get("total_cells", 0),
        })
        cache_safety_score_grid(grid_scores)
        logger.info(f"Dynamic Risk [{city_id}]: Cache written to Redis ({len(grid_scores)} grid scores)")
    else:
        logger.info(f"Dynamic Risk [{city_id}]: Redis unavailable, using in-memory fallback")

    # Always update in-memory fallback
    if city_id not in _risk_cache:
        _risk_cache[city_id] = {"current": None, "previous": None, "delta": None, "timeline": [], "computed_at": None, "count": 0}
    mem = _risk_cache[city_id]
    mem["previous"] = mem["current"]
    mem["current"] = result
    mem["delta"] = delta
    mem["computed_at"] = now
    mem["count"] = count
    mem["timeline"] = timeline


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _meters_to_deg_lat(meters):
    return meters / 111_320.0


def _meters_to_deg_lng(meters, lat):
    return meters / (111_320.0 * math.cos(math.radians(lat)))


def _get_weight_profile(hour: int) -> tuple[str, dict]:
    if 6 <= hour < 20:
        return "day", WEIGHT_PROFILES["day"]
    elif 20 <= hour < 24:
        return "night", WEIGHT_PROFILES["night"]
    return "late_night", WEIGHT_PROFILES["late_night"]


def _classify_risk(score: float) -> str:
    if score >= RISK_CRITICAL:
        return "critical"
    if score >= RISK_HIGH:
        return "high"
    if score >= RISK_MODERATE:
        return "moderate"
    return "safe"


# ── Data Fetchers ──

async def _fetch_zones(session: AsyncSession) -> list[dict]:
    import json
    rows = (await session.execute(text("""
        SELECT id, zone_name, latitude, longitude, radius_meters,
               risk_score, risk_level, incident_count, factors
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
        ORDER BY risk_score DESC
    """))).fetchall()

    zones = []
    for z in rows:
        fac = z.factors
        if isinstance(fac, str):
            fac = json.loads(fac)
        trend_meta = {}
        for f in (fac or []):
            if isinstance(f, dict) and "trend_status" in f:
                trend_meta = f
        zones.append({
            "zone_id": str(z.id), "zone_name": z.zone_name,
            "lat": float(z.latitude), "lng": float(z.longitude),
            "radius_meters": float(z.radius_meters),
            "risk_score": float(z.risk_score), "risk_level": z.risk_level,
            "incident_count": z.incident_count, "trend_meta": trend_meta,
        })
    return zones


async def _fetch_incidents(session: AsyncSession, days: int = 30) -> list[dict]:
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
        "lat": float(r.latitude), "lng": float(r.longitude),
        "severity": r.severity, "incident_type": r.incident_type,
        "created_at": r.created_at, "hour": int(r.hour),
    } for r in rows]


async def _fetch_active_sessions(session: AsyncSession) -> list[dict]:
    """Fetch active guardian sessions for session density + mobility signals."""
    try:
        rows = (await session.execute(text("""
            SELECT id, user_id, current_location, destination,
                   risk_level, speed_mps, started_at
            FROM guardian_sessions
            WHERE status = 'active'
        """))).fetchall()
        results = []
        for r in rows:
            loc = r.current_location
            if loc and isinstance(loc, dict) and "lat" in loc:
                results.append({
                    "lat": loc["lat"], "lng": loc["lng"],
                    "speed_mps": float(r.speed_mps) if r.speed_mps else 0,
                    "started_at": r.started_at,
                })
        return results
    except Exception:
        return []


# ── Grid Builder ──

def _build_grid(zones: list[dict], incidents: list[dict]) -> list[dict]:
    all_lats = [z["lat"] for z in zones] + [i["lat"] for i in incidents]
    all_lngs = [z["lng"] for z in zones] + [i["lng"] for i in incidents]
    if not all_lats:
        return []

    pad_lat = _meters_to_deg_lat(GRID_PADDING_M)
    center_lat = (min(all_lats) + max(all_lats)) / 2
    pad_lng = _meters_to_deg_lng(GRID_PADDING_M, center_lat)

    min_lat, max_lat = min(all_lats) - pad_lat, max(all_lats) + pad_lat
    min_lng, max_lng = min(all_lngs) - pad_lng, max(all_lngs) + pad_lng

    step_lat = _meters_to_deg_lat(GRID_CELL_SIZE_M)
    step_lng = _meters_to_deg_lng(GRID_CELL_SIZE_M, center_lat)

    cells = []
    row = 0
    lat = min_lat
    while lat <= max_lat:
        col = 0
        lng = min_lng
        while lng <= max_lng:
            cells.append({
                "grid_id": f"C{row:03d}_{col:03d}",
                "lat": round(lat + step_lat / 2, 6),
                "lng": round(lng + step_lng / 2, 6),
            })
            lng += step_lng
            col += 1
        lat += step_lat
        row += 1
    return cells


# ── 8 Signal Scorers ──

def _score_hotspot(clat, clng, zones):
    """Signal 1: Hotspot density (0-10)"""
    influence = 0.0
    for z in zones:
        dist = _haversine(clat, clng, z["lat"], z["lng"])
        radius = z.get("radius_meters", 500) * 1.5
        if dist <= radius:
            proximity = 1.0 - (dist / radius)
            influence += z["risk_score"] * proximity
    return round(min(10.0, influence), 2)


def _score_trend(clat, clng, zones, trend_data):
    """Signal 2: Trend growth (0-10)"""
    status_score = {"growing": 8.0, "emerging": 5.5, "stable": 3.0, "declining": 1.5, "dormant": 0.5}
    best_score, best_status = 0.0, "stable"
    for z in zones:
        dist = _haversine(clat, clng, z["lat"], z["lng"])
        if dist <= z.get("radius_meters", 500) * 1.5:
            td = trend_data.get(z["zone_id"], {})
            ts = td.get("trend_status", "stable")
            sc = status_score.get(ts, 3.0)
            raw_trend = td.get("trend_score", 0)
            adjusted = sc + raw_trend * 1.5
            proximity = 1.0 - (dist / (z.get("radius_meters", 500) * 1.5))
            val = adjusted * proximity
            if val > best_score:
                best_score = val
                best_status = ts
    return round(min(10.0, best_score), 2), best_status


def _score_forecast(clat, clng, zones, forecast_data):
    """Signal 3: Forecast risk (0-10)"""
    best_score, best_cat = 0.0, "stable"
    for z in zones:
        dist = _haversine(clat, clng, z["lat"], z["lng"])
        if dist <= z.get("radius_meters", 500) * 1.5:
            fd = forecast_data.get(z["zone_id"], {})
            pred = fd.get("predicted_48h", z["risk_score"])
            cat = fd.get("forecast_category", "stable")
            proximity = 1.0 - (dist / (z.get("radius_meters", 500) * 1.5))
            val = pred * proximity
            if val > best_score:
                best_score = val
                best_cat = cat
    return round(min(10.0, best_score), 2), best_cat


def _score_activity(clat, clng, incidents):
    """Signal 4: Activity spike (0-10)"""
    cell_radius = GRID_CELL_SIZE_M * 2
    nearby = [i for i in incidents
              if abs(i["lat"] - clat) < 0.005 and abs(i["lng"] - clng) < 0.005
              and _haversine(clat, clng, i["lat"], i["lng"]) <= cell_radius]
    if not nearby:
        return 0.0
    density = min(1.0, len(nearby) / 12.0)
    type_weight = sum(ACTIVITY_W.get(i["incident_type"], 1.0) for i in nearby)
    severity = min(1.0, type_weight / 15.0)
    sev_weight = sum(SEVERITY_W.get(i["severity"], 1.0) for i in nearby)
    sev_score = min(1.0, sev_weight / 10.0)
    return round(min(10.0, density * 3.5 + severity * 3.5 + sev_score * 3.0), 2)


def _score_patrol(clat, clng, zones, forecast_data):
    """Signal 5: Patrol priority (0-10)"""
    best = 0.0
    for z in zones:
        dist = _haversine(clat, clng, z["lat"], z["lng"])
        if dist <= z.get("radius_meters", 500) * 1.5:
            fd = forecast_data.get(z["zone_id"], {})
            pred = fd.get("predicted_48h", z["risk_score"])
            patrol_urgency = z["risk_score"] * 0.4 + pred * 0.6
            proximity = 1.0 - (dist / (z.get("radius_meters", 500) * 1.5))
            val = patrol_urgency * proximity
            if val > best:
                best = val
    return round(min(10.0, best), 2)


def _score_environment(hour: int) -> float:
    """Signal 6: Environmental risk — darkness/visibility (0-10)"""
    if 6 <= hour < 18:
        return 1.5   # Daylight — safe
    elif 18 <= hour < 21:
        return 4.5   # Dusk/evening
    elif 21 <= hour < 24:
        return 7.0   # Dark
    return 8.5        # Late night — highest env risk


def _score_session_density(clat, clng, sessions: list[dict]) -> float:
    """Signal 7: Active session density as foot-traffic proxy (0-10)
    Higher session density = more eyes on street = slightly safer,
    BUT absence when expected = danger signal.
    For scoring: inverse — low density in normally-active area = higher risk.
    """
    cell_radius = GRID_CELL_SIZE_M * 3
    nearby = [s for s in sessions
              if abs(s["lat"] - clat) < 0.008 and abs(s["lng"] - clng) < 0.008
              and _haversine(clat, clng, s["lat"], s["lng"]) <= cell_radius]
    if not sessions:
        return 3.0  # No session data — neutral
    if not nearby:
        return 5.0  # No activity nearby when sessions exist elsewhere — mild concern
    # More sessions nearby = safer (inverse signal)
    density = len(nearby) / max(len(sessions), 1)
    return round(max(0.0, 5.0 - density * 8.0), 2)


def _score_mobility_anomaly(clat, clng, sessions: list[dict], incidents: list[dict]) -> float:
    """Signal 8: Mobility anomaly — sudden avoidance of an area (0-10)
    If an area has historical incidents but zero current sessions,
    people may be avoiding it, signaling danger.
    """
    cell_radius = GRID_CELL_SIZE_M * 2
    nearby_incidents = sum(1 for i in incidents
                          if abs(i["lat"] - clat) < 0.005 and abs(i["lng"] - clng) < 0.005
                          and _haversine(clat, clng, i["lat"], i["lng"]) <= cell_radius)
    nearby_sessions = sum(1 for s in sessions
                          if abs(s["lat"] - clat) < 0.008 and abs(s["lng"] - clng) < 0.008
                          and _haversine(clat, clng, s["lat"], s["lng"]) <= cell_radius * 1.5)

    if nearby_incidents == 0:
        return 0.0  # No historical danger — no anomaly
    if nearby_sessions == 0 and nearby_incidents >= 3:
        return 8.0  # Known danger zone with zero activity — strong anomaly
    if nearby_sessions == 0 and nearby_incidents >= 1:
        return 5.0  # Some danger, no activity
    # Activity present — reduced anomaly
    ratio = nearby_incidents / max(nearby_sessions, 1)
    return round(min(10.0, ratio * 2.5), 2)


# ── Incident Velocity (spike detection for activity signal boost) ──

def _compute_incident_velocity(incidents: list[dict]) -> float:
    """Detect if incidents are occurring faster than baseline.
    Returns a multiplier (1.0 = normal, up to 2.0 for spikes)."""
    if len(incidents) < 3:
        return 1.0
    now = datetime.now(timezone.utc)
    recent_24h = [i for i in incidents if (now - i["created_at"]).total_seconds() < 86400]
    older = [i for i in incidents if (now - i["created_at"]).total_seconds() >= 86400]
    if not older:
        return 1.2
    daily_baseline = len(older) / max((len(incidents) - len(recent_24h)) / 30, 1)
    if daily_baseline == 0:
        return 1.0
    velocity = len(recent_24h) / daily_baseline
    return min(2.0, max(1.0, velocity))


# ── Delta Computation ──

def compute_delta(prev_cells: list[dict], curr_cells: list[dict]) -> dict:
    """Compare two snapshots to detect risk changes."""
    prev_map = {c["grid_id"]: c for c in (prev_cells or [])}
    curr_map = {c["grid_id"]: c for c in (curr_cells or [])}

    escalated, de_escalated, new_hotspots, cooling = [], [], [], []

    for gid, cell in curr_map.items():
        prev = prev_map.get(gid)
        if not prev:
            if cell["risk_level"] in ("high", "critical"):
                new_hotspots.append({
                    "grid_id": gid, "lat": cell["lat"], "lng": cell["lng"],
                    "risk_level": cell["risk_level"], "score": cell["composite_score"],
                })
            continue
        curr_rank = RISK_RANK.get(cell["risk_level"], 0)
        prev_rank = RISK_RANK.get(prev["risk_level"], 0)
        if curr_rank > prev_rank:
            escalated.append({
                "grid_id": gid, "lat": cell["lat"], "lng": cell["lng"],
                "from": prev["risk_level"], "to": cell["risk_level"],
                "score_change": round(cell["composite_score"] - prev["composite_score"], 2),
            })
        elif curr_rank < prev_rank:
            de_escalated.append({
                "grid_id": gid, "lat": cell["lat"], "lng": cell["lng"],
                "from": prev["risk_level"], "to": cell["risk_level"],
                "score_change": round(cell["composite_score"] - prev["composite_score"], 2),
            })

    for gid, prev in prev_map.items():
        if gid not in curr_map and prev["risk_level"] in ("high", "critical"):
            cooling.append({
                "grid_id": gid, "lat": prev["lat"], "lng": prev["lng"],
                "was": prev["risk_level"],
            })

    return {
        "escalated": escalated, "de_escalated": de_escalated,
        "new_hotspots": new_hotspots, "cooling": cooling,
        "escalated_count": len(escalated), "de_escalated_count": len(de_escalated),
        "new_hotspot_count": len(new_hotspots), "cooling_count": len(cooling),
        "net_change": len(escalated) - len(de_escalated),
    }


# ── Main Pipeline ──

async def compute_city_risk_snapshot(session: AsyncSession, city_id: str = "default") -> dict:
    """
    Full risk pipeline: aggregate signals → score grid → snapshot → cache → delta.
    Called every 5 minutes by the dynamic risk scheduler.
    """
    start_ms = _time.time()
    now = datetime.now(timezone.utc)
    hour = now.hour

    # Phase 1: Signal Aggregation — fetch all data sources
    zones = await _fetch_zones(session)
    if not zones:
        empty = {
            "cells": [], "bounds": None, "grid_size_m": GRID_CELL_SIZE_M,
            "total_cells": 0, "total_zones": 0, "total_incidents_analyzed": 0,
            "analyzed_at": now.isoformat(), "city_id": city_id,
            "weight_profile": "day", "weights": WEIGHT_PROFILES["day"],
            "stats": {"critical": 0, "high": 0, "moderate": 0, "safe": 0},
            "delta": compute_delta([], []),
            "computation_time_ms": 0, "snapshot_number": 0,
        }
        _get_cache(city_id)["current"] = empty
        return empty

    incidents = await _fetch_incidents(session, days=30)
    active_sessions = await _fetch_active_sessions(session)

    # Precompute forecast + trend data per zone
    from app.services.risk_forecast_engine import _compute_zone_forecast, _fetch_all_incidents as fetch_forecast_incidents
    from app.services.hotspot_trend_engine import _compute_zone_trend, _fetch_all_incidents as fetch_trend_incidents

    forecast_incidents = await fetch_forecast_incidents(session, timedelta(days=14))
    trend_incidents = await fetch_trend_incidents(session, timedelta(days=60))

    forecast_data, trend_data = {}, {}
    for z in zones:
        forecast_data[z["zone_id"]] = _compute_zone_forecast(z, forecast_incidents, now)
        trend_data[z["zone_id"]] = _compute_zone_trend(z, trend_incidents, now)

    # Incident velocity multiplier
    velocity_mult = _compute_incident_velocity(incidents)

    # Phase 2: Adaptive Weight Selection
    profile_name, weights = _get_weight_profile(hour)
    env_score_global = _score_environment(hour)

    # Phase 3: Grid Scoring
    grid_cells = _build_grid(zones, incidents)
    logger.info(f"Dynamic Risk [{city_id}]: Scoring {len(grid_cells)} cells, {len(zones)} zones, {len(incidents)} incidents, {len(active_sessions)} sessions")

    scored_cells = []
    for cell in grid_cells:
        clat, clng = cell["lat"], cell["lng"]

        hotspot = _score_hotspot(clat, clng, zones)
        trend, trend_status = _score_trend(clat, clng, zones, trend_data)
        forecast, forecast_cat = _score_forecast(clat, clng, zones, forecast_data)
        activity = _score_activity(clat, clng, incidents)
        patrol = _score_patrol(clat, clng, zones, forecast_data)
        session_density = _score_session_density(clat, clng, active_sessions)
        mobility = _score_mobility_anomaly(clat, clng, active_sessions, incidents)

        # Apply incident velocity boost to activity
        activity = round(min(10.0, activity * velocity_mult), 2)

        # Weighted composite using adaptive profile
        composite = round(
            weights["forecast"] * forecast +
            weights["hotspot"] * hotspot +
            weights["trend"] * trend +
            weights["activity"] * activity +
            weights["patrol"] * patrol +
            weights["environment"] * env_score_global +
            weights["session_density"] * session_density +
            weights["mobility_anomaly"] * mobility, 2
        )

        if composite < 0.1:
            continue

        scored_cells.append({
            "grid_id": cell["grid_id"],
            "lat": clat, "lng": clng,
            "composite_score": composite,
            "risk_level": _classify_risk(composite),
            "hotspot": hotspot, "trend": trend, "trend_status": trend_status,
            "forecast": forecast, "forecast_category": forecast_cat,
            "activity": activity, "patrol": patrol,
            "environment": round(env_score_global, 2),
            "session_density": session_density,
            "mobility_anomaly": mobility,
        })

    scored_cells.sort(key=lambda c: c["composite_score"], reverse=True)

    # Bounds
    bounds = None
    if scored_cells:
        lats = [c["lat"] for c in scored_cells]
        lngs = [c["lng"] for c in scored_cells]
        bounds = {"min_lat": min(lats), "max_lat": max(lats), "min_lng": min(lngs), "max_lng": max(lngs)}

    # Stats
    stats = defaultdict(int)
    for c in scored_cells:
        stats[c["risk_level"]] += 1

    signal_sums = defaultdict(float)
    for c in scored_cells:
        for sig in ("forecast", "hotspot", "trend", "activity", "patrol", "environment", "session_density", "mobility_anomaly"):
            signal_sums[sig] += c.get(sig, 0)
    dominant = max(signal_sums, key=signal_sums.get) if signal_sums else "none"

    # Phase 4: Delta Computation
    cache = _get_cache(city_id)
    prev_cells = cache["current"]["cells"] if cache["current"] else []
    delta = compute_delta(prev_cells, scored_cells)

    comp_ms = int((_time.time() - start_ms) * 1000)
    new_count = cache["count"] + 1

    result = {
        "cells": scored_cells, "bounds": bounds,
        "grid_size_m": GRID_CELL_SIZE_M,
        "total_cells": len(scored_cells),
        "total_grid_generated": len(grid_cells),
        "total_zones": len(zones),
        "total_incidents_analyzed": len(incidents),
        "active_sessions": len(active_sessions),
        "incident_velocity": round(velocity_mult, 2),
        "analyzed_at": now.isoformat(),
        "city_id": city_id,
        "weight_profile": profile_name,
        "weights": weights,
        "stats": {
            "critical": stats.get("critical", 0),
            "high": stats.get("high", 0),
            "moderate": stats.get("moderate", 0),
            "safe": stats.get("safe", 0),
            "dominant_signal": dominant,
            "forecast_p1_cells": sum(1 for c in scored_cells if c["forecast_category"] == "escalating"),
        },
        "delta": delta,
        "computation_time_ms": comp_ms,
        "snapshot_number": new_count,
    }

    # Phase 5: Cache Update (Redis primary, in-memory fallback)
    timeline = cache["timeline"].copy() if cache["timeline"] else []
    timeline_entry = {
        "snapshot_number": new_count,
        "analyzed_at": now.isoformat(),
        "total_cells": len(scored_cells),
        "stats": dict(stats),
        "delta_summary": {
            "escalated": delta["escalated_count"],
            "de_escalated": delta["de_escalated_count"],
            "new_hotspots": delta["new_hotspot_count"],
        },
        "weight_profile": profile_name,
        "computation_time_ms": comp_ms,
    }
    timeline.append(timeline_entry)
    if len(timeline) > TIMELINE_MAX:
        timeline = timeline[-TIMELINE_MAX:]

    _update_cache(city_id, result, delta, timeline, new_count, now)

    # Phase 6: Persist Snapshot to DB
    try:
        await _store_snapshot(session, city_id, now, result)
    except Exception as e:
        logger.warning(f"Snapshot storage failed (non-critical): {e}")

    logger.info(
        f"Dynamic Risk [{city_id}]: {len(scored_cells)} cells scored in {comp_ms}ms "
        f"(critical={stats.get('critical', 0)}, high={stats.get('high', 0)}, "
        f"escalated={delta['escalated_count']}, de-escalated={delta['de_escalated_count']})"
    )

    return result


async def _store_snapshot(session: AsyncSession, city_id: str, ts: datetime, data: dict):
    """Persist snapshot to city_risk_snapshots table for timeline/analytics."""
    from app.models.city_risk_snapshot import CityRiskSnapshot
    snapshot = CityRiskSnapshot(
        city_id=city_id,
        snapshot_timestamp=ts,
        total_cells=data["total_cells"],
        total_zones=data["total_zones"],
        total_incidents=data["total_incidents_analyzed"],
        stats=data["stats"],
        cells=data["cells"],
        delta=data["delta"],
        weights=data["weights"],
        weight_profile=data["weight_profile"],
        bounds=data["bounds"],
        computation_time_ms=data["computation_time_ms"],
    )
    session.add(snapshot)
    await session.commit()

    # Prune old snapshots (keep last 288 = 24 hours at 5-min intervals)
    cutoff = ts - timedelta(hours=24)
    await session.execute(text(
        "DELETE FROM city_risk_snapshots WHERE city_id = :cid AND snapshot_timestamp < :cutoff"
    ), {"cid": city_id, "cutoff": cutoff})
    await session.commit()


# ── Cache Access Functions (for API layer) ──
# Redis primary, in-memory fallback for all read operations.

def get_live_heatmap(city_id: str = "default") -> dict | None:
    """Return pre-computed heatmap. Redis first, then in-memory fallback."""
    from app.services.redis_service import get_heatmap_live
    try:
        cached = get_heatmap_live()
        if cached:
            return cached
    except Exception:
        pass
    # Fallback to in-memory
    mem = _risk_cache.get(city_id, {})
    return mem.get("current")


def get_heatmap_delta(city_id: str = "default") -> dict | None:
    """Return latest delta. Redis first, then in-memory fallback."""
    from app.services.redis_service import get_heatmap_delta as redis_get_delta
    try:
        cached = redis_get_delta()
        if cached:
            return cached
    except Exception:
        pass
    mem = _risk_cache.get(city_id, {})
    return mem.get("delta")


def get_heatmap_timeline(city_id: str = "default") -> list[dict]:
    """Return last 12 snapshots. Redis first, then in-memory fallback."""
    from app.services.redis_service import get_heatmap_timeline as redis_get_tl
    try:
        cached = redis_get_tl()
        if cached:
            return cached
    except Exception:
        pass
    mem = _risk_cache.get(city_id, {})
    return mem.get("timeline", [])


def get_cache_status(city_id: str = "default") -> dict:
    """Return cache metadata with Redis status."""
    from app.services.redis_service import get_heatmap_meta, is_available

    redis_up = is_available()
    meta = get_heatmap_meta() if redis_up else None

    if meta:
        return {
            "has_data": True,
            "computed_at": meta.get("computed_at"),
            "snapshot_count": meta.get("count", 0),
            "timeline_length": len(get_heatmap_timeline(city_id)),
            "cache_backend": "redis",
        }

    # Fallback to in-memory
    mem = _risk_cache.get(city_id, {})
    return {
        "has_data": mem.get("current") is not None,
        "computed_at": mem.get("computed_at").isoformat() if mem.get("computed_at") else None,
        "snapshot_count": mem.get("count", 0),
        "timeline_length": len(mem.get("timeline", [])),
        "cache_backend": "memory" if not redis_up else "redis",
    }


async def get_db_timeline(session: AsyncSession, city_id: str = "default", limit: int = 12) -> list[dict]:
    """Fetch timeline from DB (for when cache is cold)."""
    rows = (await session.execute(text("""
        SELECT id, snapshot_timestamp, total_cells, total_zones, total_incidents,
               stats, delta, weight_profile, computation_time_ms
        FROM city_risk_snapshots
        WHERE city_id = :cid
        ORDER BY snapshot_timestamp DESC
        LIMIT :lim
    """), {"cid": city_id, "lim": limit})).fetchall()

    return [{
        "snapshot_id": str(r.id),
        "analyzed_at": r.snapshot_timestamp.isoformat(),
        "total_cells": r.total_cells,
        "stats": r.stats,
        "delta_summary": {
            "escalated": (r.delta or {}).get("escalated_count", 0),
            "de_escalated": (r.delta or {}).get("de_escalated_count", 0),
            "new_hotspots": (r.delta or {}).get("new_hotspot_count", 0),
        },
        "weight_profile": r.weight_profile,
        "computation_time_ms": r.computation_time_ms,
    } for r in rows]


# ── Backward Compatibility ──

async def generate_city_heatmap(session: AsyncSession) -> dict:
    """Legacy function — now delegates to the dynamic pipeline."""
    return await compute_city_risk_snapshot(session)


async def get_heatmap_stats(session: AsyncSession) -> dict:
    """Lightweight heatmap summary."""
    cache = _get_cache("default")
    if cache["current"]:
        data = cache["current"]
        return {
            "total_zones": data["total_zones"],
            "critical_zones": data["stats"].get("critical", 0),
            "high_risk_zones": data["stats"].get("high", 0),
            "recent_incidents_7d": data["total_incidents_analyzed"],
            "analyzed_at": data["analyzed_at"],
            "live": True,
            "snapshot_number": data.get("snapshot_number", 0),
        }

    # Fallback to DB query
    zones = await _fetch_zones(session)
    incidents = await _fetch_incidents(session, days=7)
    return {
        "total_zones": len(zones),
        "critical_zones": sum(1 for z in zones if z["risk_score"] >= RISK_CRITICAL),
        "high_risk_zones": sum(1 for z in zones if RISK_HIGH <= z["risk_score"] < RISK_CRITICAL),
        "recent_incidents_7d": len(incidents),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "live": False,
    }


async def get_cell_detail(session: AsyncSession, grid_id: str, cells_cache=None) -> dict | None:
    """Get detailed breakdown for a specific grid cell."""
    cache = _get_cache("default")
    cells = cells_cache or (cache["current"]["cells"] if cache["current"] else None)
    if cells:
        cell = next((c for c in cells if c["grid_id"] == grid_id), None)
        if cell:
            return _build_cell_detail(cell)

    heatmap = await compute_city_risk_snapshot(session)
    cell = next((c for c in heatmap["cells"] if c["grid_id"] == grid_id), None)
    if not cell:
        return None
    return _build_cell_detail(cell)


def _build_cell_detail(cell: dict) -> dict:
    """Build detailed cell response with all 8 signals."""
    profile_name, weights = _get_weight_profile(datetime.now(timezone.utc).hour)
    signals = [
        {"name": "Forecast Risk", "key": "forecast", "score": cell["forecast"],
         "weight": weights["forecast"], "weighted": round(weights["forecast"] * cell["forecast"], 2),
         "category": cell.get("forecast_category", "stable")},
        {"name": "Hotspot Density", "key": "hotspot", "score": cell["hotspot"],
         "weight": weights["hotspot"], "weighted": round(weights["hotspot"] * cell["hotspot"], 2)},
        {"name": "Trend Growth", "key": "trend", "score": cell["trend"],
         "weight": weights["trend"], "weighted": round(weights["trend"] * cell["trend"], 2),
         "status": cell.get("trend_status", "stable")},
        {"name": "Activity Spike", "key": "activity", "score": cell["activity"],
         "weight": weights["activity"], "weighted": round(weights["activity"] * cell["activity"], 2)},
        {"name": "Patrol Priority", "key": "patrol", "score": cell["patrol"],
         "weight": weights["patrol"], "weighted": round(weights["patrol"] * cell["patrol"], 2)},
        {"name": "Environment", "key": "environment", "score": cell.get("environment", 0),
         "weight": weights["environment"], "weighted": round(weights["environment"] * cell.get("environment", 0), 2)},
        {"name": "Session Density", "key": "session_density", "score": cell.get("session_density", 0),
         "weight": weights["session_density"], "weighted": round(weights["session_density"] * cell.get("session_density", 0), 2)},
        {"name": "Mobility Anomaly", "key": "mobility_anomaly", "score": cell.get("mobility_anomaly", 0),
         "weight": weights["mobility_anomaly"], "weighted": round(weights["mobility_anomaly"] * cell.get("mobility_anomaly", 0), 2)},
    ]
    signal_scores = {s["name"]: s["score"] for s in signals}
    dominant = max(signal_scores, key=signal_scores.get)

    recs = []
    if cell["forecast"] >= 7:
        recs.append("Increase patrol — forecast risk escalating")
    if cell["trend"] >= 6:
        recs.append("Monitor trend growth — hotspot expanding")
    if cell["activity"] >= 5:
        recs.append("High activity risk — consider crowd management")
    if cell["hotspot"] >= 7:
        recs.append("Dense hotspot zone — prioritize in routing")
    if cell.get("mobility_anomaly", 0) >= 6:
        recs.append("Mobility anomaly detected — people avoiding area")
    if cell.get("environment", 0) >= 6:
        recs.append("Low visibility environment — increased caution advised")
    if not recs:
        recs.append("Standard monitoring recommended")

    return {
        "grid_id": cell["grid_id"], "lat": cell["lat"], "lng": cell["lng"],
        "composite_score": cell["composite_score"],
        "risk_level": cell["risk_level"],
        "signals": signals, "dominant_signal": dominant,
        "weight_profile": profile_name, "recommendations": recs,
    }
