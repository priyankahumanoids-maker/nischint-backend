# Route Monitor Service — Live route deviation detection & safety escalation
#
# Architecture (per user's design):
#   1. Corridor generated at route creation → stored in Redis
#   2. Active routes + deviation state in Redis (horizontally scalable)
#   3. Separate SSE events per escalation level: route_warning, route_alert, route_emergency
#
# Escalation levels:
#   L1 Warning:   distance > 30m  AND duration > 10s
#   L2 Alert:     distance > 60m  AND duration > 30s  AND risk elevated
#   L3 Emergency: distance > 120m AND duration > 60s  AND night_guardian active

import logging
from datetime import datetime, timezone
from shapely.geometry import LineString, Point, shape

from app.services.event_broadcaster import broadcaster
from app.services.redis_service import set_json as _redis_set, get_json as _redis_get, delete_key as _redis_del

logger = logging.getLogger(__name__)

# In-memory fallback when Redis is unavailable (preview/dev)
_mem_store: dict[str, dict] = {}


def _store_set(namespace: str, key: str, data):
    full_key = f"{namespace}:{key}"
    ok = _redis_set(namespace, key, data)
    if not ok:
        _mem_store[full_key] = data


def _store_get(namespace: str, key: str):
    full_key = f"{namespace}:{key}"
    val = _redis_get(namespace, key)
    if val is not None:
        return val
    return _mem_store.get(full_key)


def _store_del(namespace: str, key: str):
    full_key = f"{namespace}:{key}"
    _redis_del(namespace, key)
    _mem_store.pop(full_key, None)

# Corridor widths by mode (meters)
CORRIDOR_WIDTH_M = {
    "fastest": 40,
    "balanced": 35,
    "safest": 30,
    "night_guardian": 25,
}

# Escalation thresholds
L1_DISTANCE_M = 30
L1_DURATION_S = 10
L2_DISTANCE_M = 60
L2_DURATION_S = 30
L3_DISTANCE_M = 120
L3_DURATION_S = 60

MAX_TRAIL_POINTS = 200
CONSECUTIVE_OFF_TRIGGER = 2  # min consecutive off-route checks

CACHE_PREFIX = "route_monitor"
DEVIATION_PREFIX = "route_deviation"


# ── Corridor Generation ──

def generate_corridor(route_coords: list[list[float]], mode: str = "balanced") -> dict:
    """
    Convert route polyline to a buffered corridor polygon.
    route_coords: [[lng, lat], ...]
    Returns GeoJSON polygon.
    """
    if len(route_coords) < 2:
        return None

    width_m = CORRIDOR_WIDTH_M.get(mode, 35)
    width_deg = width_m / 111_000

    line = LineString(route_coords)
    corridor = line.buffer(width_deg, cap_style="round", join_style="round")
    coords = list(corridor.exterior.coords)

    return {
        "type": "Polygon",
        "coordinates": [[[c[0], c[1]] for c in coords]],
        "properties": {"width_m": width_m, "mode": mode},
    }


def is_inside_corridor(lat: float, lng: float, corridor_geojson: dict) -> tuple[bool, float]:
    """Check if point is inside corridor. Returns (inside, distance_m from corridor edge)."""
    point = Point(lng, lat)
    corridor_shape = shape(corridor_geojson)
    inside = corridor_shape.contains(point)
    if inside:
        return (True, 0.0)
    dist_m = round(corridor_shape.exterior.distance(point) * 111_000, 1)
    return (False, dist_m)


def distance_from_route(lat: float, lng: float, route_coords: list[list[float]]) -> float:
    """Distance (meters) from point to the route line itself."""
    if len(route_coords) < 2:
        return 0.0
    line = LineString(route_coords)
    point = Point(lng, lat)
    return round(line.distance(point) * 111_000, 1)


# ── Route Session Management ──

