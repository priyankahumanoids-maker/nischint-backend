# Safety Event API — Mobile-ready unified safety endpoints
# Consolidates SOS, sessions, risk, routes, alerts, location sharing, fake calls
import uuid as uuid_mod
import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.roles import require_role
from app.models.user import User
from app.models.guardian import GuardianSession, GuardianAlert
from app.models.guardian_network import GuardianRelationship

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/safety-events", tags=["Safety Events"])

# ── Rate Limiting ──
_rate_limits = defaultdict(list)  # user_id -> [timestamps]
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMITS = {
    "share-location": 60,   # 60 calls per minute
    "risk-score": 20,       # 20 calls per minute
    "safe-route": 10,       # 10 calls per minute
}


def _check_rate_limit(user_id: str, endpoint: str):
    limit = RATE_LIMITS.get(endpoint)
    if not limit:
        return
    key = f"{user_id}:{endpoint}"
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[key]) >= limit:
        raise HTTPException(429, f"Rate limit exceeded: max {limit} requests per minute")
    _rate_limits[key].append(now)


# ── Schemas ──

class SOSRequest(BaseModel):
    trigger_type: str = Field("manual", pattern="^(manual|voice|button|shake|auto)$")
    lat: Optional[float] = None
    lng: Optional[float] = None
    message: Optional[str] = None


class StartSessionRequest(BaseModel):
    destination: Optional[dict] = None  # {lat, lng, name}
    route_points: Optional[List[dict]] = None  # [{lat, lng}]
    mode: str = Field("walking", pattern="^(walking|driving|transit)$")


class EndSessionRequest(BaseModel):
    reason: str = Field("arrived", pattern="^(arrived|cancelled|emergency|timeout)$")


class ShareLocationRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heading: Optional[float] = None
    battery_pct: Optional[int] = None


class SafeRouteRequest(BaseModel):
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lng: float = Field(..., ge=-180, le=180)
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lng: float = Field(..., ge=-180, le=180)


class FakeCallRequest(BaseModel):
    caller_name: str = Field("Mom", max_length=120)
    delay_seconds: int = Field(3, ge=0, le=60)


# ── 1. SOS ──

@router.post("/sos")
async def trigger_sos(
    body: SOSRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Trigger SOS with location. Notifies guardian network and command center."""
    from app.services import sos_service as svc

    result = await svc.trigger_sos(
        session, user.id,
        trigger_type=body.trigger_type,
        lat=body.lat, lng=body.lng,
    )

    # Notify guardian network
    guardians = (await session.execute(
        select(GuardianRelationship)
        .where(and_(
            GuardianRelationship.user_id == user.id,
            GuardianRelationship.is_active == True,
        ))
        .order_by(GuardianRelationship.priority)
    )).scalars().all()

    notified = []
    for g in guardians:
        notified.append({
            "name": g.guardian_name,
            "relationship": g.relationship_type,
            "channels": g.notification_channels,
            "priority": g.priority,
        })

    result["guardian_notifications"] = notified
    result["guardians_notified"] = len(notified)

    # Push notifications + email alerts to guardians
    try:
        from app.services.notification_service import NotificationService
        from app.services.email_service import send_sos_alert_email
        from app.db.session import async_session

        ns = NotificationService(async_session)
        guardian_ids = [str(g.guardian_user_id) for g in guardians if g.guardian_user_id]
        await ns.send_sos_notification(
            user_id=str(user.id),
            user_name=user.full_name or user.email,
            location={"lat": body.lat, "lng": body.lng} if body.lat else None,
            guardian_ids=guardian_ids,
        )
        # Email alerts
        for g in guardians:
            if g.guardian_email:
                send_sos_alert_email(
                    to_email=g.guardian_email,
                    user_name=user.full_name or user.email,
                    location={"lat": body.lat, "lng": body.lng} if body.lat else None,
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Push/email notification error: {e}")

    # Emit via real-time event pipeline
    from app.api.realtime_events import emit_sos_triggered
    try:
        await emit_sos_triggered(str(user.id), result)
    except Exception:
        pass

    return result


# ── 2. Start Session ──

@router.post("/start-session")
async def start_session(
    body: StartSessionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Start a safety tracking session."""
    # Check for existing active session
    existing = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user.id,
            GuardianSession.status == "active",
        ))
    )).scalar_one_or_none()

    if existing:
        return {
            "status": "already_active",
            "session_id": str(existing.id),
            "started_at": existing.started_at.isoformat(),
            "message": "An active session already exists",
        }

    gs = GuardianSession(
        user_id=user.id,
        status="active",
        destination=body.destination,
        route_points=body.route_points,
        risk_level="SAFE",
        risk_score=0.0,
    )
    session.add(gs)
    await session.commit()
    await session.refresh(gs)

    # Push notification to guardians about session start
    try:
        from app.services.notification_service import NotificationService
        from app.db.session import async_session
        ns = NotificationService(async_session)
        guardians = (await session.execute(
            select(GuardianRelationship)
            .where(and_(
                GuardianRelationship.user_id == user.id,
                GuardianRelationship.is_active == True,
            ))
        )).scalars().all()
        guardian_ids = [str(g.guardian_user_id) for g in guardians if g.guardian_user_id]
        dest_str = f" to {body.destination}" if body.destination else ""
        await ns.send_session_alert(
            user_id=str(user.id),
            session_event="started",
            details=f"{user.full_name or user.email} started a safety session{dest_str}.",
            guardian_ids=guardian_ids,
        )
    except Exception as e:
        logger.debug(f"Session start push notification skipped: {e}")

    return {
        "status": "started",
        "session_id": str(gs.id),
        "started_at": gs.started_at.isoformat(),
        "risk_level": gs.risk_level,
        "destination": gs.destination,
    }


