# Predictive Safety Reroute Service
#
# Computes safer alternative routes when Safety Brain risk score rises.
# Uses OSRM for alternative routes + safety scoring based on:
#   - Recent incident proximity (35%)
#   - Safe zone proximity (25%)
#   - Time-of-day risk / urban density proxy (20%)
#   - Path efficiency / shortest path (20%)
#
# Trigger logic:
#   Normal (<0.3)     → No reroute
#   Suspicious (≥0.3) → Passive monitoring
#   Dangerous (≥0.6)  → Auto reroute suggestion
#   Critical (≥0.85)  → Immediate reroute + SOS escalation

import math
import uuid
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reroute_suggestion import RerouteSuggestion
from app.services.event_broadcaster import broadcaster
from app.services.redis_service import get_json as _redis_get, set_json as _redis_set

logger = logging.getLogger(__name__)

# In-memory fallback
_mem: dict = {}

# Cooldown: no more than 1 reroute suggestion per user per 120s
REROUTE_COOLDOWN_S = 120

# Auto-trigger threshold (dangerous or above)
AUTO_TRIGGER_THRESHOLD = 0.6

# Route safety scoring weights (user-confirmed formula)
W_INCIDENT = 0.35
W_SAFE_ZONE = 0.25
W_TIME_OF_DAY = 0.20
W_EFFICIENCY = 0.20

# Time-of-day risk (0-1 scale)
TIME_RISK = {
    0: 0.9, 1: 0.95, 2: 0.95, 3: 0.9, 4: 0.8, 5: 0.5,
    6: 0.3, 7: 0.2, 8: 0.15, 9: 0.1, 10: 0.1, 11: 0.1,
    12: 0.15, 13: 0.15, 14: 0.15, 15: 0.2, 16: 0.2, 17: 0.3,
    18: 0.4, 19: 0.55, 20: 0.65, 21: 0.75, 22: 0.8, 23: 0.85,
}

# Incident proximity radius (meters)
INCIDENT_RADIUS_M = 500
# Safe zone proximity scoring range (meters)
SAFE_ZONE_RANGE_M = 1000


def _haversine(lat1, lng1, lat2, lng2):
    """Haversine distance in meters."""
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_store(key):
    val = _redis_get("reroute", key)
    if val is not None:
        return val
    return _mem.get(f"reroute:{key}")


def _set_store(key, data, ttl=300):
    ok = _redis_set("reroute", key, data, ttl=ttl)
    if not ok:
        _mem[f"reroute:{key}"] = data


def _check_cooldown(user_id: str) -> bool:
    """Returns True if cooldown is active (should NOT trigger)."""
    last = _get_store(f"cooldown:{user_id}")
    if last:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
        if elapsed < REROUTE_COOLDOWN_S:
            return True
    return False


def _set_cooldown(user_id: str):
    _set_store(f"cooldown:{user_id}", datetime.now(timezone.utc).isoformat(), ttl=REROUTE_COOLDOWN_S)


def _get_active_route_session(user_id: str) -> dict | None:
    """Get the user's active route monitoring session from Redis/memory."""
    from app.services.route_monitor_service import _store_get, CACHE_PREFIX
    session = _store_get(CACHE_PREFIX, user_id)
    if session and session.get("status") == "active":
        return session
    return None


