# Safe Route AI Engine — Safety-Aware Routing
# Generates optimal routes: fastest, safest, balanced, night_guardian.
# Uses OSRM for candidate routes, safe_zone_engine for risk scoring.
# Integrates forecast cache for predictive risk awareness.
#
# Route Safety Score = 0.5 * segment_live_risk + 0.3 * forecast_risk + 0.2 * environmental
# Night Guardian Mode: 80% safety / 20% travel time

import math
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.safe_zone_engine import (
    _fetch_zones, _compute_crime_density, _haversine,
    generate_zone_id, _classify_risk, _get_tod_multiplier,
)

logger = logging.getLogger(__name__)

SEGMENT_INTERVAL_M = 100

# Night multipliers for risk amplification
NIGHT_MULTIPLIERS = {"day": 1.0, "night": 1.4, "late_night": 1.7}

# Route mode weighting: (time_weight, safety_weight)
MODE_WEIGHTS = {
    "fastest":        (0.80, 0.20),
    "safest":         (0.20, 0.80),
    "balanced":       (0.50, 0.50),
    "night_guardian":  (0.20, 0.80),
}

# Segment scoring formula weights
W_LIVE_RISK = 0.50
W_FORECAST = 0.30
W_ENVIRONMENTAL = 0.20

# Route type colors for frontend
ROUTE_COLORS = {"fastest": "#ef4444", "safest": "#22c55e", "balanced": "#f59e0b"}

# Segment color thresholds
def _segment_color(risk: float) -> str:
    if risk >= 7.0:
        return "#ef4444"  # red
    if risk >= 4.0:
        return "#f59e0b"  # yellow
    return "#22c55e"      # green


# ── Environmental Factors ──

def _compute_environmental_factor(lat: float, lng: float, hour: int) -> tuple[float, list[str]]:
    """
    Compute environmental risk factor (0-1) and contributing factors.
    Combines: lighting, crowd density proxy, time-of-day.
    """
    factors = []
    score = 0.0

    # Lighting (proxy: based on hour)
    if hour >= 22 or hour < 5:
        score += 0.4
        factors.append("low_lighting")
    elif hour >= 19 or hour < 6:
        score += 0.2
        factors.append("dim_lighting")

    # Crowd density proxy (based on hour — empty streets are riskier)
    if 1 <= hour <= 4:
        score += 0.35
        factors.append("deserted_area")
    elif 22 <= hour or hour <= 5:
        score += 0.15
        factors.append("low_crowd")

    # Late night amplifier
    if hour >= 23 or hour < 4:
        score += 0.25
        factors.append("late_night")

    return min(1.0, score), factors


# ── Main Entry ──

async def generate_safe_routes(
    session: AsyncSession,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    timestamp: datetime | None = None,
    mode: str = "balanced",
) -> dict:
    """
    Generate safety-aware routes between two points.

    mode: fastest | safest | balanced | night_guardian
    Returns 3 route options with per-segment risk + color coding.
    """
    now = timestamp or datetime.now(timezone.utc)
    hour = now.hour
    tod_mult, tod_label = _get_tod_multiplier(hour)
    night_mult = NIGHT_MULTIPLIERS.get(tod_label, 1.0)

    # Resolve weighting for this mode
    time_w, safety_w = MODE_WEIGHTS.get(mode, MODE_WEIGHTS["balanced"])

    # Night Guardian: auto-activate if late night regardless of mode
    if tod_label in ("night", "late_night") and mode != "fastest":
        time_w, safety_w = MODE_WEIGHTS["night_guardian"]
        mode = "night_guardian"

    # 1. Fetch candidate routes from OSRM
    raw_routes = await _fetch_osrm_routes(origin_lat, origin_lng, dest_lat, dest_lng)
    if not raw_routes:
        return {"error": "Could not fetch routes from routing service", "routes": []}

    candidates = _ensure_three_candidates(raw_routes)

    # 2. Fetch zone risk data (single DB call)
    zones = await _fetch_zones(session)

    # 3. Score each candidate with full formula
    scored = []
    for i, route in enumerate(candidates):
        coords = route["geometry"]["coordinates"]
        segments = _segment_route(coords, SEGMENT_INTERVAL_M)
        risk_data = _score_route_segments(segments, zones, hour)

        distance_km = round(route["distance"] / 1000, 1)
        time_min = round(route["duration"] / 60, 1)

        base_risk = risk_data["avg_risk"]
        adjusted_risk = round(min(10.0, base_risk * night_mult), 2)

        # Weighted route cost = time_w * time_normalized + safety_w * risk_normalized
        time_cost = time_min
        risk_cost = adjusted_risk * distance_km
        weighted_cost = time_w * time_min + safety_w * (adjusted_risk * 10)

        scored.append({
            "index": i,
            "distance_km": distance_km,
            "time_min": time_min,
            "base_risk_score": base_risk,
            "risk_score": adjusted_risk,
            "risk_level": _classify_risk(adjusted_risk),
            "zones_crossed": risk_data["zones_crossed"],
            "high_risk_zones": risk_data["high_risk_count"],
            "critical_zones": risk_data["critical_count"],
            "segments": risk_data["segments"],
            "segment_count": len(segments),
            "time_cost": time_cost,
            "risk_cost": round(risk_cost, 2),
            "weighted_cost": round(weighted_cost, 2),
            "geometry": coords,
            "warnings": risk_data["warnings"],
            "environmental_factors": risk_data["environmental_factors"],
            "forecast_risk_avg": risk_data["forecast_risk_avg"],
        })

    # 4. Rank and assign types
    routes = _rank_routes(scored, mode)

    return {
        "routes": routes,
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "destination": {"lat": dest_lat, "lng": dest_lng},
        "mode": mode,
        "mode_weights": {"time": time_w, "safety": safety_w},
        "time_period": tod_label,
        "night_multiplier": night_mult,
        "hour": hour,
        "total_candidates": len(candidates),
        "recommendation": routes[0]["type"] if routes else "balanced",
        "generated_at": now.isoformat(),
    }


