# Predictive Risk Forecasting Engine
# Predicts risk scores at 24h/48h/72h horizons for learned hotspot zones.
# Uses trend score, incident velocity, severity shifts, and temporal patterns.
# Cache: Redis-backed grid cache (30-min TTL) with in-memory fallback.
# Safety rule: Always recompute live during active emergencies.

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hotspot_trend_engine import (
    _fetch_zones, _fetch_all_incidents, _filter_near,
    _compute_window_stats, _compute_trend_score, SEVERITY_WEIGHT,
)
from app.services.redis_service import (
    cache_forecast_zone, get_forecast_zone, cache_forecast_1hr, get_forecast_1hr,
)

logger = logging.getLogger(__name__)

# Forecast horizons in hours
HORIZONS = [24, 48, 72]

# Forecast classification thresholds
FORECAST_ESCALATING = 7.0   # predicted score → will become P1
FORECAST_EMERGING = 5.0     # predicted score → rising concern
FORECAST_COOLING = -0.15    # negative velocity → cooling


def _incident_velocity(recent_7d: dict, previous_7d: dict) -> float:
    """Incidents per day growth rate over 7d window."""
    recent_rate = recent_7d["count"] / 7.0
    prev_rate = max(previous_7d["count"] / 7.0, 0.01)
    return round(recent_rate / prev_rate, 3)


def _severity_momentum(recent: dict, previous: dict) -> float:
    """Change in severity-weighted score normalized by count."""
    r_avg = recent["severity_weighted"] / max(recent["count"], 1)
    p_avg = previous["severity_weighted"] / max(previous["count"], 1)
    return round(r_avg - p_avg, 3)


def _temporal_pattern_factor(nearby_incidents: list[dict], now: datetime) -> float:
    """Detect cyclical patterns — incidents clustering at similar times-of-day."""
    if len(nearby_incidents) < 3:
        return 0.0
    # Check if incidents cluster in specific hours
    hour_counts = defaultdict(int)
    for inc in nearby_incidents:
        hour_counts[inc["hour"]] += 1
    if not hour_counts:
        return 0.0
    max_hour_count = max(hour_counts.values())
    total = sum(hour_counts.values())
    concentration = max_hour_count / total
    # High concentration = stronger temporal pattern
    return round(max(0.0, concentration - 0.2) * 2.0, 3)


def _compute_forecast(
    current_score: float,
    trend_score: float,
    velocity: float,
    severity_momentum: float,
    temporal_factor: float,
    hours: int,
) -> float:
    """
    predicted_risk = current_score + (trend_score × velocity × time_factor)
    with severity momentum and temporal pattern adjustments.
    """
    time_factor = hours / 24.0  # normalize to days
    # Core prediction: current + directional movement over time
    trend_component = trend_score * velocity * time_factor * 1.5
    # Severity momentum amplifies or dampens
    severity_component = severity_momentum * time_factor * 0.5
    # Temporal pattern adds predictability boost for growing zones
    temporal_component = temporal_factor * trend_score * time_factor * 0.3

    predicted = current_score + trend_component + severity_component + temporal_component
    # Clamp to valid range
    return round(max(0.0, min(10.0, predicted)), 1)


def _forecast_category(current: float, predicted_48h: float, velocity: float) -> str:
    """Classify the forecast."""
    delta = predicted_48h - current
    if predicted_48h >= FORECAST_ESCALATING and delta > 0.5:
        return "escalating"
    if delta > 0.3 and predicted_48h >= FORECAST_EMERGING:
        return "emerging"
    if delta < FORECAST_COOLING or velocity < 0.5:
        return "cooling"
    return "stable"


def _forecast_priority(category: str, predicted_48h: float) -> int:
    """Predicted operator priority."""
    if category == "escalating":
        return 1
    if category == "emerging" and predicted_48h >= 6:
        return 1
    if category == "emerging":
        return 2
    if category == "stable" and predicted_48h >= 7:
        return 2
    return 3


