# AI Route Safety Engine
# Fetches candidate routes via OSRM, samples geometry points,
# evaluates safety per segment using PostGIS risk zones + incidents,
# and returns 3 options: shortest, safest, balanced.

import json
import math
import hashlib
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_M = 200  # metres between sampled points

# Time-of-day risk (0-1)
TIME_RISK = {
    0: 0.9, 1: 0.95, 2: 0.95, 3: 0.9, 4: 0.8, 5: 0.5,
    6: 0.3, 7: 0.2, 8: 0.15, 9: 0.1, 10: 0.1, 11: 0.1,
    12: 0.15, 13: 0.15, 14: 0.15, 15: 0.2, 16: 0.2, 17: 0.3,
    18: 0.4, 19: 0.55, 20: 0.65, 21: 0.75, 22: 0.8, 23: 0.85,
}

W_ZONE = 0.35
W_INCIDENT = 0.30
W_TIME = 0.20
W_ISOLATION = 0.15


async def evaluate_route_safety(
    session: AsyncSession,
    start_lat: float, start_lng: float,
    end_lat: float, end_lng: float,
) -> dict:
    """Evaluate safety for routes between two points."""
    now = datetime.now(timezone.utc)
    hour = now.hour

    # Check cache
    cache_key = _cache_key(start_lat, start_lng, end_lat, end_lng, hour)
    cached = await _get_cache(session, cache_key)
    if cached:
        return cached

    # Fetch routes from OSRM
    raw_routes = await _fetch_osrm_routes(start_lat, start_lng, end_lat, end_lng)
    if not raw_routes:
        return {"error": "Could not fetch routes from routing service"}

    # Ensure we have at least 3 route variants
    routes = _ensure_three_routes(raw_routes)

    # Fetch heatmap cells for route risk overlay
    heatmap_cells = await _fetch_heatmap_cells(session)

    # Score each route
    scored = []
    for i, route in enumerate(routes):
        coords = route["geometry"]["coordinates"]
        sampled = _sample_points(coords, SAMPLE_INTERVAL_M)
        segments = await _score_segments(session, sampled, hour)

        total_risk = sum(s["risk"] for s in segments) / max(len(segments), 1)
        dangerous = [s for s in segments if s["risk"] >= 5]
        moderate = [s for s in segments if 3 <= s["risk"] < 5]

        # Heatmap risk analysis for route
        heatmap_analysis = _analyze_route_heatmap(sampled, heatmap_cells)

        # Apply heatmap penalty to route risk
        heatmap_penalty = heatmap_analysis["heatmap_penalty"]
        adjusted_risk = round(min(10.0, total_risk + heatmap_penalty), 1)

        scored.append({
            "index": i,
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "distance_km": round(route["distance"] / 1000, 1),
            "duration_min": round(route["duration"] / 60, 1),
            "geometry": coords,
            "sampled_points": len(sampled),
            "route_risk_score": adjusted_risk,
            "base_risk_score": round(total_risk, 1),
            "heatmap_penalty": round(heatmap_penalty, 2),
            "risk_level": _risk_level(adjusted_risk),
            "dangerous_segments": len(dangerous),
            "moderate_segments": len(moderate),
            "segments": segments,
            "risk_reasons": _extract_reasons(segments),
            "heatmap_risk_zones": heatmap_analysis["risk_zones"],
            "heatmap_warnings": heatmap_analysis["warnings"],
            "heatmap_summary": heatmap_analysis["summary"],
        })

    # Label routes: shortest, safest, balanced
    by_dist = sorted(scored, key=lambda r: r["distance_m"])
    by_risk = sorted(scored, key=lambda r: r["route_risk_score"])

    shortest = by_dist[0]
    safest = by_risk[0]
    for r in scored:
        dist_rank = next(j for j, x in enumerate(by_dist) if x["index"] == r["index"])
        risk_rank = next(j for j, x in enumerate(by_risk) if x["index"] == r["index"])
        r["combined_rank"] = dist_rank + risk_rank

    by_balanced = sorted(scored, key=lambda r: r["combined_rank"])
    balanced = by_balanced[0]

    for r in scored:
        r["label"] = []
    shortest["label"].append("shortest")
    safest["label"].append("safest")
    balanced["label"].append("balanced")
    for r in scored:
        r["label"] = list(set(r["label"])) or ["alternate"]
    for r in scored:
        r.pop("combined_rank", None)

    result = {
        "start": {"lat": start_lat, "lng": start_lng},
        "end": {"lat": end_lat, "lng": end_lng},
        "routes": scored,
        "recommendation": safest["index"],
        "time_of_day_risk": TIME_RISK.get(hour, 0.5),
        "heatmap_integrated": len(heatmap_cells) > 0,
        "evaluated_at": now.isoformat(),
    }

    await _set_cache(session, cache_key, result)
    return result


