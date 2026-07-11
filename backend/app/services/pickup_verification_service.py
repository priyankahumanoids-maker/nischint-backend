# Pickup Verification Service
#
# Create authorization → generate code → verify (code + proximity) → SSE broadcast
# Security: secrets-based code, hashlib hashing, 10-min expiry, 5-attempt rate limit

import hashlib
import logging
import math
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pickup_authorization import PickupAuthorization
from app.models.pickup_event import PickupEvent
from app.services.event_broadcaster import broadcaster
from app.services.redis_service import set_json as _redis_set, get_json as _redis_get

logger = logging.getLogger(__name__)

# In-memory fallback for rate limiting
_mem: dict = {}

EXPIRY_MINUTES = 10
MAX_VERIFY_ATTEMPTS = 5


def _rate_key(auth_id: str) -> str:
    return f"pickup_rate:{auth_id}"


def _rate_set(key, data):
    ok = _redis_set("pickup", key, data)
    if not ok:
        _mem[f"pickup:{key}"] = data


def _rate_get(key):
    v = _redis_get("pickup", key)
    return v if v is not None else _mem.get(f"pickup:{key}")


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _generate_code() -> tuple[str, str]:
    """Generate cryptographically random 6-digit code. Returns (raw, hash)."""
    raw = str(secrets.randbelow(1_000_000)).zfill(6)
    return raw, _hash_code(raw)


