# City-Scale Safety Heatmap Engine
# Aggregates all AI signals into a unified grid-based city safety heatmap.
# Grid cells (250m x 250m) store composite scores from 5 signal layers.

import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Composite Score Weights ──
W_FORECAST = 0.30
W_HOTSPOT = 0.25
W_TREND = 0.20
W_ACTIVITY = 0.15
W_PATROL = 0.10

# ── Grid Configuration ──
GRID_CELL_SIZE_M = 250  # meters per cell
GRID_PADDING_M = 500    # padding beyond zone bounds

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


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _meters_to_deg_lat(meters):
    """Convert meters to approximate degrees latitude."""
    return meters / 111_320.0


def _meters_to_deg_lng(meters, lat):
    """Convert meters to approximate degrees longitude at given latitude."""
    return meters / (111_320.0 * math.cos(math.radians(lat)))


async def _fetch_zones(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT id, zone_name, latitude, longitude, radius_meters,
               risk_score, risk_level, incident_count, factors
        FROM location_risk_zones
        WHERE risk_type = 'learned_hotspot'
        ORDER BY risk_score DESC
    """))).fetchall()

    import json
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
            "zone_id": str(z.id),
            "zone_name": z.zone_name,
            "lat": float(z.latitude),
            "lng": float(z.longitude),
            "radius_meters": float(z.radius_meters),
            "risk_score": float(z.risk_score),
            "risk_level": z.risk_level,
            "incident_count": z.incident_count,
            "trend_meta": trend_meta,
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


def _build_grid(zones: list[dict], incidents: list[dict]) -> list[dict]:
    """Generate grid cells covering the city bounding box."""
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
                "row": row,
                "col": col,
            })
            lng += step_lng
            col += 1
        lat += step_lat
        row += 1

    return cells


def _score_cell_hotspot(cell_lat, cell_lng, zones: list[dict]) -> float:
    """Hotspot density score (0-10): proximity-weighted influence from known hotspots."""
    if not zones:
        return 0.0
    influence = 0.0
    for z in zones:
        dist = _haversine(cell_lat, cell_lng, z["lat"], z["lng"])
        radius = z.get("radius_meters", 500) * 1.5
        if dist <= radius:
            proximity = 1.0 - (dist / radius)
            influence += z["risk_score"] * proximity
    return round(min(10.0, influence), 2)


def _score_cell_trend(cell_lat, cell_lng, zones: list[dict], trend_data: dict) -> tuple[float, str]:
    """Trend risk score (0-10): based on nearby zone trend statuses."""
    status_score = {"growing": 8.0, "emerging": 5.5, "stable": 3.0, "declining": 1.5, "dormant": 0.5}
    best_score = 0.0
    best_status = "stable"
    for z in zones:
        dist = _haversine(cell_lat, cell_lng, z["lat"], z["lng"])
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


def _score_cell_forecast(cell_lat, cell_lng, zones: list[dict], forecast_data: dict) -> tuple[float, str]:
    """Forecast risk score (0-10): predicted 48h risk from nearby zones."""
    best_score = 0.0
    best_cat = "stable"
    for z in zones:
        dist = _haversine(cell_lat, cell_lng, z["lat"], z["lng"])
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


def _score_cell_activity(cell_lat, cell_lng, incidents: list[dict]) -> float:
    """Activity risk score (0-10): incident density and severity in cell vicinity."""
    cell_radius = GRID_CELL_SIZE_M * 2
    nearby = [i for i in incidents
              if abs(i["lat"] - cell_lat) < 0.005 and abs(i["lng"] - cell_lng) < 0.005
              and _haversine(cell_lat, cell_lng, i["lat"], i["lng"]) <= cell_radius]
    if not nearby:
        return 0.0

    density = min(1.0, len(nearby) / 12.0)
    type_weight = sum(ACTIVITY_W.get(i["incident_type"], 1.0) for i in nearby)
    severity = min(1.0, type_weight / 15.0)
    sev_weight = sum(SEVERITY_W.get(i["severity"], 1.0) for i in nearby)
    sev_score = min(1.0, sev_weight / 10.0)

    raw = density * 3.5 + severity * 3.5 + sev_score * 3.0
    return round(min(10.0, raw), 2)


def _score_cell_patrol(cell_lat, cell_lng, zones: list[dict], forecast_data: dict) -> float:
    """Patrol priority score (0-10): composite urgency from zone risk + forecast."""
    best = 0.0
    for z in zones:
        dist = _haversine(cell_lat, cell_lng, z["lat"], z["lng"])
        if dist <= z.get("radius_meters", 500) * 1.5:
            fd = forecast_data.get(z["zone_id"], {})
            pred = fd.get("predicted_48h", z["risk_score"])
            base = z["risk_score"]
            patrol_urgency = (base * 0.4 + pred * 0.6)
            proximity = 1.0 - (dist / (z.get("radius_meters", 500) * 1.5))
            val = patrol_urgency * proximity
            if val > best:
                best = val
    return round(min(10.0, best), 2)


def _classify_risk(score: float) -> str:
    if score >= RISK_CRITICAL:
        return "critical"
    if score >= RISK_HIGH:
        return "high"
    if score >= RISK_MODERATE:
        return "moderate"
    return "safe"


async def generate_city_heatmap(session: AsyncSession) -> dict:
    """
    Generate city-scale safety heatmap with grid cells.
    Each cell stores scores from 5 AI signal layers + composite score.
    """
    now = datetime.now(timezone.utc)

    # Batch fetch all data (3 DB queries total)
    zones = await _fetch_zones(session)
    if not zones:
        return {
            "cells": [],
            "bounds": None,
            "grid_size_m": GRID_CELL_SIZE_M,
            "total_cells": 0,
            "analyzed_at": now.isoformat(),
            "stats": {"critical": 0, "high": 0, "moderate": 0, "safe": 0},
        }

    incidents = await _fetch_incidents(session, days=30)

    # Pre-compute forecast and trend data per zone (in-memory, no extra DB calls)
    from app.services.risk_forecast_engine import _compute_zone_forecast, _fetch_all_incidents as fetch_forecast_incidents
    from app.services.hotspot_trend_engine import _compute_zone_trend, _fetch_all_incidents as fetch_trend_incidents

    forecast_incidents = await fetch_forecast_incidents(session, timedelta(days=14))
    trend_incidents = await fetch_trend_incidents(session, timedelta(days=60))

    forecast_data = {}
    trend_data = {}
    for z in zones:
        forecast_data[z["zone_id"]] = _compute_zone_forecast(z, forecast_incidents, now)
        trend_data[z["zone_id"]] = _compute_zone_trend(z, trend_incidents, now)

    # Build grid
    grid_cells = _build_grid(zones, incidents)
    logger.info(f"City heatmap: {len(grid_cells)} grid cells generated")

    # Score each cell
    scored_cells = []
    for cell in grid_cells:
        clat, clng = cell["lat"], cell["lng"]

        hotspot = _score_cell_hotspot(clat, clng, zones)
        trend, trend_status = _score_cell_trend(clat, clng, zones, trend_data)
        forecast, forecast_cat = _score_cell_forecast(clat, clng, zones, forecast_data)
        activity = _score_cell_activity(clat, clng, incidents)
        patrol = _score_cell_patrol(clat, clng, zones, forecast_data)

        composite = round(
            W_FORECAST * forecast +
            W_HOTSPOT * hotspot +
            W_TREND * trend +
            W_ACTIVITY * activity +
            W_PATROL * patrol, 2
        )

        # Skip cells with zero signal (optimization: reduce payload)
        if composite < 0.1:
            continue

        risk_level = _classify_risk(composite)

        scored_cells.append({
            "grid_id": cell["grid_id"],
            "lat": clat,
            "lng": clng,
            "composite_score": composite,
            "risk_level": risk_level,
            "hotspot": hotspot,
            "trend": trend,
            "trend_status": trend_status,
            "forecast": forecast,
            "forecast_category": forecast_cat,
            "activity": activity,
            "patrol": patrol,
        })

    # Sort by composite score descending
    scored_cells.sort(key=lambda c: c["composite_score"], reverse=True)

    # Compute bounds
    if scored_cells:
        lats = [c["lat"] for c in scored_cells]
        lngs = [c["lng"] for c in scored_cells]
        bounds = {
            "min_lat": min(lats), "max_lat": max(lats),
            "min_lng": min(lngs), "max_lng": max(lngs),
        }
    else:
        bounds = None

    # Stats
    stats = defaultdict(int)
    for c in scored_cells:
        stats[c["risk_level"]] += 1

    # Dominant signal analysis
    signal_sums = {"forecast": 0, "hotspot": 0, "trend": 0, "activity": 0, "patrol": 0}
    for c in scored_cells:
        signal_sums["forecast"] += c["forecast"]
        signal_sums["hotspot"] += c["hotspot"]
        signal_sums["trend"] += c["trend"]
        signal_sums["activity"] += c["activity"]
        signal_sums["patrol"] += c["patrol"]
    dominant_signal = max(signal_sums, key=signal_sums.get) if signal_sums else "none"

    # Forecast P1 cells
    forecast_p1 = sum(1 for c in scored_cells if c["forecast_category"] == "escalating")

    return {
        "cells": scored_cells,
        "bounds": bounds,
        "grid_size_m": GRID_CELL_SIZE_M,
        "total_cells": len(scored_cells),
        "total_grid_generated": len(grid_cells),
        "total_zones": len(zones),
        "total_incidents_analyzed": len(incidents),
        "analyzed_at": now.isoformat(),
        "weights": {
            "forecast": W_FORECAST, "hotspot": W_HOTSPOT, "trend": W_TREND,
            "activity": W_ACTIVITY, "patrol": W_PATROL,
        },
        "stats": {
            "critical": stats.get("critical", 0),
            "high": stats.get("high", 0),
            "moderate": stats.get("moderate", 0),
            "safe": stats.get("safe", 0),
            "dominant_signal": dominant_signal,
            "forecast_p1_cells": forecast_p1,
        },
    }


async def get_heatmap_stats(session: AsyncSession) -> dict:
    """Lightweight heatmap summary (for Command Center widget)."""
    now = datetime.now(timezone.utc)
    zones = await _fetch_zones(session)
    incidents = await _fetch_incidents(session, days=7)

    critical = sum(1 for z in zones if z["risk_score"] >= RISK_CRITICAL)
    high = sum(1 for z in zones if RISK_HIGH <= z["risk_score"] < RISK_CRITICAL)

    return {
        "total_zones": len(zones),
        "critical_zones": critical,
        "high_risk_zones": high,
        "recent_incidents_7d": len(incidents),
        "analyzed_at": now.isoformat(),
    }


async def get_cell_detail(session: AsyncSession, grid_id: str, cells_cache: list[dict] = None) -> dict:
    """Get detailed breakdown for a specific grid cell."""
    if cells_cache:
        cell = next((c for c in cells_cache if c["grid_id"] == grid_id), None)
        if cell:
            return _build_cell_detail(cell)

    # If no cache, regenerate (expensive but rare)
    heatmap = await generate_city_heatmap(session)
    cell = next((c for c in heatmap["cells"] if c["grid_id"] == grid_id), None)
    if not cell:
        return None
    return _build_cell_detail(cell)


def _build_cell_detail(cell: dict) -> dict:
    """Build detailed cell response."""
    signals = [
        {"name": "Forecast Risk", "score": cell["forecast"], "weight": W_FORECAST,
         "weighted": round(W_FORECAST * cell["forecast"], 2), "category": cell.get("forecast_category", "stable")},
        {"name": "Hotspot Density", "score": cell["hotspot"], "weight": W_HOTSPOT,
         "weighted": round(W_HOTSPOT * cell["hotspot"], 2)},
        {"name": "Trend Growth", "score": cell["trend"], "weight": W_TREND,
         "weighted": round(W_TREND * cell["trend"], 2), "status": cell.get("trend_status", "stable")},
        {"name": "Activity Spike", "score": cell["activity"], "weight": W_ACTIVITY,
         "weighted": round(W_ACTIVITY * cell["activity"], 2)},
        {"name": "Patrol Priority", "score": cell["patrol"], "weight": W_PATROL,
         "weighted": round(W_PATROL * cell["patrol"], 2)},
    ]

    # Dominant signal for this cell
    signal_scores = {s["name"]: s["score"] for s in signals}
    dominant = max(signal_scores, key=signal_scores.get)

    # Recommendations
    recs = []
    if cell["forecast"] >= 7:
        recs.append("Increase patrol frequency — forecast risk escalating")
    if cell["trend"] >= 6:
        recs.append("Monitor trend growth — hotspot activity increasing")
    if cell["activity"] >= 5:
        recs.append("High activity risk — consider crowd management")
    if cell["hotspot"] >= 7:
        recs.append("Dense hotspot zone — prioritize in patrol routing")
    if not recs:
        recs.append("Standard monitoring recommended")

    return {
        "grid_id": cell["grid_id"],
        "lat": cell["lat"],
        "lng": cell["lng"],
        "composite_score": cell["composite_score"],
        "risk_level": cell["risk_level"],
        "signals": signals,
        "dominant_signal": dominant,
        "recommendations": recs,
    }
