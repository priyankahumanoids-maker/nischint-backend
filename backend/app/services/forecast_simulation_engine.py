# Forecast Simulation Engine
# Allows operators to run "what-if" scenarios against the predictive forecast model.
# Simulates changes in incident rates, patrol deployment, and new hazard zones.

import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from copy import deepcopy

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hotspot_trend_engine import (
    _fetch_zones, _fetch_all_incidents, _filter_near,
    _compute_window_stats, _compute_trend_score,
)
from app.services.risk_forecast_engine import _compute_zone_forecast

logger = logging.getLogger(__name__)

# Scenario types
SCENARIO_TYPES = {
    "incident_surge": {
        "label": "Incident Surge",
        "description": "Simulate a sudden increase in incidents at specific zones",
        "params": ["zone_ids", "multiplier", "duration_hours"],
    },
    "patrol_deployment": {
        "label": "Patrol Deployment",
        "description": "Simulate deploying patrols to reduce incidents at zones",
        "params": ["zone_ids", "reduction_pct"],
    },
    "new_hazard": {
        "label": "New Hazard Zone",
        "description": "Simulate a new construction zone or event at a location",
        "params": ["lat", "lng", "radius_m", "severity", "incident_rate"],
    },
    "time_shift": {
        "label": "Time Shift",
        "description": "Forecast risk at a different time of day",
        "params": ["target_hour"],
    },
}


def _apply_incident_surge(incidents: list[dict], zone: dict, multiplier: float) -> list[dict]:
    """Clone and multiply incidents near a zone to simulate a surge."""
    lat, lng = zone["lat"], zone["lng"]
    radius = zone.get("radius_meters", 500)
    deg_approx = (radius / 1000.0) * 0.009 + 0.002

    nearby_idx = []
    for i, inc in enumerate(incidents):
        if abs(inc["lat"] - lat) <= deg_approx and abs(inc["lng"] - lng) <= deg_approx:
            nearby_idx.append(i)

    # Clone existing incidents to simulate surge
    extra = []
    clones_needed = int(len(nearby_idx) * (multiplier - 1))
    now = datetime.now(timezone.utc)
    for i in range(clones_needed):
        src = incidents[nearby_idx[i % max(len(nearby_idx), 1)]]
        clone = deepcopy(src)
        clone["created_at"] = now - timedelta(hours=i % 24)
        clone["hour"] = clone["created_at"].hour
        extra.append(clone)

    return incidents + extra


def _apply_patrol_reduction(incidents: list[dict], zone: dict, reduction_pct: float) -> list[dict]:
    """Remove a percentage of recent incidents near a zone (simulating patrol effect)."""
    lat, lng = zone["lat"], zone["lng"]
    radius = zone.get("radius_meters", 500)
    deg_approx = (radius / 1000.0) * 0.009 + 0.002

    # Find nearby incidents
    nearby = []
    others = []
    for inc in incidents:
        if abs(inc["lat"] - lat) <= deg_approx and abs(inc["lng"] - lng) <= deg_approx:
            nearby.append(inc)
        else:
            others.append(inc)

    # Keep only (1 - reduction_pct) of nearby incidents
    keep_count = max(0, int(len(nearby) * (1 - reduction_pct / 100)))
    # Keep the oldest ones (most established), remove recent
    nearby.sort(key=lambda x: x["created_at"])
    return others + nearby[:keep_count]


def _inject_synthetic_incidents(incidents: list[dict], lat: float, lng: float,
                                 severity: str, count: int) -> list[dict]:
    """Inject synthetic incidents at a new location."""
    now = datetime.now(timezone.utc)
    extra = []
    for i in range(count):
        extra.append({
            "id": f"sim_{i}",
            "lat": lat + (i % 3 - 1) * 0.001,
            "lng": lng + (i % 3 - 1) * 0.001,
            "incident_type": "sos_alert" if severity in ("critical", "high") else "fall_detected",
            "severity": severity,
            "created_at": now - timedelta(hours=i * 4),
            "hour": (now - timedelta(hours=i * 4)).hour,
        })
    return incidents + extra