def _risk_level(score):
    if score >= 7:
        return "Critical"
    if score >= 5:
        return "High"
    if score >= 3:
        return "Moderate"
    return "Low"


def _extract_reasons(segments):
    reasons = set()
    for s in segments:
        for f in s.get("factors", []):
            reasons.add(f)
    return sorted(reasons)[:8]


# ── OSRM (via osrm_service with Redis caching) ──

async def _fetch_osrm_routes(start_lat, start_lng, end_lat, end_lng):
    """Fetch up to 3 alternative routes via self-hosted OSRM → public fallback, Redis cached."""
    from app.services.osrm_service import get_route

    try:
        data = await get_route(
            start_lng=start_lng, start_lat=start_lat,
            end_lng=end_lng, end_lat=end_lat,
            alternatives=3,
        )
        if data.get("code") == "Ok":
            source = data.get("_source", "unknown")
            latency = data.get("_latency_ms", "?")
            cache = data.get("_cache", "unknown")
            logger.info(f"Route Safety: {len(data.get('routes', []))} routes from {source} ({latency}ms, cache={cache})")
            return data.get("routes", [])
        logger.warning(f"OSRM non-Ok response: {data.get('code')}")
    except Exception as e:
        logger.error(f"OSRM route fetch failed: {e}")
    return []


def _ensure_three_routes(raw_routes):
    """If OSRM returns fewer than 3 routes, create variants."""
    routes = list(raw_routes)
    if len(routes) >= 3:
        return routes[:3]

    base = routes[0]
    while len(routes) < 3:
        variant = _create_route_variant(base, len(routes))
        routes.append(variant)
    return routes


def _create_route_variant(base, variant_num):
    """Create a synthetic route variant by offsetting coordinates."""
    coords = base["geometry"]["coordinates"]
    offset = 0.001 * variant_num  # ~110m offset
    new_coords = []
    for i, (lng, lat) in enumerate(coords):
        # Alternate offset direction
        if variant_num == 1:
            nlat = lat + offset * math.sin(i * 0.3)
            nlng = lng + offset * math.cos(i * 0.3)
        else:
            nlat = lat - offset * math.sin(i * 0.5)
            nlng = lng - offset * math.cos(i * 0.5)
        new_coords.append([nlng, nlat])

    dist_factor = 1.0 + 0.08 * variant_num
    dur_factor = 1.0 + 0.12 * variant_num
    return {
        "distance": base["distance"] * dist_factor,
        "duration": base["duration"] * dur_factor,
        "geometry": {"type": "LineString", "coordinates": new_coords},
    }


# ── Geometry sampling ──

def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _sample_points(coords, interval_m):
    """Sample points along a polyline at regular intervals."""
    if not coords:
        return []
    # coords are [lng, lat] pairs
    sampled = [{"lat": coords[0][1], "lng": coords[0][0], "idx": 0}]
    accum = 0.0
    for i in range(1, len(coords)):
        d = _haversine(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0])
        accum += d
        if accum >= interval_m:
            sampled.append({"lat": coords[i][1], "lng": coords[i][0], "idx": i})
            accum = 0.0
    # Always include last point
    if len(coords) > 1:
        last = coords[-1]
        if sampled[-1]["lat"] != last[1] or sampled[-1]["lng"] != last[0]:
            sampled.append({"lat": last[1], "lng": last[0], "idx": len(coords) - 1})
    return sampled


# ── Segment scoring ──