# ── 3. End Session ──

@router.post("/end-session")
async def end_session(
    body: EndSessionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """End the current safety tracking session."""
    gs = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user.id,
            GuardianSession.status == "active",
        ))
    )).scalar_one_or_none()

    if not gs:
        raise HTTPException(404, "No active session found")

    now = datetime.now(timezone.utc)
    gs.status = "completed" if body.reason == "arrived" else body.reason
    gs.ended_at = now
    duration = int((now - gs.started_at).total_seconds()) if gs.started_at else 0
    await session.commit()

    # Push notification to guardians about session end
    try:
        from app.services.notification_service import NotificationService
        from app.db.session import async_session
        ns = NotificationService(async_session)
        guardians = (await session.execute(
            select(GuardianRelationship)
            .where(and_(
                GuardianRelationship.user_id == user.id,
                GuardianRelationship.is_active == True,
            ))
        )).scalars().all()
        guardian_ids = [str(g.guardian_user_id) for g in guardians if g.guardian_user_id]
        await ns.send_session_alert(
            user_id=str(user.id),
            session_event="ended",
            details=f"{user.full_name or user.email}'s safety session ended ({body.reason}). Duration: {duration // 60}m.",
            guardian_ids=guardian_ids,
        )
    except Exception as e:
        logger.debug(f"Session end push notification skipped: {e}")

    return {
        "status": "ended",
        "session_id": str(gs.id),
        "reason": body.reason,
        "duration_seconds": duration,
        "total_distance_m": round(gs.total_distance_m, 1),
        "alert_count": gs.alert_count,
        "ended_at": now.isoformat(),
    }


# ── 4. Risk Score ──

@router.get("/risk-score")
async def get_risk_score(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get current AI risk score for the user."""
    _check_rate_limit(str(user.id), "risk-score")

    from app.services.guardian_ai_refinement import compute_risk_score

    score = await compute_risk_score(session, user.id)
    return score


# ── 5. Safe Route ──

@router.post("/safe-route")
async def get_safe_route(
    body: SafeRouteRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get safety assessment for a route."""
    _check_rate_limit(str(user.id), "safe-route")

    from app.services.safe_route_engine import generate_safe_routes

    result = await generate_safe_routes(
        session,
        body.origin_lat, body.origin_lng,
        body.dest_lat, body.dest_lng,
    )
    return result


# ── 6. Guardian Alerts ──

@router.get("/guardian-alerts")
async def get_guardian_alerts(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get alerts for the user's guardian network (alerts about people they protect)."""
    # Find users this person is a guardian of
    guarded_user_ids = (await session.execute(
        select(GuardianRelationship.user_id)
        .where(and_(
            GuardianRelationship.guardian_user_id == user.id,
            GuardianRelationship.is_active == True,
        ))
    )).scalars().all()

    # Also include own alerts
    all_user_ids = list(set([user.id] + list(guarded_user_ids)))

    # Get active sessions for these users
    active_sessions = (await session.execute(
        select(GuardianSession.id)
        .where(and_(
            GuardianSession.user_id.in_(all_user_ids),
            GuardianSession.status == "active",
        ))
    )).scalars().all()

    # Get recent alerts from these sessions
    if active_sessions:
        alerts = (await session.execute(
            select(GuardianAlert)
            .where(GuardianAlert.session_id.in_(active_sessions))
            .order_by(desc(GuardianAlert.created_at))
            .limit(limit)
        )).scalars().all()
    else:
        alerts = []

    # Also get recent alerts from any session of guarded users (last 24h)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_sessions = (await session.execute(
        select(GuardianSession.id)
        .where(and_(
            GuardianSession.user_id.in_(all_user_ids),
            GuardianSession.started_at >= cutoff,
        ))
    )).scalars().all()

    if recent_sessions:
        recent_alerts = (await session.execute(
            select(GuardianAlert)
            .where(and_(
                GuardianAlert.session_id.in_(recent_sessions),
                GuardianAlert.created_at >= cutoff,
            ))
            .order_by(desc(GuardianAlert.created_at))
            .limit(limit)
        )).scalars().all()
    else:
        recent_alerts = []

    # Merge and dedupe
    seen = set()
    merged = []
    for a in list(alerts) + list(recent_alerts):
        if a.id not in seen:
            seen.add(a.id)
            merged.append({
                "id": str(a.id),
                "session_id": str(a.session_id),
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "recommendation": a.recommendation,
                "location": a.location,
                "created_at": a.created_at.isoformat(),
            })
    merged.sort(key=lambda x: x["created_at"], reverse=True)

    return {"alerts": merged[:limit], "total": len(merged[:limit])}