def _recommendation(category: str, zone_name: str, predicted_48h: float, current: float) -> dict:
    """Preventive recommendation for operators."""
    recs = {
        "escalating": {
            "action": "Increase patrol frequency",
            "details": [
                f"{zone_name} predicted to reach {predicted_48h} within 48h",
                "Notify nearby guardians of elevated risk",
                "Adjust route safety weighting immediately",
                "Consider deploying mobile response unit",
            ],
            "urgency": "high",
        },
        "emerging": {
            "action": "Monitor closely",
            "details": [
                f"{zone_name} showing risk escalation trend",
                "Review recent incident patterns",
                "Pre-alert guardian network",
                "Flag for next shift briefing",
            ],
            "urgency": "medium",
        },
        "stable": {
            "action": "Maintain current monitoring",
            "details": [
                f"{zone_name} risk expected to remain around {predicted_48h}",
                "Continue standard patrol schedule",
            ],
            "urgency": "low",
        },
        "cooling": {
            "action": "Reduce alert level",
            "details": [
                f"{zone_name} risk declining from {current} to {predicted_48h}",
                "May reduce patrol frequency",
                "Re-evaluate in 72h",
            ],
            "urgency": "low",
        },
    }
    return recs.get(category, recs["stable"])


def _compute_zone_forecast(zone: dict, all_incidents: list[dict], now: datetime) -> dict:
    """Compute forecast for a single zone using pre-fetched data."""
    lat, lng = zone["lat"], zone["lng"]
    radius = zone.get("radius_meters", 500)
    current_score = zone.get("risk_score", 0)

    # Filter nearby incidents
    nearby = _filter_near(all_incidents, lat, lng, radius)

    # 7d windows for trend and velocity
    recent_start = now - timedelta(days=7)
    previous_start = recent_start - timedelta(days=7)
    recent = [i for i in nearby if recent_start <= i["created_at"] <= now]
    previous = [i for i in nearby if previous_start <= i["created_at"] < recent_start]

    recent_stats = _compute_window_stats(recent)
    previous_stats = _compute_window_stats(previous)

    trend_score = _compute_trend_score(recent_stats, previous_stats)
    velocity = _incident_velocity(recent_stats, previous_stats)
    sev_momentum = _severity_momentum(recent_stats, previous_stats)
    temporal = _temporal_pattern_factor(nearby, now)

    # Compute predictions for each horizon
    predictions = {}
    for h in HORIZONS:
        predicted = _compute_forecast(current_score, trend_score, velocity, sev_momentum, temporal, h)
        predictions[f"{h}h"] = predicted

    # Forecast sparkline: past 7 days + 3 future points
    sparkline_past = []
    for day_offset in range(6, -1, -1):
        day_start = now - timedelta(days=day_offset + 1)
        day_end = now - timedelta(days=day_offset)
        count = sum(1 for i in nearby if day_start <= i["created_at"] < day_end)
        sparkline_past.append(count)

    # Future projection points (incident counts are hard to predict, use risk score deltas)
    sparkline_future = [
        predictions["24h"],
        predictions["48h"],
        predictions["72h"],
    ]

    pred_48h = predictions.get("48h", current_score)
    category = _forecast_category(current_score, pred_48h, velocity)
    priority = _forecast_priority(category, pred_48h)
    rec = _recommendation(category, zone.get("zone_name", "Zone"), pred_48h, current_score)

    # Confidence based on data quality
    data_points = len(nearby)
    confidence = min(1.0, data_points / 20.0) * 0.5 + min(1.0, abs(trend_score) / 0.5) * 0.3 + min(1.0, velocity / 2.0) * 0.2
    confidence = round(max(0.1, min(0.95, confidence)), 2)

    return {
        "zone_id": zone.get("zone_id", ""),
        "zone_name": zone.get("zone_name", ""),
        "risk_score": current_score,
        "risk_level": zone.get("risk_level", ""),
        "lat": lat,
        "lng": lng,
        "radius_meters": radius,
        "incident_count": zone.get("incident_count", 0),
        "factors": zone.get("factors", []),
        "predicted_24h": predictions["24h"],
        "predicted_48h": predictions["48h"],
        "predicted_72h": predictions["72h"],
        "forecast_category": category,
        "forecast_priority": priority,
        "confidence": confidence,
        "signals": {
            "trend_score": trend_score,
            "incident_velocity": velocity,
            "severity_momentum": sev_momentum,
            "temporal_pattern": temporal,
        },
        "recommendation": rec,
        "sparkline_past": sparkline_past,
        "sparkline_future": sparkline_future,
    }