async def _fetch_recent_incidents(session: AsyncSession, hours: int = 24) -> list[dict]:
    """Fetch recent safety incidents for route scoring."""
    from sqlalchemy import text
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    incidents = []

    # Safety brain events
    try:
        result = await session.execute(
            text("""
                SELECT location_lat, location_lng, risk_score, risk_level, primary_event
                FROM safety_events
                WHERE created_at > :cutoff AND status = 'active'
                ORDER BY created_at DESC LIMIT 100
            """),
            {"cutoff": cutoff},
        )
        for row in result.mappings():
            incidents.append({
                "lat": row["location_lat"], "lng": row["location_lng"],
                "score": row["risk_score"], "type": row["primary_event"],
            })
    except Exception as e:
        logger.warning(f"Failed to fetch safety events for reroute: {e}")

    # Fall events
    try:
        result = await session.execute(
            text("""
                SELECT lat, lng, confidence FROM fall_events
                WHERE created_at > :cutoff AND status != 'resolved'
                LIMIT 50
            """),
            {"cutoff": cutoff},
        )
        for row in result.mappings():
            incidents.append({"lat": row["lat"], "lng": row["lng"], "score": row["confidence"], "type": "fall"})
    except Exception:
        pass

    # Voice distress events
    try:
        result = await session.execute(
            text("""
                SELECT lat, lng, distress_score FROM voice_distress_events
                WHERE created_at > :cutoff AND status != 'resolved'
                LIMIT 50
            """),
            {"cutoff": cutoff},
        )
        for row in result.mappings():
            incidents.append({"lat": row["lat"], "lng": row["lng"], "score": row["distress_score"], "type": "voice"})
    except Exception:
        pass

    # Wandering events
    try:
        result = await session.execute(
            text("""
                SELECT lat, lng, wander_score FROM wandering_events
                WHERE created_at > :cutoff AND status != 'resolved'
                LIMIT 50
            """),
            {"cutoff": cutoff},
        )
        for row in result.mappings():
            incidents.append({"lat": row["lat"], "lng": row["lng"], "score": row["wander_score"], "type": "wander"})
    except Exception:
        pass

    return incidents


async def _fetch_safe_zones(session: AsyncSession, user_id: str) -> list[dict]:
    """Fetch user's safe zones."""
    try:
        from sqlalchemy import text
        result = await session.execute(
            text("SELECT name, center_lat, center_lng, radius_m FROM safe_zones WHERE user_id = :uid"),
            {"uid": user_id},
        )
        return [{"name": r["name"], "lat": r["center_lat"], "lng": r["center_lng"], "radius": r["radius_m"]} for r in result.mappings()]
    except Exception:
        return []


def _sample_route_points(geometry: list, interval_m: int = 200) -> list[dict]:
    """Sample points along a route geometry at regular intervals."""
    if not geometry or len(geometry) < 2:
        return []
    points = [{"lat": geometry[0][1], "lng": geometry[0][0]}]
    acc = 0.0
    for i in range(1, len(geometry)):
        d = _haversine(geometry[i - 1][1], geometry[i - 1][0], geometry[i][1], geometry[i][0])
        acc += d
        if acc >= interval_m:
            points.append({"lat": geometry[i][1], "lng": geometry[i][0]})
            acc = 0.0
    # Always include last point
    points.append({"lat": geometry[-1][1], "lng": geometry[-1][0]})
    return points


def _score_route_safety(
    route_points: list[dict],
    incidents: list[dict],
    safe_zones: list[dict],
    hour: int,
    route_distance_m: float,
    baseline_distance_m: float,
) -> dict:
    """
    Score a route for safety using the 4-factor formula.

    Returns: {score: 0-1 (lower is safer), details: {...}}
    """
    n = max(len(route_points), 1)

    # 1. Incident proximity (0-1, lower is safer)
    incident_scores = []
    for pt in route_points:
        pt_score = 0.0
        for inc in incidents:
            d = _haversine(pt["lat"], pt["lng"], inc["lat"], inc["lng"])
            if d < INCIDENT_RADIUS_M:
                proximity = 1.0 - (d / INCIDENT_RADIUS_M)
                pt_score = max(pt_score, proximity * inc.get("score", 0.5))
        incident_scores.append(pt_score)
    avg_incident = sum(incident_scores) / n if incident_scores else 0.0

    # 2. Safe zone proximity (0-1, lower means closer to safe zones = safer)
    zone_scores = []
    for pt in route_points:
        min_dist = SAFE_ZONE_RANGE_M
        for zone in safe_zones:
            d = _haversine(pt["lat"], pt["lng"], zone["lat"], zone["lng"])
            effective_dist = max(0, d - zone.get("radius", 0))
            min_dist = min(min_dist, effective_dist)
        zone_scores.append(min_dist / SAFE_ZONE_RANGE_M)
    avg_zone = sum(zone_scores) / n if zone_scores else 0.5

    # 3. Time-of-day risk (0-1)
    time_risk = TIME_RISK.get(hour, 0.5)

    # 4. Efficiency penalty (longer routes get slight penalty)
    if baseline_distance_m > 0:
        efficiency = min(1.0, (route_distance_m / baseline_distance_m - 1.0))
        efficiency = max(0.0, efficiency)
    else:
        efficiency = 0.0

    # Weighted composite
    composite = (
        W_INCIDENT * avg_incident +
        W_SAFE_ZONE * avg_zone +
        W_TIME_OF_DAY * time_risk +
        W_EFFICIENCY * efficiency
    )

    return {
        "score": round(min(1.0, max(0.0, composite)), 3),
        "details": {
            "incident_proximity": round(avg_incident, 3),
            "safe_zone_distance": round(avg_zone, 3),
            "time_of_day_risk": round(time_risk, 3),
            "efficiency_penalty": round(efficiency, 3),
            "incidents_near_route": sum(1 for s in incident_scores if s > 0),
            "safe_zones_near_route": sum(1 for s in zone_scores if s < 0.8),
        },
    }


