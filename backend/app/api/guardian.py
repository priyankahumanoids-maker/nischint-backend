# Guardian Mode API — Live safety sharing with trusted contacts
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.api.deps import get_db_session, get_current_user
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian", tags=["guardian"])


class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy: Optional[float] = None
    name: Optional[str] = Field(None, max_length=240)


class AddGuardianRequest(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    relationship: str = "family"


class StartSessionRequest(BaseModel):
    location: LocationInput
    destination: Optional[LocationInput] = None


class UpdateLocationRequest(BaseModel):
    session_id: str
    location: LocationInput
    timestamp: Optional[str] = None


# ── Guardian CRUD ──

@router.post("/add")
async def add_guardian(
    req: AddGuardianRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import add_guardian as add_g
    return await add_g(session, str(user.id), req.name, req.phone, req.email, req.relationship)


@router.get("/list")
async def list_guardians(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import list_guardians as list_g
    guardians = await list_g(session, str(user.id))
    return {"guardians": guardians}


@router.delete("/remove/{guardian_id}")
async def remove_guardian(
    guardian_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import remove_guardian as remove_g
    result = await remove_g(session, guardian_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ── Session Management ──

@router.post("/start")
async def start_session(
    req: StartSessionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import start_session as start_s
    return await start_s(
        session, str(user.id), req.location.lat, req.location.lng,
        dest_lat=req.destination.lat if req.destination else None,
        dest_lng=req.destination.lng if req.destination else None,
        dest_name=req.destination.name if req.destination else None,
    )


class SessionIdRequest(BaseModel):
    session_id: str


@router.post("/stop")
async def stop_session(
    req: SessionIdRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import stop_session as stop_s
    result = await stop_s(session, req.session_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/session/{session_id}")
async def get_session(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import get_session as get_s
    result = await get_s(session, session_id)
    if not result:
        raise HTTPException(404, "Session not found")
    return result


@router.get("/sessions/active")
async def list_active_sessions(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import get_active_sessions
    if user.role != "operator":
        raise HTTPException(403, "Operator access required")
    return {"sessions": await get_active_sessions(session)}


@router.get("/sessions/history")
async def get_user_history(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import get_user_sessions
    return {"sessions": await get_user_sessions(session, str(user.id))}


# ── Location Updates ──

@router.post("/update-location")
async def update_location(
    req: UpdateLocationRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    logger.info(f"GPS_UPDATE_RECEIVED user={user.id} session={req.session_id} lat={req.location.lat} lng={req.location.lng}")
    from app.services.guardian_mode_engine import update_location as update_l
    from app.services.shadow_tracking import shadow_ping
    ts = None
    if req.timestamp:
        try:
            ts = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass
    result = await update_l(session, req.session_id, req.location.lat, req.location.lng, ts,
                              accuracy=req.location.accuracy)

    # NISCH-002B: piggyback the user's `last_known_*` so co-location
    # suppression has fresh data. Best-effort — never blocks the ping.
    try:
        from app.services.user_presence import update_last_known
        await update_last_known(
            session, user.id,
            req.location.lat, req.location.lng,
            ts=ts,
        )
    except Exception as _e:
        logger.debug(f"[NISCH-002B] last_known update failed (non-fatal): {_e}")
    # Stale packet (Invariant #2): server-clock comparison rejected
    # this as out-of-order. Drop silently — no shadow, no event.
    if result.get("stale"):
        return {"stale": True}
    if "error" in result:
        # Shadow-tracking failsafe: even when the session layer can't
        # honor the ping, we still capture (user_id, lat, lng, ts) so
        # we have a forensic trail and a recovery path. Tracking must
        # NEVER drop on a session-layer fault.
        err = result["error"]
        next_action = None
        if err == "No active session":
            shadow_source = "no_session"
            next_action = "start_new_session"
        elif "completed" in err:
            shadow_source = "session_age_cap" if "Session is completed" in err else "session_ended"
            # 24-hour zombie cap — client MUST rotate to a new session,
            # otherwise it's permanently in shadow. We surface the
            # signal explicitly; the policy decision (auto-create vs
            # ask-the-guardian) lives on the client where the journey
            # context (destination, intent) is known.
            next_action = "start_new_session"
        elif "ended" in err:
            shadow_source = "session_ended"
            # User explicitly ended the journey — only rotate if the
            # client wants to start a fresh one.
            next_action = "start_new_session"
        else:
            shadow_source = "no_session"
            next_action = "start_new_session"
        await shadow_ping(
            session, user.id, req.location.lat, req.location.lng,
            source=shadow_source, session_id=req.session_id, ts=ts,
        )
        logger.warning(
            f"GPS_UPDATE_REJECTED session={req.session_id} reason={err} "
            f"→ recorded to shadow_location_pings (source={shadow_source})"
        )
        # Don't 4xx — the trail was captured. Tell the client what
        # happened so it can rotate to a new session if needed.
        return {
            "shadow":      True,
            "reason":      err,
            "source":      shadow_source,
            "next_action": next_action,
        }
    return result


@router.post("/acknowledge-safety")
async def acknowledge_safety(
    req: SessionIdRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.guardian_mode_engine import acknowledge_safety as ack_s
    return await ack_s(session, req.session_id)



# ── Step 7: Journey Polyline (decision support for guardians) ──
# Reads from `journey_points` (append-only, NOT a state source per
# Invariant #1). Returns ordered points + last point + a stale flag
# so the mobile/web client can grey out the line when the device's
# GPS stream has gone quiet.
@router.get("/{session_id}/polyline")
async def get_session_polyline(
    session_id: str,
    limit: int = 1000,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Return the GPS trail for a session as an ordered polyline.

    Authorization: the session owner OR any guardian linked to the
    owner (same logic the dashboard uses) OR an operator.
    """
    import uuid
    from sqlalchemy import select, text
    from app.models.guardian import GuardianSession, JourneyPoint

    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(400, "Invalid session_id")

    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == sid)
    )).scalar_one_or_none()
    if gs is None:
        raise HTTPException(404, "Session not found")

    # AuthZ: owner / operator / linked guardian.
    is_owner = (gs.user_id == user.id)
    is_operator = (user.role == "operator")
    if not (is_owner or is_operator):
        # Linked-guardian check via Guardian table (email match).
        link = await session.execute(
            text(
                """SELECT 1
                     FROM guardians g
                     JOIN users u ON u.email = g.email
                    WHERE g.user_id = :child AND u.id = :viewer
                    LIMIT 1"""
            ),
            {"child": str(gs.user_id), "viewer": str(user.id)},
        )
        if link.scalar() is None:
            raise HTTPException(403, "Not authorized for this session")

    # Cap to keep payload sane. seq is monotonic per session.
    capped = max(1, min(int(limit or 1000), 5000))
    rows = (await session.execute(
        select(JourneyPoint)
        .where(JourneyPoint.session_id == sid)
        .order_by(JourneyPoint.seq.asc())
        .limit(capped)
    )).scalars().all()

    points = [
        {
            "seq":     int(p.seq),
            "lat":     float(p.lat),
            "lng":     float(p.lng),
            "ts":      p.server_received_at.isoformat() if p.server_received_at else None,
            "quality": p.quality,
            "gap_s":   int(p.gap_before_s) if p.gap_before_s is not None else None,
        }
        for p in rows
    ]

    # Stale-flag: server-clock based (Invariant #2). We use the
    # session's `previous_update_at` (the actual GPS arrival time
    # on the server) rather than the last point's `ts` so this stays
    # consistent with the watchdog's view of the world.
    now = datetime.now(timezone.utc)
    last_ping_at = gs.previous_update_at
    stale_seconds = (
        int((now - last_ping_at).total_seconds()) if last_ping_at else None
    )
    is_stale = bool(gs.is_offline) or (
        stale_seconds is not None and stale_seconds >= 30
    )

    return {
        "session_id":     str(sid),
        "user_id":        str(gs.user_id),
        "status":         gs.status,
        "is_offline":     bool(gs.is_offline),
        "is_stale":       is_stale,
        "stale_seconds":  stale_seconds,
        "last_seen_online_at": (
            gs.last_seen_online_at.isoformat() if gs.last_seen_online_at else None
        ),
        "total_points":   int(gs.total_points or 0),
        "offline_gaps":   int(gs.offline_gaps or 0),
        "max_gap_seconds": int(gs.max_gap_seconds or 0),
        "points":         points,
        "last_point":     points[-1] if points else None,
        "returned":       len(points),
        "limit":          capped,
        "truncated":      len(points) >= capped and (gs.total_points or 0) > capped,
    }