async def get_all_forecasts(session: AsyncSession, force_recompute: bool = False) -> dict:
    """Compute forecasts for all learned hotspot zones. Uses cache when available."""
    now = datetime.now(timezone.utc)

    zones = await _fetch_zones(session)
    if not zones:
        return {"total_zones": 0, "forecast_counts": {}, "priority_counts": {},
                "forecasts": [], "escalating_zones": [], "emerging_zones": [],
                "cooling_zones": [], "analyzed_at": now.isoformat()}

    all_incidents = None  # Lazy-load only if needed

    forecasts = []
    cache_hits = 0
    for z in zones:
        zone_id = z.get("zone_id", "")

        # Check zone cache first (unless emergency bypass)
        if not force_recompute:
            cached = get_forecast_zone(zone_id)
            if cached:
                forecasts.append(cached)
                cache_hits += 1
                continue

        # Cache miss — compute fresh
        if all_incidents is None:
            all_incidents = await _fetch_all_incidents(session, timedelta(days=14))

        fc = _compute_zone_forecast(z, all_incidents, now)
        forecasts.append(fc)

        # Cache the result
        cache_forecast_zone(zone_id, fc)
        # Also cache by grid cell for point-based lookups
        cache_forecast_1hr(z["lat"], z["lng"], {
            "grid_id": f"{z['lat']:.5f}_{z['lng']:.5f}",
            "forecast_window": "1h",
            "risk_score": fc.get("predicted_24h", fc.get("risk_score", 0)),
            "risk_level": fc.get("forecast_category", "stable"),
            "top_factors": [s for s, _ in sorted(fc.get("signals", {}).items(), key=lambda x: abs(x[1]), reverse=True)[:3]],
            "generated_at": now.isoformat(),
        })

    logger.info(f"Forecast: {len(forecasts)} zones, {cache_hits} cache hits, {len(forecasts) - cache_hits} computed")

    forecast_counts = defaultdict(int)
    priority_counts = defaultdict(int)
    for f in forecasts:
        forecast_counts[f["forecast_category"]] += 1
        priority_counts[f["forecast_priority"]] += 1

    escalating = sorted(
        [f for f in forecasts if f["forecast_category"] == "escalating"],
        key=lambda x: x["predicted_48h"], reverse=True,
    )
    emerging = sorted(
        [f for f in forecasts if f["forecast_category"] == "emerging"],
        key=lambda x: x["predicted_48h"], reverse=True,
    )
    cooling = sorted(
        [f for f in forecasts if f["forecast_category"] == "cooling"],
        key=lambda x: x["predicted_48h"],
    )

    p1_in_48h = sum(1 for f in forecasts if f["predicted_48h"] >= 7.0 and f["forecast_category"] in ("escalating", "emerging"))

    return {
        "total_zones": len(forecasts),
        "forecast_counts": dict(forecast_counts),
        "priority_counts": {str(k): v for k, v in priority_counts.items()},
        "p1_predicted_48h": p1_in_48h,
        "forecasts": forecasts,
        "escalating_zones": escalating[:5],
        "emerging_zones": emerging[:5],
        "cooling_zones": cooling[:5],
        "analyzed_at": now.isoformat(),
    }


async def get_zone_forecast(session: AsyncSession, zone_id: str, force_recompute: bool = False) -> dict | None:
    """Compute forecast for a single zone. Uses cache when available."""
    # Check cache first
    if not force_recompute:
        cached = get_forecast_zone(str(zone_id))
        if cached:
            logger.info(f"Forecast cache hit for zone {zone_id}")
            return cached

    now = datetime.now(timezone.utc)

    zones = await _fetch_zones(session)
    zone = next((z for z in zones if z["zone_id"] == str(zone_id)), None)
    if not zone:
        return None

    all_incidents = await _fetch_all_incidents(session, timedelta(days=14))
    fc = _compute_zone_forecast(zone, all_incidents, now)

    # Cache the result
    cache_forecast_zone(str(zone_id), fc)
    cache_forecast_1hr(zone["lat"], zone["lng"], {
        "grid_id": f"{zone['lat']:.5f}_{zone['lng']:.5f}",
        "forecast_window": "1h",
        "risk_score": fc.get("predicted_24h", fc.get("risk_score", 0)),
        "risk_level": fc.get("forecast_category", "stable"),
        "top_factors": [s for s, _ in sorted(fc.get("signals", {}).items(), key=lambda x: abs(x[1]), reverse=True)[:3]],
        "generated_at": now.isoformat(),
    })

    return fc


