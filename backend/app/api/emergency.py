# Emergency API — Silent SOS endpoints
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session as get_session

router = APIRouter(prefix="/emergency", tags=["Emergency"])

# Rate limit config
SOS_USER_LIMIT = 5       # per user per minute
SOS_DEVICE_LIMIT = 5     # per device per minute
SOS_IP_LIMIT = 30        # per IP per minute (soft protection)
SOS_WINDOW = 60           # 60 seconds


class SilentSOSRequest(BaseModel):
    lat: float
    lng: float
    trigger_source: str = "hidden_button"
    cancel_pin: str | None = None
    device_metadata: dict | None = None


class LocationUpdateRequest(BaseModel):
    event_id: str
    lat: float
    lng: float


class CancelRequest(BaseModel):
    event_id: str
    cancel_pin: str


class ResolveRequest(BaseModel):
    event_id: str


class SMSFallbackRequest(BaseModel):
    lat: float
    lng: float
    trigger_source: str = "offline_fallback"


def _rate_limit_headers(result) -> dict:
    """Build X-RateLimit-* headers from a RateLimitResult."""
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_at),
    }


@router.post("/silent-sos")
async def silent_sos(
    req: SilentSOSRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    from app.services.redis_service import check_rate_limit
    from app.services.emergency_engine import get_active_emergencies, update_emergency_location, trigger_silent_sos

    user_id = str(user.id)

    # ── Capability-based role gating (explicit map, not role sets).
    # Only roles where CAN_TRIGGER_SOS[role] is True may emit SOS events.
    # Designed to prevent role-explosion bugs: new roles default to false
    # (must be explicitly whitelisted) rather than "anything not in a set".
    CAN_TRIGGER_SOS = {
        "child":    True,
        "kid":      True,
        "woman":    True,
        "elderly":  True,
        "senior":   True,
        "guardian": False,
        "parent":   False,
        "operator": False,
        "admin":    False,
    }
    user_role = (getattr(user, "role", None) or "").lower()
    if not CAN_TRIGGER_SOS.get(user_role, False):
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user_role or 'unknown'}' cannot trigger SOS. Only protected users (child/woman/elderly) may emit emergency events.",
        )

    # ── Critical UX Rule: if active emergency exists, return it (never block panicking user) ──
    active = await get_active_emergencies(session=session, user_id=user_id)
    if active:
        existing = active[0]
        # Update location on the existing event (user pressing again = location update)
        await update_emergency_location(
            session=session,
            event_id=existing["event_id"],
            lat=req.lat,
            lng=req.lng,
        )
        result = {
            **existing,
            "message": "Active emergency already exists. Location updated.",
            "is_existing": True,
        }
        return JSONResponse(content=result, headers={
            "X-RateLimit-Limit": str(SOS_USER_LIMIT),
            "X-RateLimit-Remaining": "N/A",
            "X-RateLimit-Reset": "N/A",
        })

    # ── Multi-layer rate limiting (only for NEW emergency creation) ──
    # 1. Per-user
    user_rl = check_rate_limit("sos:user", user_id, SOS_USER_LIMIT, SOS_WINDOW)
    if not user_rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: max 5 SOS triggers per minute per user",
            headers=_rate_limit_headers(user_rl),
        )

    # 2. Per-device (from device_metadata or user-agent)
    device_id = None
    if req.device_metadata:
        device_id = req.device_metadata.get("device_id") or req.device_metadata.get("platform")
    if not device_id:
        device_id = request.headers.get("user-agent", "unknown")[:64]
    device_rl = check_rate_limit("sos:device", device_id, SOS_DEVICE_LIMIT, SOS_WINDOW)
    if not device_rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: max 5 SOS triggers per minute per device",
            headers=_rate_limit_headers(device_rl),
        )

    # 3. Per-IP (soft protection — higher limit)
    client_ip = request.client.host if request.client else "unknown"
    ip_rl = check_rate_limit("sos:ip", client_ip, SOS_IP_LIMIT, SOS_WINDOW)
    if not ip_rl.allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: too many requests from this IP",
            headers=_rate_limit_headers(ip_rl),
        )

    # ── Create new emergency ──
    result = await trigger_silent_sos(
        session=session,
        user_id=user_id,
        lat=req.lat,
        lng=req.lng,
        trigger_source=req.trigger_source,
        cancel_pin=req.cancel_pin,
        device_metadata=req.device_metadata,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return JSONResponse(content=result, headers=_rate_limit_headers(user_rl))


@router.post("/location-update")
async def location_update(
    req: LocationUpdateRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    from app.services.emergency_engine import update_emergency_location
    result = await update_emergency_location(
        session=session,
        event_id=req.event_id,
        lat=req.lat,
        lng=req.lng,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/cancel")
async def cancel_sos(
    req: CancelRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    from app.services.emergency_engine import cancel_emergency
    from app.models.emergency import EmergencyEvent
    import uuid as _uuid

    # ── Ownership enforcement: only the user who OWNS the event (or an operator) may cancel it.
    # Prevents token misuse / cross-account cancellation even with a leaked PIN.
    try:
        ev_row = await session.execute(
            select(EmergencyEvent).where(EmergencyEvent.id == _uuid.UUID(req.event_id))
        )
        ev = ev_row.scalar_one_or_none()
    except Exception:
        ev = None
    if ev is None:
        raise HTTPException(status_code=404, detail="Emergency event not found")
    caller_role = (getattr(user, "role", None) or "").lower()
    if str(ev.user_id) != str(user.id) and caller_role != "operator":
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to cancel this emergency event.",
        )

    result = await cancel_emergency(
        session=session,
        event_id=req.event_id,
        cancel_pin=req.cancel_pin,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/resolve")
async def resolve_sos(
    req: ResolveRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    from app.services.emergency_engine import resolve_emergency
    result = await resolve_emergency(session=session, event_id=req.event_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/active")
async def get_active(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    from app.services.emergency_engine import get_active_emergencies
    # Operators see all, users see their own
    user_filter = None if user.role == "operator" else str(user.id)
    events = await get_active_emergencies(session=session, user_id=user_filter)
    return {"events": events, "count": len(events)}


@router.get("/status/{event_id}")
async def get_status(
    event_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    from app.services.emergency_engine import get_emergency_details
    result = await get_emergency_details(session=session, event_id=event_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── SMS Fallback (last-resort delivery when API-driven SOS cannot be confirmed) ──
# Idempotent: per user, at most ONE fallback SMS per 10-minute window.
# Sends to all linked guardians using the existing Twilio integration.

SMS_FALLBACK_WINDOW_SEC = 600  # 10 minutes — one fallback SMS per user per window


@router.post("/sms-fallback")
async def sms_fallback(
    req: SMSFallbackRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """
    Last-resort SMS delivery when the mobile client cannot confirm an active
    SOS event via the normal API path. Sends a single SMS per linked guardian.
    Safe to call multiple times — idempotent within SMS_FALLBACK_WINDOW_SEC.
    """
    import uuid as _uuid
    from sqlalchemy import select
    from app.services.redis_service import get_json, set_json
    from app.models.guardian import Guardian

    user_id = str(user.id)

    # ── Idempotency guard ──
    idem_key = f"{user_id}"
    existing = get_json("sos:sms_fallback", idem_key)
    if existing:
        return {
            "sent": 0,
            "skipped": True,
            "reason": "already_sent_recently",
            "sent_at": existing.get("sent_at"),
        }

    # Fetch linked guardians
    try:
        res = await session.execute(
            select(Guardian).where(
                Guardian.user_id == _uuid.UUID(user_id),
                Guardian.is_active.is_(True),
            )
        )
        guardians = res.scalars().all()
    except Exception:
        guardians = []

    user_name = (user.full_name or (user.email or "Your loved one").split("@")[0]).strip()
    maps_url = f"https://maps.google.com/?q={req.lat:.6f},{req.lng:.6f}"
    body = (
        "🚨 SOS ALERT\n\n"
        f"{user_name} may be in danger.\n\n"
        "Last known location:\n"
        f"{maps_url}\n\n"
        "Unable to reach via internet. Please act immediately."
    )

    sent_count = 0
    phones_sent: list[str] = []
    from app.services.sms_service import send_sms
    for g in guardians:
        if not g.phone:
            continue
        prefs = g.notification_pref or {}
        # Respect SMS preference but DEFAULT to sending (safety-first)
        if prefs.get("sms", True) is False:
            continue
        try:
            ok = send_sms(g.phone, body)
            if ok:
                sent_count += 1
                phones_sent.append(g.phone[-4:])  # last-4 for audit only
        except Exception:
            # Never raise — fallback must degrade gracefully
            continue

    # Persist idempotency marker regardless of success
    # (prevents SMS-storm if Twilio is flaky and user keeps retrying)
    set_json(
        "sos:sms_fallback",
        idem_key,
        {
            "sent_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "sent_count": sent_count,
            "trigger_source": req.trigger_source,
        },
        ttl=SMS_FALLBACK_WINDOW_SEC,
    )

    return {
        "sent": sent_count,
        "skipped": False,
        "guardians_matched": len(guardians),
        "phones_last4": phones_sent,
    }
