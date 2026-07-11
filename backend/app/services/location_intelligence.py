# Location Intelligence Engine
#
# Grid-based spatial danger scoring for the 3-Layer Safety Brain.
# Divides the map into 100m × 100m cells and scores each based on:
#   - incident_density (50%) — count of past incidents in/near cell
#   - night_time_weight (30%) — higher risk at night
#   - recent_incident_boost (20%) — recency-weighted incidents
#
# Feeds location_risk signal into the Risk Fusion Engine.

import math
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Grid resolution: ~100m at equator
GRID_SIZE_DEG = 0.001  # ~111m latitude, ~85-111m longitude depending on latitude
INCIDENT_RADIUS_CELLS = 2  # Look at 2 cells in each direction (5×5 area)
RECENCY_DECAY_DAYS = 7  # Recent incidents within 7 days get boosted

# Time-of-day risk factors (0=midnight, 23=11pm)
HOUR_RISK = {
    0: 0.90, 1: 0.95, 2: 0.95, 3: 0.90, 4: 0.80, 5: 0.50,
    6: 0.30, 7: 0.20, 8: 0.15, 9: 0.10, 10: 0.10, 11: 0.10,
    12: 0.15, 13: 0.15, 14: 0.15, 15: 0.20, 16: 0.20, 17: 0.30,
    18: 0.40, 19: 0.55, 20: 0.65, 21: 0.75, 22: 0.80, 23: 0.85,
}


def _to_grid(lat: float, lng: float) -> tuple[int, int]:
    """Convert lat/lng to grid cell coordinates."""
    return (int(lat / GRID_SIZE_DEG), int(lng / GRID_SIZE_DEG))


def _grid_distance(c1: tuple, c2: tuple) -> float:
    """Manhattan distance between grid cells."""
    return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])


async def _fetch_all_incidents(session: AsyncSession, hours: int = 720) -> list[dict]:
    """Fetch incidents from last N hours (default 30 days) for grid scoring."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    incidents = []

    queries = [
        ("safety_events", "location_lat", "location_lng", "risk_score", "created_at"),
        ("fall_events", "lat", "lng", "confidence", "created_at"),
        ("voice_distress_events", "lat", "lng", "distress_score", "created_at"),
        ("wandering_events", "lat", "lng", "wander_score", "created_at"),
    ]

    for table, lat_col, lng_col, score_col, time_col in queries:
        try:
            result = await session.execute(
                text(f"SELECT {lat_col}, {lng_col}, {score_col}, {time_col} FROM {table} WHERE {time_col} > :cutoff LIMIT 500"),
                {"cutoff": cutoff},
            )
            for row in result.mappings():
                lat_val = row[lat_col]
                lng_val = row[lng_col]
                if lat_val and lng_val:
                    incidents.append({
                        "lat": float(lat_val), "lng": float(lng_val),
                        "score": float(row[score_col] or 0.5),
                        "created_at": row[time_col],
                        "grid": _to_grid(float(lat_val), float(lng_val)),
                    })
        except Exception as e:
            logger.debug(f"Location intelligence: skip {table}: {e}")

    return incidents


def _build_grid(incidents: list[dict]) -> dict[tuple, dict]:
    """Build the spatial grid from incident data."""
    grid = {}
    now = datetime.now(timezone.utc)

    for inc in incidents:
        cell = inc["grid"]
        if cell not in grid:
            grid[cell] = {"count": 0, "total_score": 0.0, "recent_count": 0, "recent_score": 0.0}

        grid[cell]["count"] += 1
        grid[cell]["total_score"] += inc["score"]

        # Recent boost (last 7 days)
        age = (now - inc["created_at"].replace(tzinfo=timezone.utc) if inc["created_at"].tzinfo is None else now - inc["created_at"]).total_seconds()
        if age < RECENCY_DECAY_DAYS * 86400:
            recency_factor = 1.0 - (age / (RECENCY_DECAY_DAYS * 86400))
            grid[cell]["recent_count"] += 1
            grid[cell]["recent_score"] += inc["score"] * recency_factor

    return grid


async def compute_location_risk(
    session: AsyncSession,
    lat: float,
    lng: float,
) -> dict:
    """
    Compute location danger score for a specific point.

    Returns: {score: 0-1, details: {...}}
    """
    incidents = await _fetch_all_incidents(session)
    grid = _build_grid(incidents)
    target_cell = _to_grid(lat, lng)
    now = datetime.now(timezone.utc)
    hour = now.hour

    # 1. Incident density (search 5×5 grid around target)
    nearby_count = 0
    nearby_score = 0.0
    for dx in range(-INCIDENT_RADIUS_CELLS, INCIDENT_RADIUS_CELLS + 1):
        for dy in range(-INCIDENT_RADIUS_CELLS, INCIDENT_RADIUS_CELLS + 1):
            neighbor = (target_cell[0] + dx, target_cell[1] + dy)
            if neighbor in grid:
                dist = abs(dx) + abs(dy)
                weight = 1.0 / (1.0 + dist * 0.5)  # Closer cells weigh more
                nearby_count += grid[neighbor]["count"]
                nearby_score += grid[neighbor]["total_score"] * weight

    # Normalize density (cap at 20 incidents = max density)
    max_incidents = 20
    incident_density = min(1.0, nearby_count / max_incidents)

    # 2. Night time weight
    night_risk = HOUR_RISK.get(hour, 0.5)

    # 3. Recent incident boost
    recent_count = 0
    recent_total = 0.0
    for dx in range(-INCIDENT_RADIUS_CELLS, INCIDENT_RADIUS_CELLS + 1):
        for dy in range(-INCIDENT_RADIUS_CELLS, INCIDENT_RADIUS_CELLS + 1):
            neighbor = (target_cell[0] + dx, target_cell[1] + dy)
            if neighbor in grid:
                recent_count += grid[neighbor]["recent_count"]
                recent_total += grid[neighbor]["recent_score"]
    recent_boost = min(1.0, recent_count / 5.0)  # Cap at 5 recent incidents

    # Composite score
    score = (
        incident_density * 0.50 +
        night_risk * 0.30 +
        recent_boost * 0.20
    )

    return {
        "score": round(min(1.0, max(0.0, score)), 3),
        "details": {
            "incident_density": round(incident_density, 3),
            "night_time_risk": round(night_risk, 3),
            "recent_incident_boost": round(recent_boost, 3),
            "nearby_incidents": nearby_count,
            "recent_incidents": recent_count,
            "hour": hour,
            "grid_cell": list(target_cell),
        },
    }


async def get_danger_heatmap(
    session: AsyncSession,
    bounds: dict | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    Generate heatmap data points for the frontend map overlay.
    Returns list of {lat, lng, intensity} for rendering.
    """
    incidents = await _fetch_all_incidents(session)
    grid = _build_grid(incidents)

    heatmap = []
    for cell, data in sorted(grid.items(), key=lambda x: x[1]["total_score"], reverse=True)[:limit]:
        lat_center = (cell[0] + 0.5) * GRID_SIZE_DEG
        lng_center = (cell[1] + 0.5) * GRID_SIZE_DEG

        if bounds:
            if lat_center < bounds.get("south", -90) or lat_center > bounds.get("north", 90):
                continue
            if lng_center < bounds.get("west", -180) or lng_center > bounds.get("east", 180):
                continue

        intensity = min(1.0, data["total_score"] / 5.0)
        heatmap.append({
            "lat": round(lat_center, 6),
            "lng": round(lng_center, 6),
            "intensity": round(intensity, 3),
            "count": data["count"],
            "recent": data["recent_count"],
        })

    return heatmap