async def run_forecast_scenario(session: AsyncSession, scenario: dict) -> dict:
    """
    Run a what-if forecast scenario.

    scenario = {
        "type": "incident_surge" | "patrol_deployment" | "new_hazard" | "time_shift",
        "params": { ... type-specific params ... },
        "name": "optional scenario name"
    }
    """
    now = datetime.now(timezone.utc)
    scenario_type = scenario.get("type", "")
    params = scenario.get("params", {})
    name = scenario.get("name", f"Scenario: {scenario_type}")

    if scenario_type not in SCENARIO_TYPES:
        return {"error": f"Unknown scenario type: {scenario_type}"}

    # Fetch baseline data
    zones = await _fetch_zones(session)
    all_incidents = await _fetch_all_incidents(session, timedelta(days=14))

    if not zones:
        return {"error": "No learned zones available", "scenario": name}

    # Compute baseline forecasts
    baseline_forecasts = [_compute_zone_forecast(z, all_incidents, now) for z in zones]

    # Apply scenario modifications to incident set
    modified_incidents = deepcopy(all_incidents)

    affected_zone_ids = set()
    scenario_details = {}

    if scenario_type == "incident_surge":
        zone_ids = params.get("zone_ids", [])
        multiplier = max(1.0, min(5.0, params.get("multiplier", 2.0)))
        for zone in zones:
            if not zone_ids or zone["zone_id"] in [str(z) for z in zone_ids]:
                modified_incidents = _apply_incident_surge(modified_incidents, zone, multiplier)
                affected_zone_ids.add(zone["zone_id"])
        scenario_details = {"multiplier": multiplier, "affected_zones": len(affected_zone_ids)}

    elif scenario_type == "patrol_deployment":
        zone_ids = params.get("zone_ids", [])
        reduction = max(10, min(90, params.get("reduction_pct", 40)))
        for zone in zones:
            if not zone_ids or zone["zone_id"] in [str(z) for z in zone_ids]:
                modified_incidents = _apply_patrol_reduction(modified_incidents, zone, reduction)
                affected_zone_ids.add(zone["zone_id"])
        scenario_details = {"reduction_pct": reduction, "affected_zones": len(affected_zone_ids)}

    elif scenario_type == "new_hazard":
        lat = params.get("lat", 12.97)
        lng = params.get("lng", 77.59)
        severity = params.get("severity", "high")
        rate = max(1, min(20, params.get("incident_rate", 5)))
        modified_incidents = _inject_synthetic_incidents(modified_incidents, lat, lng, severity, rate)
        scenario_details = {"lat": lat, "lng": lng, "severity": severity, "injected_incidents": rate, "radius_m": params.get("radius_m", 500)}

    elif scenario_type == "time_shift":
        target_hour = params.get("target_hour", 22)
        # Shift all incident hours to simulate a different time window
        for inc in modified_incidents:
            inc["hour"] = target_hour
        scenario_details = {"target_hour": target_hour}

    # Compute scenario forecasts with modified data
    scenario_forecasts = [_compute_zone_forecast(z, modified_incidents, now) for z in zones]

    # Build comparison
    comparisons = []
    for base, sim in zip(baseline_forecasts, scenario_forecasts):
        delta_24h = round(sim["predicted_24h"] - base["predicted_24h"], 1)
        delta_48h = round(sim["predicted_48h"] - base["predicted_48h"], 1)
        delta_72h = round(sim["predicted_72h"] - base["predicted_72h"], 1)
        category_changed = base["forecast_category"] != sim["forecast_category"]
        priority_changed = base["forecast_priority"] != sim["forecast_priority"]

        comparisons.append({
            "zone_id": base["zone_id"],
            "zone_name": base["zone_name"],
            "risk_score": base["risk_score"],
            "affected": base["zone_id"] in affected_zone_ids,
            "baseline": {
                "predicted_24h": base["predicted_24h"],
                "predicted_48h": base["predicted_48h"],
                "predicted_72h": base["predicted_72h"],
                "forecast_category": base["forecast_category"],
                "forecast_priority": base["forecast_priority"],
            },
            "scenario": {
                "predicted_24h": sim["predicted_24h"],
                "predicted_48h": sim["predicted_48h"],
                "predicted_72h": sim["predicted_72h"],
                "forecast_category": sim["forecast_category"],
                "forecast_priority": sim["forecast_priority"],
            },
            "delta_24h": delta_24h,
            "delta_48h": delta_48h,
            "delta_72h": delta_72h,
            "category_changed": category_changed,
            "priority_changed": priority_changed,
        })

    # Sort: most impacted first
    comparisons.sort(key=lambda x: abs(x["delta_48h"]), reverse=True)

    # Summary stats
    worsened = sum(1 for c in comparisons if c["delta_48h"] > 0.5)
    improved = sum(1 for c in comparisons if c["delta_48h"] < -0.5)
    category_changes = sum(1 for c in comparisons if c["category_changed"])
    priority_changes = sum(1 for c in comparisons if c["priority_changed"])

    new_p1 = sum(1 for c in comparisons if c["scenario"]["forecast_priority"] == 1 and c["baseline"]["forecast_priority"] != 1)
    resolved_p1 = sum(1 for c in comparisons if c["baseline"]["forecast_priority"] == 1 and c["scenario"]["forecast_priority"] != 1)

    return {
        "scenario_name": name,
        "scenario_type": scenario_type,
        "scenario_details": scenario_details,
        "total_zones": len(comparisons),
        "summary": {
            "zones_worsened": worsened,
            "zones_improved": improved,
            "category_changes": category_changes,
            "priority_changes": priority_changes,
            "new_p1_zones": new_p1,
            "resolved_p1_zones": resolved_p1,
        },
        "comparisons": comparisons,
        "simulated_at": now.isoformat(),
    }


def get_available_scenarios() -> dict:
    """Return available scenario types and their parameter schemas."""
    return {
        "scenarios": {
            k: {"label": v["label"], "description": v["description"], "params": v["params"]}
            for k, v in SCENARIO_TYPES.items()
        }
    }
