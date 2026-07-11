# Wandering Detection Service
#
# Logic: User exits safe zone AND no active route AND movement continues away for >60s
# Wander score: distance_score*0.4 + time_score*0.4 + direction_score*0.2
# Escalation at wander_score >= 0.7
# SSE events: wandering_detected, wandering_resolved, wandering_escalated

import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safe_zone import SafeZone
from app.models.wandering_event import WanderingEvent
from app.services.event_broadcaster import broadcaster
from app.services.redis_service import set_json as _redis_set, get_json as _redis_get, delete_key as _redis_del

logger = logging.getLogger(__name__)

# In-memory fallback
_mem: dict = {}

WANDER_THRESHOLD = 0.7
MIN_TIME_OUTSIDE_S = 60
MAX_DISTANCE_NORM = 300  # meters for normalization
MAX_TIME_NORM = 180  # seconds for normalization
ESCALATION_DISTANCE_M = 300


def _set(key, data):
    ok = _redis_set("wandering", key, data)
    if not ok:
        _mem[f"wandering:{key}"] = data


def _get(key):
    v = _redis_get("wandering", key)
    return v if v is not None else _mem.get(f"wandering:{key}")


def _del(key):
    _redis_del("wandering", key)
    _mem.pop(f"wandering:{key}", None)


def _haversine(lat1, lng1, lat2, lng2) -> float:
    """Distance in meters between two points."""
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_direction(zone_lat, zone_lng, prev_lat, prev_lng, cur_lat, cur_lng) -> str:
    """Determine if user is moving away from, toward, or lateral to zone."""
    prev_dist = _haversine(zone_lat, zone_lng, prev_lat, prev_lng)
    cur_dist = _haversine(zone_lat, zone_lng, cur_lat, cur_lng)
    delta = cur_dist - prev_dist
    if delta > 5:
        return "away"
    elif delta < -5:
        return "toward"
    return "lateral"


def compute_wander_score(distance_m: float, time_outside_s: float, moving_away: bool) -> float:
    """Compute normalized wander score."""
    distance_score = min(distance_m / MAX_DISTANCE_NORM, 1.0)
    time_score = min(time_outside_s / MAX_TIME_NORM, 1.0)
    direction_score = 1.0 if moving_away else 0.0
    return round(distance_score * 0.4 + time_score * 0.4 + direction_score * 0.2, 3)


# ── Safe Zone CRUD ──

async def create_safe_zone(session: AsyncSession, user_id: str, name: str, lat: float, lng: float,
                           radius_m: float, zone_type: str) -> dict:
    zone = SafeZone(
        user_id=uuid.UUID(user_id), name=name, lat=lat, lng=lng,
        radius_m=radius_m, zone_type=zone_type, active=True,
    )
    session.add(zone)
    await session.flush()
    await session.commit()
    return _zone_dict(zone)


async def get_safe_zones(session: AsyncSession, user_id: str) -> list[dict]:
    result = await session.execute(
        select(SafeZone).where(SafeZone.user_id == uuid.UUID(user_id), SafeZone.active.is_(True))
    )
    return [_zone_dict(z) for z in result.scalars().all()]


async def delete_safe_zone(session: AsyncSession, zone_id: str, user_id: str) -> dict:
    result = await session.execute(
        select(SafeZone).where(SafeZone.id == uuid.UUID(zone_id), SafeZone.user_id == uuid.UUID(user_id))
    )
    zone = result.scalar_one_or_none()
    if not zone:
        return {"error": "Safe zone not found"}
    zone.active = False
    zone.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "deleted", "zone_id": zone_id}


def _zone_dict(z: SafeZone) -> dict:
    return {
        "zone_id": str(z.id), "user_id": str(z.user_id), "name": z.name,
        "lat": z.lat, "lng": z.lng, "radius_m": z.radius_m,
        "zone_type": z.zone_type, "active": z.active,
        "created_at": z.created_at.isoformat() if z.created_at else None,
    }


# ── Wandering Check ──