async def _score_segments(session, sampled_points, hour):
    """Score segments in batch with minimal DB round-trips."""
    if len(sampled_points) < 2:
        return []

    time_risk = TIME_RISK.get(hour, 0.5)
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    points = sampled_points[:-1]  # segments = gaps between consecutive samples
    if not points:
        return []

    # Compute bounding box (with 0.01° buffer ≈ 1km)
    lats = [p["lat"] for p in points]
    lngs = [p["lng"] for p in points]
    bbox = {
        "min_lat": min(lats) - 0.01, "max_lat": max(lats) + 0.01,
        "min_lng": min(lngs) - 0.01, "max_lng": max(lngs) + 0.01,
        "cutoff": cutoff,
    }

    # Fetch all risk zones / incidents / devices inside the bounding box (3 queries total)
    zones_rows = (await session.execute(text("""
        SELECT risk_score, zone_name, factors, risk_type, ST_Y(geom) as lat, ST_X(geom) as lng
        FROM location_risk_zones
        WHERE ST_Y(geom) BETWEEN :min_lat AND :max_lat
          AND ST_X(geom) BETWEEN :min_lng AND :max_lng
    """), bbox)).fetchall()

    inc_rows = (await session.execute(text("""
        SELECT ST_Y(geom) as lat, ST_X(geom) as lng
        FROM location_incidents
        WHERE ST_Y(geom) BETWEEN :min_lat AND :max_lat
          AND ST_X(geom) BETWEEN :min_lng AND :max_lng
          AND created_at >= :cutoff
    """), bbox)).fetchall()

    dev_rows = (await session.execute(text("""
        SELECT ST_Y(geom) as lat, ST_X(geom) as lng
        FROM device_locations
        WHERE ST_Y(geom) BETWEEN :min_lat AND :max_lat
          AND ST_X(geom) BETWEEN :min_lng AND :max_lng
    """), bbox)).fetchall()

    # Pre-convert to lists for fast iteration (with trend multiplier extraction)
    zones = []
    for z in zones_rows:
        fac_raw = z.factors
        trend_mult = 1.0
        if isinstance(fac_raw, list):
            for item in fac_raw:
                if isinstance(item, dict) and 'trend_multiplier' in item:
                    trend_mult = item['trend_multiplier']
        elif isinstance(fac_raw, str):
            try:
                parsed = json.loads(fac_raw)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and 'trend_multiplier' in item:
                            trend_mult = item['trend_multiplier']
            except (json.JSONDecodeError, TypeError):
                pass
        zones.append((float(z.risk_score), z.zone_name, z.factors, float(z.lat), float(z.lng), trend_mult))
    incidents = [(float(i.lat), float(i.lng)) for i in inc_rows]
    devices = [(float(d.lat), float(d.lng)) for d in dev_rows]

    segments = []
    for p in points:
        lat, lng = p["lat"], p["lng"]

        # Check cached forecast first (fast path — avoids zone/incident iteration for cached cells)
        from app.services.risk_forecast_engine import get_point_forecast_cached
        cached_fc = get_point_forecast_cached(lat, lng)

        # Zone proximity (within ~500m ≈ 0.0045°)
        zone_score = 0.0
        zone_name = None
        zone_factors = []
        for z_risk, z_name, z_fac, z_lat, z_lng, z_trend_mult in zones:
            if abs(lat - z_lat) < 0.0045 and abs(lng - z_lng) < 0.006:
                dist = _haversine(lat, lng, z_lat, z_lng)
                if dist <= 500 and z_risk / 10.0 * z_trend_mult > zone_score:
                    zone_score = min(1.0, z_risk / 10.0 * z_trend_mult)
                    zone_name = z_name
                    raw_fac = z_fac
                    if isinstance(raw_fac, str):
                        zone_factors = json.loads(raw_fac)
                    elif raw_fac:
                        zone_factors = list(raw_fac)
                    else:
                        zone_factors = []

        # Incident density (within ~300m)
        inc_count = sum(
            1 for i_lat, i_lng in incidents
            if abs(lat - i_lat) < 0.003 and abs(lng - i_lng) < 0.004
            and _haversine(lat, lng, i_lat, i_lng) <= 300
        )
        incident_score = min(1.0, inc_count / 8.0)

        # Isolation (devices within ~500m)
        dev_count = sum(
            1 for d_lat, d_lng in devices
            if abs(lat - d_lat) < 0.0045 and abs(lng - d_lng) < 0.006
            and _haversine(lat, lng, d_lat, d_lng) <= 500
        )
        isolation = max(0, 1.0 - dev_count / 4.0)

        raw = (
            W_ZONE * zone_score
            + W_INCIDENT * incident_score
            + W_TIME * time_risk
            + W_ISOLATION * isolation
        ) * 10.0
        # Blend cached forecast if available (adds predictive awareness)
        if cached_fc and cached_fc.get("risk_score") is not None:
            forecast_risk = cached_fc["risk_score"]
            raw = raw * 0.7 + forecast_risk * 0.3  # 70% live + 30% predictive
        seg_risk = round(min(10.0, max(0.0, raw)), 1)

        factors = []
        if zone_name and zone_score > 0.3:
            factors.append(f"Near {zone_name}")
            factors.extend(zone_factors[:2])
        if inc_count > 0:
            factors.append(f"{inc_count} incident(s) nearby")
        if time_risk >= 0.6:
            factors.append("Night hours")
        if isolation > 0.5:
            factors.append("Low crowd density")

        segments.append({
            "lat": lat,
            "lng": lng,
            "risk": seg_risk,
            "level": _risk_level(seg_risk),
            "factors": factors,
        })

    return segments


# ── Heatmap Integration ──