async def start_route_monitoring(
    user_id: str,
    route_coords: list[list[float]],
    mode: str,
    destination: dict,
    route_risk_score: float,
) -> dict:
    """Start monitoring a user's route. Generates corridor and stores in Redis."""
    corridor = generate_corridor(route_coords, mode)
    if not corridor:
        return {"error": "Cannot generate corridor from route"}

    now = datetime.now(timezone.utc).isoformat()

    session_data = {
        "user_id": user_id,
        "mode": mode,
        "corridor": corridor,
        "route_coords": route_coords,
        "destination": destination,
        "route_risk_score": route_risk_score,
        "trail": [],
        "status": "active",
        "started_at": now,
        "last_update": now,
    }

    # Deviation state — separate for clean tracking
    deviation_state = {
        "off_route_count": 0,
        "off_route_since": None,
        "escalation_level": 0,
        "last_escalation_at": None,
        "total_deviations": 0,
        "max_distance_m": 0,
    }

    _store_set(CACHE_PREFIX, user_id, session_data)
    _store_set(DEVIATION_PREFIX, user_id, deviation_state)

    width_m = CORRIDOR_WIDTH_M.get(mode, 35)
    logger.info(f"Route monitoring started: user={user_id}, mode={mode}, corridor={width_m}m")

    return {
        "status": "monitoring",
        "user_id": user_id,
        "corridor": corridor,
        "corridor_width_m": width_m,
        "mode": mode,
        "started_at": now,
    }


async def stop_route_monitoring(user_id: str) -> dict:
    """Stop monitoring a user's route. Returns journey summary."""
    session = _store_get(CACHE_PREFIX, user_id)
    deviation = _store_get(DEVIATION_PREFIX, user_id)
    if not session:
        return {"error": "No active route monitoring session"}

    _store_del(CACHE_PREFIX, user_id)
    _store_del(DEVIATION_PREFIX, user_id)
    logger.info(f"Route monitoring stopped: user={user_id}")

    return {
        "status": "stopped",
        "user_id": user_id,
        "total_trail_points": len(session.get("trail", [])),
        "max_escalation": deviation.get("escalation_level", 0) if deviation else 0,
        "total_deviations": deviation.get("total_deviations", 0) if deviation else 0,
        "max_distance_m": deviation.get("max_distance_m", 0) if deviation else 0,
        "duration_s": _compute_duration(session),
    }


def _compute_duration(session: dict) -> float:
    started = session.get("started_at")
    if not started:
        return 0
    start_dt = datetime.fromisoformat(started)
    return round((datetime.now(timezone.utc) - start_dt).total_seconds(), 1)


# ── Location Update + Deviation Detection ──