# ── Route Ranking ──

def _rank_routes(scored: list[dict], mode: str) -> list[dict]:
    """Assign fastest/safest/balanced from scored candidates."""
    if not scored:
        return []

    by_time = sorted(scored, key=lambda r: r["time_min"])
    by_risk = sorted(scored, key=lambda r: r["risk_score"])
    by_weighted = sorted(scored, key=lambda r: r["weighted_cost"])

    used_indices = set()
    routes = []

    # Primary pick based on mode
    if mode == "fastest":
        primary = by_time[0]
        primary_type = "fastest"
    elif mode in ("safest", "night_guardian"):
        primary = by_risk[0]
        primary_type = "safest"
    else:
        primary = by_weighted[0]
        primary_type = "balanced"

    routes.append(_format_route(primary, primary_type, recommended=True))
    used_indices.add(primary["index"])

    # Fastest (if not already picked)
    if "fastest" not in {r["type"] for r in routes}:
        fastest = next((r for r in by_time if r["index"] not in used_indices), by_time[0])
        routes.append(_format_route(fastest, "fastest"))
        used_indices.add(fastest["index"])

    # Safest (if not already picked)
    if "safest" not in {r["type"] for r in routes}:
        safest = next((r for r in by_risk if r["index"] not in used_indices), by_risk[0])
        routes.append(_format_route(safest, "safest"))
        used_indices.add(safest["index"])

    # Balanced (if not already picked)
    if "balanced" not in {r["type"] for r in routes}:
        balanced = next((r for r in by_weighted if r["index"] not in used_indices), by_weighted[0])
        routes.append(_format_route(balanced, "balanced"))

    return routes


def _format_route(scored: dict, route_type: str, recommended: bool = False) -> dict:
    """Format a scored route for API response."""
    return {
        "type": route_type,
        "recommended": recommended,
        "distance_km": scored["distance_km"],
        "time_min": scored["time_min"],
        "risk_score": scored["risk_score"],
        "base_risk_score": scored["base_risk_score"],
        "risk_level": scored["risk_level"],
        "zones_crossed": scored["zones_crossed"],
        "high_risk_zones": scored["high_risk_zones"],
        "critical_zones": scored["critical_zones"],
        "segment_count": scored["segment_count"],
        "color": ROUTE_COLORS.get(route_type, "#6366f1"),
        "geometry": scored["geometry"],
        "segments": scored["segments"],
        "warnings": scored["warnings"],
        "environmental_factors": scored["environmental_factors"],
        "forecast_risk_avg": scored["forecast_risk_avg"],
        "cost": {
            "time": scored["time_cost"],
            "risk": scored["risk_cost"],
            "weighted": scored["weighted_cost"],
        },
    }


# ── Route Segmentation ──

def _segment_route(coords: list, interval_m: float) -> list[dict]:
    """Split route coords into segments at regular intervals."""
    if not coords or len(coords) < 2:
        return []

    segments = []
    accum = 0.0
    prev_lat, prev_lng = coords[0][1], coords[0][0]
    segments.append({"lat": prev_lat, "lng": prev_lng, "idx": 0})

    for i in range(1, len(coords)):
        lat, lng = coords[i][1], coords[i][0]
        d = _haversine(prev_lat, prev_lng, lat, lng)
        accum += d
        if accum >= interval_m:
            segments.append({"lat": lat, "lng": lng, "idx": i})
            accum = 0.0
        prev_lat, prev_lng = lat, lng

    last_lat, last_lng = coords[-1][1], coords[-1][0]
    if segments[-1]["lat"] != last_lat or segments[-1]["lng"] != last_lng:
        segments.append({"lat": last_lat, "lng": last_lng, "idx": len(coords) - 1})

    return segments