async def _fetch_heatmap_cells(session: AsyncSession) -> list[dict]:
    """Fetch heatmap cells for route risk overlay. Gracefully degrades if heatmap unavailable."""
    try:
        from app.services.city_heatmap_engine import generate_city_heatmap
        heatmap = await generate_city_heatmap(session)
        return heatmap.get("cells", [])
    except Exception as e:
        logger.warning(f"Heatmap fetch failed (non-blocking): {e}")
        return []


def _analyze_route_heatmap(sampled_points: list[dict], heatmap_cells: list[dict]) -> dict:
    """Analyze which heatmap cells a route passes through."""
    if not heatmap_cells or not sampled_points:
        return {
            "risk_zones": [],
            "warnings": [],
            "summary": {"critical_crossings": 0, "high_crossings": 0, "total_crossings": 0},
            "heatmap_penalty": 0.0,
        }

    # Build a quick lookup grid for heatmap cells
    cell_lookup = {}
    for cell in heatmap_cells:
        key = (round(cell["lat"], 3), round(cell["lng"], 3))
        if key not in cell_lookup or cell["composite_score"] > cell_lookup[key]["composite_score"]:
            cell_lookup[key] = cell

    risk_zones = []
    seen_cells = set()
    critical_crossings = 0
    high_crossings = 0

    for pt in sampled_points:
        # Check nearby cells (1 grid step in each direction)
        for dlat in [-0.002, -0.001, 0, 0.001, 0.002]:
            for dlng in [-0.002, -0.001, 0, 0.001, 0.002]:
                check_key = (round(pt["lat"] + dlat, 3), round(pt["lng"] + dlng, 3))
                cell = cell_lookup.get(check_key)
                if cell and cell["grid_id"] not in seen_cells and cell["risk_level"] in ("critical", "high"):
                    dist = _haversine(pt["lat"], pt["lng"], cell["lat"], cell["lng"])
                    if dist <= 400:  # Within ~400m of a dangerous cell
                        seen_cells.add(cell["grid_id"])
                        risk_zones.append({
                            "grid_id": cell["grid_id"],
                            "lat": cell["lat"],
                            "lng": cell["lng"],
                            "risk_level": cell["risk_level"],
                            "composite_score": cell["composite_score"],
                            "forecast": cell.get("forecast", 0),
                            "forecast_category": cell.get("forecast_category", "stable"),
                        })
                        if cell["risk_level"] == "critical":
                            critical_crossings += 1
                        elif cell["risk_level"] == "high":
                            high_crossings += 1

    # Generate warnings
    warnings = []
    if critical_crossings > 0:
        warnings.append(f"Route crosses {critical_crossings} critical danger zone{'s' if critical_crossings > 1 else ''}")
    if high_crossings > 0:
        warnings.append(f"Route passes through {high_crossings} high-risk area{'s' if high_crossings > 1 else ''}")

    # Forecast escalation warnings
    escalating = [z for z in risk_zones if z.get("forecast_category") == "escalating"]
    if escalating:
        warnings.append(f"{len(escalating)} zone{'s' if len(escalating) > 1 else ''} with escalating forecast — avoid if possible")

    # Heatmap penalty: penalize routes through dangerous cells
    # Critical crossings add 0.8 risk per crossing, high adds 0.4
    heatmap_penalty = min(3.0, critical_crossings * 0.8 + high_crossings * 0.4)

    return {
        "risk_zones": risk_zones[:20],  # Cap at 20 for response size
        "warnings": warnings,
        "summary": {
            "critical_crossings": critical_crossings,
            "high_crossings": high_crossings,
            "total_crossings": critical_crossings + high_crossings,
        },
        "heatmap_penalty": round(heatmap_penalty, 2),
    }



# ── Cache ──

def _cache_key(slat, slng, elat, elng, hour):
    raw = f"{round(slat,4)},{round(slng,4)},{round(elat,4)},{round(elng,4)},{hour}"
    return hashlib.md5(raw.encode()).hexdigest()


CACHE_TTL_MINUTES = 15


async def _get_cache(session, key):
    row = (await session.execute(text("""
        SELECT result FROM route_safety_cache
        WHERE cache_key = :key AND created_at > :cutoff
    """), {"key": key, "cutoff": datetime.now(timezone.utc) - timedelta(minutes=CACHE_TTL_MINUTES)})).fetchone()
    if row:
        return json.loads(row.result) if isinstance(row.result, str) else row.result
    return None


async def _set_cache(session, key, result):
    await session.execute(text("""
        INSERT INTO route_safety_cache (cache_key, result, created_at)
        VALUES (:key, :result, NOW())
        ON CONFLICT (cache_key) DO UPDATE SET result = EXCLUDED.result, created_at = NOW()
    """), {"key": key, "result": json.dumps(result)})
    await session.commit()