async def process_location_update(user_id: str, lat: float, lng: float) -> dict:
    """
    Process a GPS update. Checks corridor, detects deviations, escalates.
    Emits separate SSE events per escalation level.
    """
    session = _store_get(CACHE_PREFIX, user_id)
    if not session or session.get("status") != "active":
        return {"error": "No active monitoring session"}

    deviation = _store_get(DEVIATION_PREFIX, user_id) or {
        "off_route_count": 0,
        "off_route_since": None,
        "escalation_level": 0,
        "last_escalation_at": None,
        "total_deviations": 0,
        "max_distance_m": 0,
    }

    now = datetime.now(timezone.utc)
    corridor = session["corridor"]
    inside, distance_m = is_inside_corridor(lat, lng, corridor)

    # Distance from actual route line (more precise for escalation)
    route_distance_m = distance_from_route(lat, lng, session.get("route_coords", []))

    # Update trail
    trail = session.get("trail", [])
    trail.append({
        "lat": lat,
        "lng": lng,
        "ts": now.isoformat(),
        "inside": inside,
        "distance_m": distance_m,
    })
    if len(trail) > MAX_TRAIL_POINTS:
        trail = trail[-MAX_TRAIL_POINTS:]

    result = {
        "inside_corridor": inside,
        "distance_from_corridor_m": distance_m,
        "distance_from_route_m": route_distance_m,
        "escalation_level": deviation.get("escalation_level", 0),
        "trail_length": len(trail),
    }

    if inside:
        # Back on route — reset deviation state
        prev_level = deviation.get("escalation_level", 0)
        if prev_level > 0:
            logger.info(f"User {user_id} returned to safe corridor (was L{prev_level})")
            await broadcaster.broadcast_to_user(user_id, "route_back_on_track", {
                "event": "BACK_ON_TRACK",
                "user_id": user_id,
                "lat": lat,
                "lng": lng,
                "previous_level": prev_level,
            })
            await broadcaster.broadcast_to_operators("route_back_on_track", {
                "event": "BACK_ON_TRACK",
                "user_id": user_id,
                "lat": lat,
                "lng": lng,
                "previous_level": prev_level,
            })

        deviation.update({
            "off_route_count": 0,
            "off_route_since": None,
            "escalation_level": 0,
        })
        result["status"] = "on_route"

    else:
        # Off route — detect + escalate
        off_count = deviation.get("off_route_count", 0) + 1
        deviation["off_route_count"] = off_count

        if not deviation.get("off_route_since"):
            deviation["off_route_since"] = now.isoformat()
            deviation["total_deviations"] = deviation.get("total_deviations", 0) + 1

        deviation["max_distance_m"] = max(deviation.get("max_distance_m", 0), route_distance_m)

        off_since = datetime.fromisoformat(deviation["off_route_since"])
        off_duration_s = (now - off_since).total_seconds()

        # Risk comparison
        from app.services.risk_forecast_engine import get_point_forecast_cached
        area_risk = 5.0
        cached = get_point_forecast_cached(lat, lng)
        if cached and cached.get("risk_score") is not None:
            area_risk = cached["risk_score"]
        route_risk = session.get("route_risk_score", 5.0)
        risk_elevated = area_risk > route_risk

        # Night guardian active check
        is_night_mode = session.get("mode") == "night_guardian"

        # Determine escalation level
        prev_level = deviation.get("escalation_level", 0)
        new_level = 0

        if off_count >= CONSECUTIVE_OFF_TRIGGER:
            if route_distance_m >= L3_DISTANCE_M and off_duration_s >= L3_DURATION_S:
                new_level = 3
            elif route_distance_m >= L2_DISTANCE_M and off_duration_s >= L2_DURATION_S and risk_elevated:
                new_level = 3 if is_night_mode else 2
            elif route_distance_m >= L1_DISTANCE_M and off_duration_s >= L1_DURATION_S:
                new_level = 2 if (risk_elevated or is_night_mode) else 1
            else:
                new_level = prev_level  # maintain current level

        # Never downgrade during active deviation
        new_level = max(new_level, prev_level)
        deviation["escalation_level"] = new_level

        result.update({
            "status": "off_route",
            "escalation_level": new_level,
            "off_route_duration_s": round(off_duration_s, 1),
            "area_risk": area_risk,
            "route_risk": route_risk,
            "risk_elevated": risk_elevated,
            "is_night_mode": is_night_mode,
        })

        # Emit SSE on escalation change (separate event types per level)
        if new_level >= 1 and new_level > prev_level:
            deviation["last_escalation_at"] = now.isoformat()

            event_data = {
                "user_id": user_id,
                "lat": lat,
                "lng": lng,
                "distance_from_corridor_m": distance_m,
                "distance_from_route_m": route_distance_m,
                "escalation_level": new_level,
                "off_route_duration_s": round(off_duration_s, 1),
                "area_risk": area_risk,
                "route_risk": route_risk,
                "risk_elevated": risk_elevated,
                "is_night_mode": is_night_mode,
            }

            # Separate SSE event types per escalation level
            if new_level == 1:
                event_type = "route_warning"
                event_data["recommended_action"] = "return_to_corridor"
                event_data["alert_type"] = "minor_deviation"
            elif new_level == 2:
                event_type = "route_alert"
                event_data["recommended_action"] = "suggest_reroute"
                event_data["alert_type"] = "unsafe_deviation"
            else:
                event_type = "route_emergency"
                event_data["recommended_action"] = "guardian_alert"
                event_data["alert_type"] = "critical_deviation"

            await broadcaster.broadcast_to_user(user_id, event_type, event_data)
            await broadcaster.broadcast_to_operators(event_type, event_data)
            logger.warning(
                f"Route {event_type} L{new_level}: user={user_id}, "
                f"dist={route_distance_m}m, risk={area_risk}"
            )

            # Feed signal to Safety Brain (augment, don't replace existing SSE)
            # Normalize escalation level to 0-1 score: L1=0.4, L2=0.7, L3=1.0
            deviation_score = {1: 0.4, 2: 0.7, 3: 1.0}.get(new_level, 0.3)
            try:
                from app.db.session import async_session
                from app.services.safety_brain_service import on_route_deviation
                async with async_session() as db_session:
                    await on_route_deviation(db_session, user_id, deviation_score, lat, lng)
            except Exception as e:
                logger.error(f"Safety Brain route hook failed: {e}")

    session["trail"] = trail
    session["last_update"] = now.isoformat()
    _store_set(CACHE_PREFIX, user_id, session)
    _store_set(DEVIATION_PREFIX, user_id, deviation)
    return result


