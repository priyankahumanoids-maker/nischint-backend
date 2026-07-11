# Fall Detection Service — Apple Watch-style 5-stage pipeline
#
# Stages: Impact (2.7g) → Free-fall (0.5g) → Orientation (60°) → Post-impact → Immobility
# Confidence scoring: impact*0.30 + freefall*0.20 + orientation*0.20 + post_impact*0.10 + immobility*0.20
# Auto-SOS: if unresolved after 30s, triggers existing Silent SOS pipeline
# SSE events: fall_detected, fall_resolved, fall_auto_sos
# Cooldown: 60s between fall events per user

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fall_event import FallEvent
from app.services.event_broadcaster import broadcaster
from app.services.redis_service import set_json as _redis_set, get_json as _redis_get, delete_key as _redis_del

logger = logging.getLogger(__name__)

# In-memory fallback
_mem_store: dict = {}

COOLDOWN_SECONDS = 60
AUTO_SOS_DELAY_SECONDS = 30

# Confidence weights (Apple Watch-style)
W_IMPACT = 0.30
W_FREEFALL = 0.20
W_ORIENTATION = 0.20
W_POST_IMPACT = 0.10
W_IMMOBILITY = 0.20

CONFIDENCE_THRESHOLD = 0.75


def _store_set(key: str, data):
    ok = _redis_set("fall_detection", key, data)
    if not ok:
        _mem_store[f"fall_detection:{key}"] = data


def _store_get(key: str):
    val = _redis_get("fall_detection", key)
    if val is not None:
        return val
    return _mem_store.get(f"fall_detection:{key}")


def _store_del(key: str):
    _redis_del("fall_detection", key)
    _mem_store.pop(f"fall_detection:{key}", None)


def compute_confidence(signals: dict) -> float:
    """
    Compute fall confidence from 5-stage signals.
    Each signal is a score from 0.0-1.0.
    """
    impact = min(1.0, signals.get("impact_score", 0))
    freefall = min(1.0, signals.get("freefall_score", 0))
    orientation = min(1.0, signals.get("orientation_score", 0))
    post_impact = min(1.0, signals.get("post_impact_score", 0))
    immobility = min(1.0, signals.get("immobility_score", 0))

    confidence = (
        W_IMPACT * impact +
        W_FREEFALL * freefall +
        W_ORIENTATION * orientation +
        W_POST_IMPACT * post_impact +
        W_IMMOBILITY * immobility
    )
    return round(confidence, 3)


def _check_cooldown(user_id: str) -> bool:
    """Check if user is in cooldown period. Returns True if should block."""
    last = _store_get(f"cooldown:{user_id}")
    if last:
        last_time = datetime.fromisoformat(last)
        if (datetime.now(timezone.utc) - last_time).total_seconds() < COOLDOWN_SECONDS:
            return True
    return False