async def check_wandering(
    session: AsyncSession, user_id: str, lat: float, lng: float,
    speed: float = 0, heading: float = 0,
) -> dict:
    """Check user location against all active safe zones. Detect wandering."""
    # Skip if active route monitor exists
    from app.services.route_monitor_service import get_monitoring_session
    if get_monitoring_session(user_id):
        return {"status": "skip", "reason": "active_route_monitor"}

    zones = await get_safe_zones(session, user_id)
    if not zones:
        return {"status": "skip", "reason": "no_safe_zones"}

    # Check each zone
    closest_zone = None
    min_distance = float("inf")
    for z in zones:
        dist = _haversine(z["lat"], z["lng"], lat, lng)
        excess = dist - z["radius_m"]
        if excess < min_distance:
            min_distance = excess
            closest_zone = z

    if not closest_zone:
        return {"status": "inside_zone"}

    distance_from_zone = max(0, min_distance)

    # Inside any zone
    if distance_from_zone <= 0:
        # Clear any pending wandering state
        state = _get(f"state:{user_id}")
        if state:
            _del(f"state:{user_id}")
        return {"status": "inside_zone", "zone": closest_zone["name"]}

    # Outside zone — track state
    now = datetime.now(timezone.utc)
    state = _get(f"state:{user_id}")

    if not state:
        # First detection of being outside
        state = {
            "first_outside_at": now.isoformat(),
            "prev_lat": lat, "prev_lng": lng,
            "zone_id": closest_zone["zone_id"],
            "zone_name": closest_zone["name"],
            "zone_lat": closest_zone["lat"],
            "zone_lng": closest_zone["lng"],
        }
        _set(f"state:{user_id}", state)
        return {
            "status": "outside_zone",
            "zone": closest_zone["name"],
            "distance_m": round(distance_from_zone, 1),
            "time_outside_s": 0,
            "wander_score": 0,
            "message": "Tracking started — monitoring movement",
        }

    # Compute time outside
    first_outside = datetime.fromisoformat(state["first_outside_at"])
    time_outside_s = (now - first_outside).total_seconds()

    # Compute direction
    direction = _compute_direction(
        state.get("zone_lat", closest_zone["lat"]),
        state.get("zone_lng", closest_zone["lng"]),
        state.get("prev_lat", lat), state.get("prev_lng", lng),
        lat, lng,
    )
    moving_away = direction == "away"

    # Update state
    state["prev_lat"] = lat
    state["prev_lng"] = lng
    _set(f"state:{user_id}", state)

    # Not enough time yet
    if time_outside_s < MIN_TIME_OUTSIDE_S:
        score = compute_wander_score(distance_from_zone, time_outside_s, moving_away)
        return {
            "status": "outside_zone",
            "zone": closest_zone["name"],
            "distance_m": round(distance_from_zone, 1),
            "time_outside_s": round(time_outside_s, 1),
            "direction": direction,
            "wander_score": score,
            "message": "Monitoring — below time threshold",
        }

    # Compute wander score
    score = compute_wander_score(distance_from_zone, time_outside_s, moving_away)

    result = {
        "status": "outside_zone",
        "zone": closest_zone["name"],
        "zone_id": closest_zone["zone_id"],
        "distance_m": round(distance_from_zone, 1),
        "time_outside_s": round(time_outside_s, 1),
        "direction": direction,
        "wander_score": score,
    }

    if score >= WANDER_THRESHOLD:
        # Wandering detected — create event + broadcast
        event = WanderingEvent(
            user_id=uuid.UUID(user_id),
            safe_zone_id=uuid.UUID(closest_zone["zone_id"]),
            lat=lat, lng=lng,
            distance_from_zone=round(distance_from_zone, 1),
            time_outside_seconds=round(time_outside_s, 1),
            movement_direction=direction,
            wander_score=score,
            status="escalated" if distance_from_zone > ESCALATION_DISTANCE_M else "active",
        )
        session.add(event)
        await session.flush()
        event_id = str(event.id)

        sse_type = "wandering_escalated" if distance_from_zone > ESCALATION_DISTANCE_M else "wandering_detected"
        sse_data = {
            "event_id": event_id,
            "user_id": user_id,
            "safe_zone_name": closest_zone["name"],
            "zone_type": closest_zone.get("zone_type", "custom"),
            "lat": lat, "lng": lng,
            "distance_m": round(distance_from_zone, 1),
            "time_outside_s": round(time_outside_s, 1),
            "direction": direction,
            "wander_score": score,
            "timestamp": now.isoformat(),
        }
        await broadcaster.broadcast_to_user(user_id, sse_type, sse_data)
        await broadcaster.broadcast_to_operators(sse_type, sse_data)

        logger.warning(f"Wandering {sse_type}: user={user_id}, zone={closest_zone['name']}, "
                       f"dist={distance_from_zone:.0f}m, score={score:.2f}")

        # Clear state after triggering
        _del(f"state:{user_id}")
        await session.commit()

        # Feed signal to Safety Brain (augment, don't replace existing SSE)
        try:
            from app.services.safety_brain_service import on_wandering_detected
            await on_wandering_detected(session, user_id, score, lat, lng)
        except Exception as e:
            logger.error(f"Safety Brain wandering hook failed: {e}")

        result.update({
            "status": "wandering_detected",
            "event_id": event_id,
            "escalated": distance_from_zone > ESCALATION_DISTANCE_M,
        })

    return result


async def resolve_wandering(session: AsyncSession, event_id: str, user_id: str) -> dict:
    result = await session.execute(
        select(WanderingEvent).where(WanderingEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Wandering event not found"}
    if str(event.user_id) != user_id:
        return {"error": "Not authorized"}
    if event.status == "resolved":
        return {"status": "already_resolved"}

    event.status = "resolved"
    event.resolved_at = datetime.now(timezone.utc)
    await session.commit()

    sse_data = {
        "event_id": event_id, "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(user_id, "wandering_resolved", sse_data)
    await broadcaster.broadcast_to_operators("wandering_resolved", sse_data)

    logger.info(f"Wandering resolved: event={event_id}")
    return {"status": "resolved", "event_id": event_id}


async def get_wandering_events(session: AsyncSession, user_id: str | None = None, limit: int = 20) -> list[dict]:
    query = select(WanderingEvent).order_by(desc(WanderingEvent.created_at)).limit(limit)
    if user_id:
        query = query.where(WanderingEvent.user_id == uuid.UUID(user_id))
    result = await session.execute(query)
    return [
        {
            "event_id": str(e.id), "user_id": str(e.user_id),
            "safe_zone_id": str(e.safe_zone_id) if e.safe_zone_id else None,
            "lat": e.lat, "lng": e.lng,
            "distance_from_zone": e.distance_from_zone,
            "time_outside_seconds": e.time_outside_seconds,
            "movement_direction": e.movement_direction,
            "wander_score": e.wander_score,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in result.scalars().all()
    ]