def get_monitoring_session(user_id: str) -> dict | None:
    """Get active route monitoring session with deviation state."""
    session = _store_get(CACHE_PREFIX, user_id)
    if not session:
        return None
    deviation = _store_get(DEVIATION_PREFIX, user_id) or {}
    return {
        **session,
        "escalation_level": deviation.get("escalation_level", 0),
        "off_route_count": deviation.get("off_route_count", 0),
        "total_deviations": deviation.get("total_deviations", 0),
        "max_distance_m": deviation.get("max_distance_m", 0),
    }


# ── Legacy operator functions (backward compat stubs) ──

async def assign_route_monitor(session, device_id, route_data, route_index=0,
                                start_lat=0, start_lng=0, end_lat=0, end_lng=0):
    """Stub for legacy operator route monitoring."""
    from sqlalchemy import text
    coords = []
    if route_data and isinstance(route_data, dict):
        geom = route_data.get("geometry", {})
        coords = geom.get("coordinates", [])
    if not coords:
        return {"error": "No route coordinates provided"}

    await session.execute(text("""
        INSERT INTO active_route_monitors (device_id, route_data, status, start_lat, start_lng, end_lat, end_lng)
        VALUES (:did, :rd, 'active', :slat, :slng, :elat, :elng)
        ON CONFLICT (device_id, status) WHERE status = 'active'
        DO UPDATE SET route_data = :rd, start_lat = :slat, start_lng = :slng, end_lat = :elat, end_lng = :elng
    """), {"did": device_id, "rd": str(route_data), "slat": start_lat, "slng": start_lng, "elat": end_lat, "elng": end_lng})
    await session.commit()
    return {"status": "monitoring", "device_id": device_id}


async def get_device_route_status(session, device_id):
    """Stub for legacy device route status."""
    from sqlalchemy import text
    row = await session.execute(text(
        "SELECT * FROM active_route_monitors WHERE device_id = :did AND status = 'active'"
    ), {"did": device_id})
    r = row.fetchone()
    if not r:
        return None
    return {"device_id": device_id, "status": "active", "monitor_id": str(r.id)}


async def get_fleet_route_monitors(session):
    """Stub for legacy fleet monitors."""
    from sqlalchemy import text
    rows = await session.execute(text(
        "SELECT device_id, status FROM active_route_monitors WHERE status = 'active'"
    ))
    return [{"device_id": r.device_id, "status": r.status} for r in rows.fetchall()]


async def suggest_reroute(session, device_id):
    return {"status": "no_reroute", "message": "Use consumer route monitoring for rerouting"}


async def accept_reroute(session, device_id, route_data):
    return {"status": "not_supported", "message": "Use consumer route monitoring"}


async def recalculate_route_risk(session, device_id):
    return {"status": "not_supported", "message": "Use consumer route monitoring"}