# ── Segment Scoring (Full Formula) ──

def _score_route_segments(segments: list[dict], zones: list[dict], hour: int) -> dict:
    """
    Score all segments using:
      Route Safety Score = 0.5 * live_risk + 0.3 * forecast_risk + 0.2 * environmental
    """
    if not segments:
        return {
            "avg_risk": 0, "segments": [], "zones_crossed": 0,
            "high_risk_count": 0, "critical_count": 0, "warnings": [],
            "environmental_factors": [], "forecast_risk_avg": 0,
        }

    from app.services.risk_forecast_engine import get_point_forecast_cached

    scored_segments = []
    zone_ids_seen = set()
    high_risk = 0
    critical = 0
    total_risk = 0.0
    total_forecast = 0.0
    forecast_count = 0
    env_factor_set = set()
    warnings = []

    for seg in segments:
        lat, lng = seg["lat"], seg["lng"]
        zone_id = generate_zone_id(lat, lng)

        # 1. Live risk (zone crime density)
        live_risk = min(10.0, _compute_crime_density(lat, lng, zones))

        # 2. Forecast risk (cached grid)
        forecast_risk = 5.0  # Default moderate
        cached_fc = get_point_forecast_cached(lat, lng)
        if cached_fc and cached_fc.get("risk_score") is not None:
            forecast_risk = cached_fc["risk_score"]
            forecast_count += 1
        total_forecast += forecast_risk

        # 3. Environmental factor
        env_score, env_factors = _compute_environmental_factor(lat, lng, hour)
        env_factor_set.update(env_factors)

        # Combined score
        risk = round(min(10.0,
            W_LIVE_RISK * live_risk +
            W_FORECAST * forecast_risk +
            W_ENVIRONMENTAL * (env_score * 10.0)
        ), 2)

        zone_ids_seen.add(zone_id)
        total_risk += risk
        risk_level = _classify_risk(risk)

        if risk_level == "HIGH":
            high_risk += 1
        elif risk_level == "CRITICAL":
            critical += 1

        scored_segments.append({
            "lat": lat,
            "lng": lng,
            "zone_id": zone_id,
            "risk": risk,
            "risk_level": risk_level,
            "color": _segment_color(risk),
            "live_risk": round(live_risk, 2),
            "forecast_risk": round(forecast_risk, 2),
            "environmental": round(env_score, 2),
        })

    avg_risk = round(total_risk / len(segments), 2) if segments else 0
    forecast_avg = round(total_forecast / len(segments), 2) if segments else 0

    if critical > 0:
        warnings.append(f"Route passes through {critical} CRITICAL danger zone{'s' if critical > 1 else ''}")
    if high_risk > 0:
        warnings.append(f"Route crosses {high_risk} HIGH risk segment{'s' if high_risk > 1 else ''}")

    return {
        "avg_risk": avg_risk,
        "segments": scored_segments,
        "zones_crossed": len(zone_ids_seen),
        "high_risk_count": high_risk,
        "critical_count": critical,
        "warnings": warnings,
        "environmental_factors": sorted(env_factor_set),
        "forecast_risk_avg": forecast_avg,
    }


# ── OSRM Integration ──

async def _fetch_osrm_routes(start_lat, start_lng, end_lat, end_lng) -> list:
    """Fetch up to 3 alternative routes from OSRM."""
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
            logger.info(f"Safe Route: {len(data.get('routes', []))} routes from {source} ({latency}ms, cache={cache})")
            return data.get("routes", [])
        logger.warning(f"OSRM non-Ok: {data.get('code')} - {data.get('message', '')}")
    except Exception as e:
        logger.error(f"Route fetch failed: {e}")
    return []


def _ensure_three_candidates(raw_routes: list) -> list:
    """If OSRM returns fewer than 3 routes, create synthetic variants."""
    routes = list(raw_routes)
    if len(routes) >= 3:
        return routes[:3]

    base = routes[0]
    while len(routes) < 3:
        variant = _create_variant(base, len(routes))
        routes.append(variant)
    return routes


def _create_variant(base: dict, variant_num: int) -> dict:
    """Create a synthetic route variant by offsetting coordinates."""
    coords = base["geometry"]["coordinates"]
    offset = 0.0012 * variant_num
    new_coords = []
    for i, (lng, lat) in enumerate(coords):
        if variant_num == 1:
            nlat = lat + offset * math.sin(i * 0.4)
            nlng = lng + offset * math.cos(i * 0.4)
        else:
            nlat = lat - offset * math.sin(i * 0.6)
            nlng = lng - offset * math.cos(i * 0.6)
        new_coords.append([nlng, nlat])

    return {
        "distance": base["distance"] * (1.0 + 0.1 * variant_num),
        "duration": base["duration"] * (1.0 + 0.15 * variant_num),
        "geometry": {"type": "LineString", "coordinates": new_coords},
    }