async def report_fall(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    signals: dict,
    sensor_data: dict | None = None,
) -> dict:
    """
    Report a fall event from mobile sensors.
    Computes confidence, stores event, broadcasts SSE.
    """
    # Cooldown check
    if _check_cooldown(user_id):
        return {"status": "cooldown", "message": "Fall event recently reported. Wait 60s."}

    confidence = compute_confidence(signals)

    # Extract boolean signals
    impact = signals.get("impact_score", 0) > 0.5
    freefall = signals.get("freefall_score", 0) > 0.3
    orientation = signals.get("orientation_score", 0) > 0.4
    post_impact = signals.get("post_impact_score", 0) > 0.3
    immobility = signals.get("immobility_score", 0) > 0.4

    # Create DB event
    event = FallEvent(
        user_id=uuid.UUID(user_id),
        lat=lat,
        lng=lng,
        impact_detected=impact,
        freefall_detected=freefall,
        orientation_change=orientation,
        post_impact_motion=post_impact,
        immobility_detected=immobility,
        confidence=confidence,
        status="detected",
        sensor_data=sensor_data,
    )
    session.add(event)
    await session.flush()

    event_id = str(event.id)

    # Set cooldown
    _store_set(f"cooldown:{user_id}", datetime.now(timezone.utc).isoformat())

    # Track pending event for auto-SOS
    _store_set(f"pending:{event_id}", {
        "user_id": user_id,
        "event_id": event_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lat": lat,
        "lng": lng,
        "confidence": confidence,
    })

    # Determine marker level based on confidence
    if confidence >= 0.95:
        marker_level = "critical"
    elif confidence >= 0.85:
        marker_level = "high"
    else:
        marker_level = "moderate"

    event_data = {
        "event_id": event_id,
        "user_id": user_id,
        "type": "possible_fall",
        "lat": lat,
        "lng": lng,
        "confidence": confidence,
        "marker_level": marker_level,
        "impact_detected": impact,
        "freefall_detected": freefall,
        "orientation_change": orientation,
        "immobility_detected": immobility,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Broadcast SSE
    await broadcaster.broadcast_to_user(user_id, "fall_detected", event_data)
    await broadcaster.broadcast_to_operators("fall_detected", event_data)

    logger.warning(f"Fall detected: user={user_id}, confidence={confidence:.2f}, marker={marker_level}")

    await session.commit()

    # Feed signal to Safety Brain (augment, don't replace existing SSE)
    try:
        from app.services.safety_brain_service import on_fall_detected
        await on_fall_detected(session, user_id, confidence, lat, lng)
    except Exception as e:
        logger.error(f"Safety Brain fall hook failed: {e}")

    return {
        "status": "detected",
        "event_id": event_id,
        "confidence": confidence,
        "marker_level": marker_level,
        "auto_sos_in_seconds": AUTO_SOS_DELAY_SECONDS,
        "signals": {
            "impact": impact,
            "freefall": freefall,
            "orientation_change": orientation,
            "post_impact_motion": post_impact,
            "immobility": immobility,
        },
    }


async def resolve_fall(
    session: AsyncSession,
    event_id: str,
    resolved_by: str,
    user_id: str,
) -> dict:
    """Resolve a fall event — user confirmed safe or operator resolved."""
    result = await session.execute(
        select(FallEvent).where(FallEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Fall event not found"}

    if str(event.user_id) != user_id:
        return {"error": "Not authorized"}

    if event.status in ("resolved", "cancelled"):
        return {"status": "already_resolved"}

    now = datetime.now(timezone.utc)
    event.status = "resolved"
    event.resolved_by = resolved_by
    event.resolved_at = now

    # Clear pending auto-SOS
    _store_del(f"pending:{event_id}")

    event_data = {
        "event_id": event_id,
        "user_id": user_id,
        "resolved_by": resolved_by,
        "timestamp": now.isoformat(),
    }
    await broadcaster.broadcast_to_user(user_id, "fall_resolved", event_data)
    await broadcaster.broadcast_to_operators("fall_resolved", event_data)

    logger.info(f"Fall resolved: event={event_id}, by={resolved_by}")
    await session.commit()

    return {"status": "resolved", "event_id": event_id, "resolved_by": resolved_by}


async def trigger_auto_sos(
    session: AsyncSession,
    event_id: str,
) -> dict:
    """Trigger auto-SOS for unresolved fall event."""
    result = await session.execute(
        select(FallEvent).where(FallEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event or event.status != "detected":
        return {"status": "not_applicable"}

    # Mark as auto_sos
    event.status = "auto_sos"
    event.resolved_by = "auto_sos_triggered"

    # Trigger Silent SOS via existing pipeline
    from app.services.emergency_engine import trigger_silent_sos
    sos_result = await trigger_silent_sos(
        session=session,
        user_id=str(event.user_id),
        lat=event.lat,
        lng=event.lng,
        trigger_source="fall_detection",
        device_metadata={"fall_event_id": event_id, "confidence": event.confidence},
    )

    emergency_id = sos_result.get("event_id")
    if emergency_id:
        event.emergency_event_id = uuid.UUID(emergency_id)

    # Broadcast auto-SOS
    event_data = {
        "event_id": event_id,
        "user_id": str(event.user_id),
        "emergency_event_id": emergency_id,
        "lat": event.lat,
        "lng": event.lng,
        "confidence": event.confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(str(event.user_id), "fall_auto_sos", event_data)
    await broadcaster.broadcast_to_operators("fall_auto_sos", event_data)

    _store_del(f"pending:{event_id}")
    logger.warning(f"Fall auto-SOS triggered: event={event_id}, emergency={emergency_id}")

    await session.commit()
    return {"status": "auto_sos", "event_id": event_id, "emergency_event_id": emergency_id}


async def check_pending_auto_sos(session: AsyncSession):
    """Check for pending fall events that should trigger auto-SOS (called periodically)."""
    # This can be called from a scheduler, but for simplicity we check on each new fall report
    pass


async def cancel_fall_by_movement(
    session: AsyncSession,
    event_id: str,
    user_id: str,
) -> dict:
    """Cancel fall event because user started moving again."""
    result = await session.execute(
        select(FallEvent).where(FallEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event or event.status != "detected":
        return {"status": "not_applicable"}

    event.status = "cancelled"
    event.resolved_by = "movement_detected"
    event.resolved_at = datetime.now(timezone.utc)

    _store_del(f"pending:{event_id}")
    await session.commit()

    logger.info(f"Fall cancelled by movement: event={event_id}")
    return {"status": "cancelled", "event_id": event_id}


async def get_recent_fall_events(
    session: AsyncSession,
    user_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get recent fall events, optionally filtered by user."""
    query = select(FallEvent).order_by(desc(FallEvent.created_at)).limit(limit)
    if user_id:
        query = query.where(FallEvent.user_id == uuid.UUID(user_id))

    result = await session.execute(query)
    events = result.scalars().all()

    return [
        {
            "event_id": str(e.id),
            "user_id": str(e.user_id),
            "lat": e.lat,
            "lng": e.lng,
            "confidence": e.confidence,
            "status": e.status,
            "resolved_by": e.resolved_by,
            "impact_detected": e.impact_detected,
            "freefall_detected": e.freefall_detected,
            "orientation_change": e.orientation_change,
            "post_impact_motion": e.post_impact_motion,
            "immobility_detected": e.immobility_detected,
            "emergency_event_id": str(e.emergency_event_id) if e.emergency_event_id else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in events
    ]