async def suggest_reroute(
    session: AsyncSession,
    user_id: str,
    current_lat: float,
    current_lng: float,
    destination_lat: float | None = None,
    destination_lng: float | None = None,
    trigger_type: str = "manual",
    risk_score: float = 0.0,
    risk_level: str = "unknown",
    trigger_signals: dict | None = None,
    reason: str = "Manual reroute request",
) -> dict:
    """
    Compute a safer alternative route for a user.

    1. Fetch current route session (if active)
    2. Query OSRM for alternative routes
    3. Score each route for safety
    4. Pick the safest alternative
    5. Create a reroute suggestion record
    6. Broadcast SSE event
    """
    # Check cooldown
    if _check_cooldown(user_id):
        return {"status": "cooldown", "message": "Reroute suggestion already active. Wait 120s."}

    # Get active route session for destination
    route_session = _get_active_route_session(user_id)
    if destination_lat is None or destination_lng is None:
        if route_session and route_session.get("destination"):
            dest = route_session["destination"]
            destination_lat = dest.get("lat")
            destination_lng = dest.get("lng")
        elif route_session and route_session.get("route_coords"):
            # Use last point of route as destination
            last = route_session["route_coords"][-1]
            destination_lat, destination_lng = last[1], last[0]

    if destination_lat is None or destination_lng is None:
        return {"status": "error", "message": "No active route or destination. Cannot suggest reroute."}

    # Fetch OSRM alternatives from current position to destination
    from app.services.osrm_service import get_route
    osrm_data = await get_route(
        start_lng=current_lng, start_lat=current_lat,
        end_lng=destination_lng, end_lat=destination_lat,
        alternatives=3,
    )
    if osrm_data.get("code") != "Ok" or not osrm_data.get("routes"):
        return {"status": "error", "message": "Could not fetch alternative routes"}

    routes = osrm_data["routes"]
    if len(routes) < 2:
        return {"status": "no_alternatives", "message": "Only one route available — no safer alternative found"}

    # Fetch incident and safe zone data for scoring
    incidents = await _fetch_recent_incidents(session, hours=24)
    safe_zones = await _fetch_safe_zones(session, user_id)
    hour = datetime.now(timezone.utc).hour

    # Get baseline (current route) distance for efficiency comparison
    current_route_distance = routes[0]["distance"]

    # Score all routes
    scored_routes = []
    for i, route in enumerate(routes):
        coords = route["geometry"]["coordinates"]
        sampled = _sample_route_points(coords)
        safety = _score_route_safety(sampled, incidents, safe_zones, hour, route["distance"], current_route_distance)

        scored_routes.append({
            "index": i,
            "geometry": coords,
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "safety_score": safety["score"],
            "safety_details": safety["details"],
        })

    scores_str = ", ".join(f"{r['safety_score']:.3f}" for r in scored_routes)
    logger.info(f"Reroute scoring: {len(scored_routes)} routes, "
                f"scores=[{scores_str}], "
                f"incidents={len(incidents)}, safe_zones={len(safe_zones)}")

    # Route 0 from OSRM is the primary/current route
    current_route = scored_routes[0]
    # Sort alternatives by safety (lower is safer)
    alternatives = sorted(scored_routes[1:], key=lambda r: r["safety_score"])

    if not alternatives:
        return {"status": "no_alternatives", "message": "Only one route available — no safer alternative found"}

    safest_route = alternatives[0]

    # Only suggest if the safer route is meaningfully safer (>= 1% improvement)
    improvement = current_route["safety_score"] - safest_route["safety_score"]
    if improvement < 0.01:
        return {"status": "no_improvement", "message": "No significantly safer route available",
                "current_safety": current_route["safety_score"],
                "best_alternative_safety": safest_route["safety_score"]}

    # Calculate ETA change
    eta_change = safest_route["duration_s"] - routes[0]["duration"]  # vs fastest/current

    # Create DB record
    suggestion = RerouteSuggestion(
        user_id=uuid.UUID(user_id),
        trigger_risk_score=risk_score,
        trigger_risk_level=risk_level,
        trigger_type=trigger_type,
        trigger_signals=trigger_signals,
        reason=reason,
        current_route_risk=current_route["safety_score"] if current_route else None,
        current_location_lat=current_lat,
        current_location_lng=current_lng,
        destination_lat=destination_lat,
        destination_lng=destination_lng,
        suggested_route_geometry=safest_route["geometry"],
        suggested_route_risk=safest_route["safety_score"],
        suggested_route_distance_m=safest_route["distance_m"],
        suggested_route_duration_s=safest_route["duration_s"],
        eta_change_seconds=round(eta_change),
        safety_score_details=safest_route["safety_details"],
        status="pending",
    )
    session.add(suggestion)
    await session.commit()
    await session.refresh(suggestion)

    suggestion_id = str(suggestion.id)

    # Set cooldown
    _set_cooldown(user_id)

    # Broadcast SSE to guardian and operators
    sse_data = {
        "suggestion_id": suggestion_id,
        "user_id": user_id,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "reason": reason,
        "suggested_route": safest_route["geometry"],
        "suggested_route_risk": safest_route["safety_score"],
        "current_route_risk": current_route["safety_score"] if current_route else None,
        "distance_m": safest_route["distance_m"],
        "duration_s": safest_route["duration_s"],
        "eta_change_seconds": round(eta_change),
        "destination": {"lat": destination_lat, "lng": destination_lng},
        "current_location": {"lat": current_lat, "lng": current_lng},
        "safety_details": safest_route["safety_details"],
        "trigger_type": trigger_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(user_id, "safety_reroute_suggestion", sse_data)
    await broadcaster.broadcast_to_operators("safety_reroute_suggestion", sse_data)

    logger.warning(
        f"Reroute suggested: user={user_id}, trigger={trigger_type}, "
        f"risk={risk_score:.2f}, current_safety={current_route['safety_score'] if current_route else 'n/a':.3f}, "
        f"suggested_safety={safest_route['safety_score']:.3f}, eta_change={eta_change:.0f}s"
    )

    return {
        "status": "suggested",
        "suggestion_id": suggestion_id,
        "reason": reason,
        "current_route_risk": current_route["safety_score"] if current_route else None,
        "suggested_route_risk": safest_route["safety_score"],
        "suggested_route": safest_route["geometry"],
        "distance_m": safest_route["distance_m"],
        "duration_s": safest_route["duration_s"],
        "eta_change_seconds": round(eta_change),
        "safety_details": safest_route["safety_details"],
    }


async def approve_reroute(session: AsyncSession, suggestion_id: str, user_id: str) -> dict:
    """Guardian approves a reroute suggestion — switch active route."""
    result = await session.execute(
        select(RerouteSuggestion).where(
            RerouteSuggestion.id == uuid.UUID(suggestion_id),
        )
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        return {"error": "Suggestion not found"}
    if suggestion.status != "pending":
        return {"error": f"Suggestion already {suggestion.status}"}

    suggestion.status = "approved"
    suggestion.resolved_at = datetime.now(timezone.utc)
    await session.commit()

    # Broadcast approval SSE (to both guardian and senior device)
    sse_data = {
        "suggestion_id": suggestion_id,
        "user_id": str(suggestion.user_id),
        "status": "approved",
        "suggested_route": suggestion.suggested_route_geometry,
        "destination": {"lat": suggestion.destination_lat, "lng": suggestion.destination_lng},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(str(suggestion.user_id), "safety_reroute_approved", sse_data)
    await broadcaster.broadcast_to_operators("safety_reroute_approved", sse_data)

    logger.info(f"Reroute approved: suggestion={suggestion_id}, user={suggestion.user_id}")
    return {"status": "approved", "suggestion_id": suggestion_id}


async def dismiss_reroute(session: AsyncSession, suggestion_id: str, user_id: str) -> dict:
    """Guardian dismisses a reroute suggestion."""
    result = await session.execute(
        select(RerouteSuggestion).where(
            RerouteSuggestion.id == uuid.UUID(suggestion_id),
        )
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        return {"error": "Suggestion not found"}
    if suggestion.status != "pending":
        return {"error": f"Suggestion already {suggestion.status}"}

    suggestion.status = "dismissed"
    suggestion.resolved_at = datetime.now(timezone.utc)
    await session.commit()

    logger.info(f"Reroute dismissed: suggestion={suggestion_id}, user={suggestion.user_id}")
    return {"status": "dismissed", "suggestion_id": suggestion_id}


async def get_reroute_history(session: AsyncSession, user_id: str | None = None, limit: int = 20) -> list[dict]:
    """Fetch recent reroute suggestions."""
    q = select(RerouteSuggestion).order_by(RerouteSuggestion.created_at.desc()).limit(limit)
    if user_id:
        q = q.where(RerouteSuggestion.user_id == uuid.UUID(user_id))

    result = await session.execute(q)
    return [
        {
            "suggestion_id": str(s.id),
            "user_id": str(s.user_id),
            "trigger_risk_score": s.trigger_risk_score,
            "trigger_risk_level": s.trigger_risk_level,
            "trigger_type": s.trigger_type,
            "reason": s.reason,
            "current_route_risk": s.current_route_risk,
            "suggested_route_risk": s.suggested_route_risk,
            "distance_m": s.suggested_route_distance_m,
            "duration_s": s.suggested_route_duration_s,
            "eta_change_seconds": s.eta_change_seconds,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
        }
        for s in result.scalars().all()
    ]


# ── Safety Brain Integration Hook ──

async def on_risk_level_change(
    session: AsyncSession,
    user_id: str,
    risk_score: float,
    risk_level: str,
    signals: dict,
    lat: float,
    lng: float,
):
    """
    Called by Safety Brain when risk level is evaluated.
    Auto-triggers reroute suggestion when risk >= Dangerous (0.6).
    """
    if risk_score < AUTO_TRIGGER_THRESHOLD:
        return  # Not dangerous enough

    # Build reason from active signals
    active = [k for k, v in signals.items() if v > 0.1]
    reason = f"Safety Brain: {risk_level} ({risk_score:.0%}) — Active signals: {', '.join(active)}"

    try:
        result = await suggest_reroute(
            session=session,
            user_id=user_id,
            current_lat=lat,
            current_lng=lng,
            trigger_type="auto",
            risk_score=risk_score,
            risk_level=risk_level,
            trigger_signals=signals,
            reason=reason,
        )
        if result.get("status") == "suggested":
            logger.warning(f"Auto-reroute triggered: user={user_id}, risk={risk_score:.2f}")
        elif result.get("status") == "cooldown":
            pass  # Expected during rapid events
        else:
            logger.info(f"Auto-reroute skipped: {result.get('status')} — {result.get('message')}")
    except Exception as e:
        logger.error(f"Auto-reroute failed: {e}")