async def get_forecast_summary(session: AsyncSession) -> dict:
    """Lightweight forecast summary for command center widget."""
    now = datetime.now(timezone.utc)

    zones = await _fetch_zones(session)
    if not zones:
        return {"total_zones": 0, "forecast_counts": {}, "priority_counts": {},
                "p1_predicted_48h": 0, "zones_escalating": 0,
                "avg_predicted_48h": 0, "analyzed_at": now.isoformat()}

    all_incidents = await _fetch_all_incidents(session, timedelta(days=14))

    forecast_counts = defaultdict(int)
    priority_counts = defaultdict(int)
    p1_count = 0
    total_48h = 0.0

    for zone in zones:
        fc = _compute_zone_forecast(zone, all_incidents, now)
        forecast_counts[fc["forecast_category"]] += 1
        priority_counts[fc["forecast_priority"]] += 1
        total_48h += fc["predicted_48h"]
        if fc["predicted_48h"] >= 7.0 and fc["forecast_category"] in ("escalating", "emerging"):
            p1_count += 1

    return {
        "total_zones": len(zones),
        "forecast_counts": dict(forecast_counts),
        "priority_counts": {str(k): v for k, v in priority_counts.items()},
        "p1_predicted_48h": p1_count,
        "zones_escalating": forecast_counts.get("escalating", 0),
        "avg_predicted_48h": round(total_48h / len(zones), 1) if zones else 0,
        "analyzed_at": now.isoformat(),
    }



# ── Point-Based Forecast Lookup (for route safety, predictive alerts) ──

def get_point_forecast_cached(lat: float, lng: float) -> dict | None:
    """
    Get cached 1-hour risk forecast for a coordinate.
    Uses grid-based cache lookup (~250m cell resolution).
    Returns None if no forecast is cached for this grid cell.
    """
    return get_forecast_1hr(lat, lng)


# ── Pre-Warming ──

# High-traffic zones to pre-warm (Mumbai defaults)
PREWARM_ZONES = [
    {"name": "CST Station", "lat": 18.9398, "lng": 72.8354},
    {"name": "Dadar Station", "lat": 19.0178, "lng": 72.8478},
    {"name": "Bandra Station", "lat": 19.0544, "lng": 72.8403},
    {"name": "Andheri Station", "lat": 19.1197, "lng": 72.8468},
    {"name": "Thane Station", "lat": 19.1860, "lng": 72.9756},
    {"name": "Lower Parel", "lat": 18.9947, "lng": 72.8295},
    {"name": "Marine Drive", "lat": 18.9432, "lng": 72.8235},
    {"name": "Churchgate", "lat": 18.9322, "lng": 72.8264},
    {"name": "Juhu Beach", "lat": 19.0883, "lng": 72.8264},
    {"name": "Colaba", "lat": 18.9067, "lng": 72.8147},
]


async def prewarm_forecasts(session: AsyncSession) -> dict:
    """
    Pre-compute forecasts for high-traffic zones.
    Called by background scheduler every 10 minutes.
    Ensures cache hit rate > 90% for common locations.
    """
    now = datetime.now(timezone.utc)
    warmed = 0
    errors = 0

    # Pre-warm named zones from DB
    try:
        zones = await _fetch_zones(session)
        if zones:
            all_incidents = await _fetch_all_incidents(session, timedelta(days=14))
            for z in zones:
                try:
                    fc = _compute_zone_forecast(z, all_incidents, now)
                    cache_forecast_zone(z.get("zone_id", ""), fc)
                    cache_forecast_1hr(z["lat"], z["lng"], {
                        "grid_id": f"{z['lat']:.5f}_{z['lng']:.5f}",
                        "forecast_window": "1h",
                        "risk_score": fc.get("predicted_24h", fc.get("risk_score", 0)),
                        "risk_level": fc.get("forecast_category", "stable"),
                        "top_factors": [s for s, _ in sorted(fc.get("signals", {}).items(), key=lambda x: abs(x[1]), reverse=True)[:3]],
                        "generated_at": now.isoformat(),
                    })
                    warmed += 1
                except Exception as e:
                    logger.warning(f"Prewarm failed for zone {z.get('zone_name')}: {e}")
                    errors += 1
    except Exception as e:
        logger.warning(f"Prewarm zone fetch failed: {e}")

    # Pre-warm high-traffic static zones
    for zone in PREWARM_ZONES:
        cache_forecast_1hr(zone["lat"], zone["lng"], {
            "grid_id": f"{zone['lat']:.5f}_{zone['lng']:.5f}",
            "forecast_window": "1h",
            "risk_score": 5.0,  # Default moderate — will be overwritten by real computation
            "risk_level": "moderate",
            "top_factors": ["pre_warm_default", "static_zone"],
            "generated_at": now.isoformat(),
            "prewarm": True,
        })
        warmed += 1

    logger.info(f"Forecast prewarm: {warmed} zones cached, {errors} errors")
    return {"warmed": warmed, "errors": errors, "timestamp": now.isoformat()}