# ── 7. Share Location ──

@router.post("/share-location")
async def share_location(
    body: ShareLocationRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Share real-time location update during active session."""
    _check_rate_limit(str(user.id), "share-location")

    gs = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user.id,
            GuardianSession.status == "active",
        ))
    )).scalar_one_or_none()

    if not gs:
        raise HTTPException(404, "No active session. Start a session first.")

    now = datetime.now(timezone.utc)

    # Calculate distance from previous location
    distance_delta = 0.0
    if gs.current_location:
        prev = gs.current_location
        import math
        dlat = math.radians(body.lat - prev.get("lat", body.lat))
        dlng = math.radians(body.lng - prev.get("lng", body.lng))
        a = math.sin(dlat/2)**2 + math.cos(math.radians(prev.get("lat", 0))) * math.cos(math.radians(body.lat)) * math.sin(dlng/2)**2
        distance_delta = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # Update session
    gs.previous_location = gs.current_location
    gs.previous_update_at = now
    gs.current_location = {
        "lat": body.lat,
        "lng": body.lng,
        "accuracy_m": body.accuracy_m,
        "heading": body.heading,
        "battery_pct": body.battery_pct,
        "updated_at": now.isoformat(),
    }
    gs.speed_mps = body.speed_mps or 0.0
    gs.total_distance_m += distance_delta
    gs.location_updates += 1
    await session.commit()

    # Emit via real-time event pipeline
    from app.api.realtime_events import emit_location_update
    try:
        await emit_location_update(str(user.id), body.lat, body.lng, str(gs.id))
    except Exception:
        pass

    # Phase 3 — Live deviation engine: compute live drift from baseline and
    # broadcast `twin_delta` over WS to operators only when status changes.
    try:
        from app.services.twin_delta_broadcaster import maybe_broadcast_twin_delta
        await maybe_broadcast_twin_delta(
            session,
            user.id,
            lat=body.lat,
            lng=body.lng,
            route_deviated=bool(gs.route_deviated),
            route_deviation_m=float(gs.route_deviation_m or 0),
            is_idle=bool(gs.is_idle),
            idle_duration_s=float(gs.idle_duration_s or 0),
        )
    except Exception:
        pass

    # Phase 5 — emit structured COMMAND_CENTER_DELTA for `live_location.*`
    try:
        from app.services.cc_delta_emitter import emit_namespaced_delta
        await emit_namespaced_delta(
            str(user.id),
            "live_location",
            {
                "lat": float(body.lat),
                "lng": float(body.lng),
                "speed_mps": float(gs.speed_mps or 0),
                "speed_kmh": round(float(gs.speed_mps or 0) * 3.6, 1),
                "zone_name": gs.zone_name,
                "risk_level": gs.risk_level,
                "route_deviated": bool(gs.route_deviated),
                "route_deviation_m": round(float(gs.route_deviation_m or 0), 1),
                "is_idle": bool(gs.is_idle),
                "idle_duration_s": float(gs.idle_duration_s or 0),
                "session_id": str(gs.id),
            },
        )
    except Exception:
        pass

    # Truth Layer hardening — record the data-pipeline heartbeat. Any
    # endpoint that proves "the device is online and pushing" should
    # call this so the operator console can distinguish "stale location"
    # from "broken pipeline".
    try:
        from app.services.redis_service import mark_user_ping
        mark_user_ping(str(user.id), now.isoformat())
    except Exception:
        pass

    return {
        "status": "updated",
        "session_id": str(gs.id),
        "location_update_count": gs.location_updates,
        "total_distance_m": round(gs.total_distance_m, 1),
        "risk_level": gs.risk_level,
        "risk_score": gs.risk_score,
    }


# ── 8. Session Status ──

@router.get("/session-status")
async def get_session_status(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get current session status, risk score, and duration."""
    gs = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user.id,
            GuardianSession.status == "active",
        ))
    )).scalar_one_or_none()

    if not gs:
        return {
            "tracking_active": False,
            "session_id": None,
            "current_risk_score": 0.0,
            "risk_level": "SAFE",
            "session_duration_s": 0,
        }

    now = datetime.now(timezone.utc)
    duration = int((now - gs.started_at).total_seconds()) if gs.started_at else 0

    return {
        "tracking_active": True,
        "session_id": str(gs.id),
        "current_risk_score": gs.risk_score,
        "risk_level": gs.risk_level,
        "session_duration_s": duration,
        "started_at": gs.started_at.isoformat(),
        "current_location": gs.current_location,
        "total_distance_m": round(gs.total_distance_m, 1),
        "location_updates": gs.location_updates,
        "alert_count": gs.alert_count,
        "is_night": gs.is_night,
        "route_deviated": gs.route_deviated,
        "speed_mps": gs.speed_mps,
        "destination": gs.destination,
    }