def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def create_authorization(
    session: AsyncSession,
    guardian_id: str,
    user_id: str,
    authorized_person_name: str,
    authorized_person_phone: str | None,
    verification_method: str,
    pickup_location_lat: float,
    pickup_location_lng: float,
    pickup_radius_m: float,
    pickup_location_name: str | None,
    scheduled_time: datetime,
) -> dict:
    """Create pickup authorization. Returns raw code for guardian to share."""
    raw_code, code_hash = _generate_code()

    expires_at = scheduled_time + timedelta(minutes=EXPIRY_MINUTES)

    auth = PickupAuthorization(
        user_id=uuid.UUID(user_id),
        guardian_id=uuid.UUID(guardian_id),
        authorized_person_name=authorized_person_name,
        authorized_person_phone=authorized_person_phone,
        verification_method=verification_method,
        pickup_code_hash=code_hash,
        pickup_location_lat=pickup_location_lat,
        pickup_location_lng=pickup_location_lng,
        pickup_radius_m=pickup_radius_m,
        pickup_location_name=pickup_location_name,
        scheduled_time=scheduled_time,
        expires_at=expires_at,
        status="pending",
    )
    session.add(auth)
    await session.flush()
    auth_id = str(auth.id)

    # Broadcast SSE
    sse_data = {
        "authorization_id": auth_id,
        "user_id": user_id,
        "authorized_person": authorized_person_name,
        "location": pickup_location_name or f"{pickup_location_lat:.4f}, {pickup_location_lng:.4f}",
        "scheduled_time": scheduled_time.isoformat(),
        "verification_method": verification_method,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcaster.broadcast_to_user(guardian_id, "pickup_scheduled", sse_data)
    await broadcaster.broadcast_to_operators("pickup_scheduled", sse_data)

    await session.commit()
    logger.info(f"Pickup authorization created: {auth_id}, person={authorized_person_name}")

    return {
        "authorization_id": auth_id,
        "pickup_code": raw_code,
        "verification_method": verification_method,
        "expires_at": expires_at.isoformat(),
        "pickup_location_name": pickup_location_name,
        "status": "pending",
    }


async def verify_pickup(
    session: AsyncSession,
    authorization_id: str,
    pickup_code: str,
    lat: float,
    lng: float,
) -> dict:
    """Verify a pickup attempt. Checks code + proximity."""
    # Rate limit
    rate_key = _rate_key(authorization_id)
    attempts = _rate_get(rate_key) or 0
    if isinstance(attempts, int) and attempts >= MAX_VERIFY_ATTEMPTS:
        return {"status": "rate_limited", "message": "Too many attempts. Max 5 allowed."}

    _rate_set(rate_key, (attempts if isinstance(attempts, int) else 0) + 1)

    result = await session.execute(
        select(PickupAuthorization).where(PickupAuthorization.id == uuid.UUID(authorization_id))
    )
    auth = result.scalar_one_or_none()
    if not auth:
        return {"status": "not_found", "message": "Authorization not found"}

    now = datetime.now(timezone.utc)
    user_id = str(auth.user_id)
    guardian_id = str(auth.guardian_id)

    # Check already verified
    if auth.status == "verified":
        return {"status": "already_verified"}

    # Check expired
    if now > auth.expires_at or auth.status == "expired":
        if auth.status != "expired":
            auth.status = "expired"
            auth.updated_at = now
        event = PickupEvent(
            authorization_id=auth.id, lat=lat, lng=lng,
            verification_method=auth.verification_method,
            verification_result="expired", verified=False,
        )
        session.add(event)
        await session.commit()
        await _broadcast_failure(guardian_id, user_id, authorization_id, "code_expired", auth)
        return {"status": "expired", "message": "Pickup code has expired"}

    # Check cancelled
    if auth.status == "cancelled":
        return {"status": "cancelled", "message": "Authorization was cancelled"}

    # Proximity check
    distance = _haversine(auth.pickup_location_lat, auth.pickup_location_lng, lat, lng)
    if distance > auth.pickup_radius_m:
        event = PickupEvent(
            authorization_id=auth.id, lat=lat, lng=lng,
            verification_method=auth.verification_method,
            verification_result="proximity_failed", verified=False,
        )
        session.add(event)
        await session.commit()
        await _broadcast_failure(guardian_id, user_id, authorization_id, "proximity_failed", auth, distance)
        return {
            "status": "proximity_failed",
            "message": f"Too far from pickup location ({distance:.0f}m, max {auth.pickup_radius_m:.0f}m)",
            "distance_m": round(distance, 1),
        }

    # Code verification
    if _hash_code(pickup_code) != auth.pickup_code_hash:
        event = PickupEvent(
            authorization_id=auth.id, lat=lat, lng=lng,
            verification_method=auth.verification_method,
            verification_result="invalid_code", verified=False,
        )
        session.add(event)
        await session.commit()
        await _broadcast_failure(guardian_id, user_id, authorization_id, "invalid_code", auth)
        return {"status": "invalid_code", "message": "Invalid pickup code"}

    # SUCCESS
    auth.status = "verified"
    auth.updated_at = now

    event = PickupEvent(
        authorization_id=auth.id, lat=lat, lng=lng,
        verification_method=auth.verification_method,
        verification_result="success", verified=True, verified_at=now,
    )
    session.add(event)

    sse_data = {
        "authorization_id": authorization_id,
        "user_id": user_id,
        "authorized_person": auth.authorized_person_name,
        "location": auth.pickup_location_name or f"{lat:.4f}, {lng:.4f}",
        "status": "verified",
        "distance_m": round(distance, 1),
        "timestamp": now.isoformat(),
    }
    await broadcaster.broadcast_to_user(guardian_id, "pickup_verified", sse_data)
    await broadcaster.broadcast_to_operators("pickup_verified", sse_data)

    logger.info(f"Pickup verified: auth={authorization_id}, person={auth.authorized_person_name}")
    await session.commit()

    return {
        "status": "verified",
        "authorization_id": authorization_id,
        "authorized_person": auth.authorized_person_name,
        "distance_m": round(distance, 1),
        "verified_at": now.isoformat(),
    }


async def _broadcast_failure(guardian_id, user_id, auth_id, reason, auth, distance=None):
    sse_data = {
        "authorization_id": auth_id,
        "user_id": user_id,
        "reason": reason,
        "authorized_person": auth.authorized_person_name,
        "location": auth.pickup_location_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if distance is not None:
        sse_data["distance_m"] = round(distance, 1)
    await broadcaster.broadcast_to_user(guardian_id, "pickup_failed", sse_data)
    await broadcaster.broadcast_to_operators("pickup_failed", sse_data)

    # Feed pickup anomaly to Safety Brain (augment, don't replace existing SSE)
    # Score: expired=0.3, invalid_code=0.6, proximity_failed=0.4
    anomaly_scores = {"code_expired": 0.3, "invalid_code": 0.6, "proximity_failed": 0.4}
    anomaly_score = anomaly_scores.get(reason, 0.3)
    lat = auth.pickup_location_lat
    lng = auth.pickup_location_lng
    try:
        from app.db.session import async_session
        from app.services.safety_brain_service import on_pickup_anomaly
        async with async_session() as db_session:
            await on_pickup_anomaly(db_session, user_id, anomaly_score, lat, lng)
    except Exception as e:
        logger.error(f"Safety Brain pickup hook failed: {e}")


async def cancel_authorization(session: AsyncSession, auth_id: str, guardian_id: str) -> dict:
    result = await session.execute(
        select(PickupAuthorization).where(
            PickupAuthorization.id == uuid.UUID(auth_id),
            PickupAuthorization.guardian_id == uuid.UUID(guardian_id),
        )
    )
    auth = result.scalar_one_or_none()
    if not auth:
        return {"error": "Authorization not found"}
    if auth.status in ("verified", "cancelled"):
        return {"status": f"already_{auth.status}"}
    auth.status = "cancelled"
    auth.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "cancelled", "authorization_id": auth_id}


async def get_authorizations(session: AsyncSession, guardian_id: str, status: str | None = None) -> list[dict]:
    query = select(PickupAuthorization).where(
        PickupAuthorization.guardian_id == uuid.UUID(guardian_id)
    ).order_by(desc(PickupAuthorization.created_at)).limit(30)
    if status:
        query = query.where(PickupAuthorization.status == status)
    result = await session.execute(query)
    return [_auth_dict(a) for a in result.scalars().all()]


async def get_pickup_events(session: AsyncSession, guardian_id: str | None = None, limit: int = 20) -> list[dict]:
    if guardian_id:
        # Get auth IDs for this guardian
        auths = await session.execute(
            select(PickupAuthorization.id).where(PickupAuthorization.guardian_id == uuid.UUID(guardian_id))
        )
        auth_ids = [a[0] for a in auths.fetchall()]
        if not auth_ids:
            return []
        query = select(PickupEvent).where(PickupEvent.authorization_id.in_(auth_ids))
    else:
        query = select(PickupEvent)
    query = query.order_by(desc(PickupEvent.created_at)).limit(limit)
    result = await session.execute(query)
    return [
        {
            "event_id": str(e.id),
            "authorization_id": str(e.authorization_id),
            "lat": e.lat, "lng": e.lng,
            "verification_method": e.verification_method,
            "verification_result": e.verification_result,
            "verified": e.verified,
            "verified_at": e.verified_at.isoformat() if e.verified_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars().all()
    ]


def _auth_dict(a: PickupAuthorization) -> dict:
    return {
        "authorization_id": str(a.id),
        "user_id": str(a.user_id),
        "guardian_id": str(a.guardian_id),
        "authorized_person_name": a.authorized_person_name,
        "authorized_person_phone": a.authorized_person_phone,
        "verification_method": a.verification_method,
        "pickup_location_lat": a.pickup_location_lat,
        "pickup_location_lng": a.pickup_location_lng,
        "pickup_radius_m": a.pickup_radius_m,
        "pickup_location_name": a.pickup_location_name,
        "scheduled_time": a.scheduled_time.isoformat() if a.scheduled_time else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "status": a.status,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