# ── 9. Fake Call ──

@router.post("/fake-call")
async def trigger_fake_call(
    body: FakeCallRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Trigger a fake incoming call for escape scenarios."""
    from app.services import fake_call_service as svc

    result = await svc.trigger_fake_call(
        session, user.id,
        preset_id=None,
        caller_name=body.caller_name,
        delay_seconds=body.delay_seconds,
        trigger_method="safety_api",
        lat=None, lng=None,
    )
    return result


# ── 10. User Dashboard (single-call home screen) ──

@router.get("/user-dashboard")
async def user_dashboard(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Single API call for mobile home dashboard — risk, session, guardians, last alert, location."""
    from app.services.guardian_ai_refinement import compute_risk_score
    from app.models.guardian_network import GuardianRelationship, EmergencyContact

    # Run all queries in parallel
    gs_q = session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user.id,
            GuardianSession.status == "active",
        ))
    )
    guardian_count_q = session.execute(
        select(func.count()).where(and_(
            GuardianRelationship.user_id == user.id,
            GuardianRelationship.is_active == True,
        ))
    )
    emergency_count_q = session.execute(
        select(func.count()).where(and_(
            EmergencyContact.user_id == user.id,
            EmergencyContact.is_active == True,
        ))
    )
    last_alert_q = session.execute(
        select(GuardianAlert)
        .join(GuardianSession, GuardianAlert.session_id == GuardianSession.id)
        .where(GuardianSession.user_id == user.id)
        .order_by(desc(GuardianAlert.created_at))
        .limit(1)
    )

    gs_result, g_count_result, e_count_result, alert_result = await asyncio.gather(
        gs_q, guardian_count_q, emergency_count_q, last_alert_q,
    )

    active_session = gs_result.scalar_one_or_none()
    guardian_count = g_count_result.scalar() or 0
    emergency_count = e_count_result.scalar() or 0
    last_alert_row = alert_result.scalar_one_or_none()

    # Compute risk score (can be slow, so wrap in try)
    risk = None
    try:
        risk = await compute_risk_score(session, user.id)
    except Exception:
        pass

    # Build response
    now = datetime.now(timezone.utc)
    session_data = None
    if active_session:
        duration = int((now - active_session.started_at).total_seconds()) if active_session.started_at else 0
        session_data = {
            "session_id": str(active_session.id),
            "started_at": active_session.started_at.isoformat(),
            "duration_seconds": duration,
            "risk_level": active_session.risk_level,
            "total_distance_m": round(active_session.total_distance_m, 1),
            "alert_count": active_session.alert_count,
        }

    last_alert = None
    if last_alert_row:
        last_alert = {
            "alert_type": last_alert_row.alert_type,
            "severity": last_alert_row.severity,
            "message": last_alert_row.message,
            "created_at": last_alert_row.created_at.isoformat(),
        }

    current_location = None
    if active_session and active_session.current_location:
        current_location = active_session.current_location

    # Threat assessment (reuse cached endpoint)
    threat = None
    try:
        from app.api.guardian_ai_v2 import _threat_cache
        if _threat_cache["data"]:
            t = _threat_cache["data"]
            threat = {"level": t["threat_level"], "summary": t["summary"]}
    except Exception:
        pass

    return {
        "user_id": str(user.id),
        "email": user.email,
        "risk_score": risk.get("final_score", 0) if risk else 0,
        "risk_level": risk.get("risk_level", "low") if risk else "low",
        "session_active": active_session is not None,
        "session": session_data,
        "guardian_count": guardian_count,
        "emergency_contact_count": emergency_count,
        "last_alert": last_alert,
        "current_location": current_location,
        "threat_assessment": threat,
        "timestamp": now.isoformat(),
    }
