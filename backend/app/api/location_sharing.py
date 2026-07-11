# Location Sharing API — live tracking links + GPS trail + AI movement intelligence
import math
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.guardian import GuardianSession
from app.models.location_share import LocationShare
from app.models.location_trail import LocationTrailPoint

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/location", tags=["Location Sharing"])

DEFAULT_SHARE_HOURS = 4
MAX_SHARE_HOURS = 24
TRAIL_INTERVAL_S = 25  # min seconds between trail recordings
STOP_SPEED_KMH = 1.5
TRAIL_MAX_AGE_H = 2


# ── Schemas ──

class CreateShareRequest(BaseModel):
    duration_hours: int = Field(DEFAULT_SHARE_HOURS, ge=1, le=MAX_SHARE_HOURS)
    share_name: Optional[str] = None


class CreateShareResponse(BaseModel):
    token: str
    tracking_url: str
    expires_at: str
    share_name: str


class AIInsight(BaseModel):
    state: str
    title: str
    lines: list[str]
    risk_level: str


class TrackingDataResponse(BaseModel):
    status: str
    share_name: str
    user_name: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy_m: Optional[float] = None
    heading: Optional[float] = None
    speed_mps: Optional[float] = None
    risk_level: str = "SAFE"
    risk_score: float = 0.0
    session_active: bool = False
    destination_name: Optional[str] = None
    total_distance_m: float = 0.0
    session_duration_s: int = 0
    last_updated: Optional[str] = None
    expires_at: str = ""
    route_deviated: bool = False
    route_deviation_m: float = 0.0
    is_idle: bool = False
    ai_insight: Optional[AIInsight] = None


class TrailPointOut(BaseModel):
    lat: float
    lng: float
    speed_kmh: float
    recorded_at_ist: str
    is_stop: bool


class MovementSummary(BaseModel):
    started_at_ist: str
    total_distance_km: float
    total_duration_min: int
    stop_count: int
    stops_total_min: int
    deviation_detected: bool
    deviation_m: float
    ai_interpretation: str


class TrailResponse(BaseModel):
    trail: list[TrailPointOut]
    movement_summary: Optional[MovementSummary] = None
    has_data: bool = False


# ── Helpers ──

def _to_ist(dt: datetime) -> str:
    """Convert UTC datetime to IST string like '3:05 PM'."""
    ist = dt + timedelta(hours=5, minutes=30)
    return ist.strftime("%-I:%M %p")


def _haversine_m(lat1, lng1, lat2, lng2):
    """Haversine distance in meters."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_ai_insight(gs: GuardianSession) -> AIInsight:
    level = (gs.risk_level or "SAFE").upper()
    if level in ("HIGH", "CRITICAL"):
        lines = []
        if gs.route_deviated:
            lines.append(f"Route deviation: {int(gs.route_deviation_m)}m off path")
        if gs.is_idle:
            idle_m = int(gs.idle_duration_s / 60) if gs.idle_duration_s else 0
            lines.append(f"Idle for {idle_m}+ minutes")
        lines.append(f"Risk elevated: {level}")
        lines.append("Guardian notified")
        return AIInsight(state="alert", title="AI ALERT", lines=lines, risk_level=level)
    if level == "MODERATE":
        lines = []
        if gs.route_deviated:
            lines.append(f"Route deviation: {int(gs.route_deviation_m)}m off path")
        if gs.speed_mps and gs.speed_mps < 0.3:
            lines.append("Speed drop detected")
        if not lines:
            lines.append("Minor anomaly detected")
        lines.append(f"Risk: {level}")
        return AIInsight(state="notice", title="AI NOTICE", lines=lines, risk_level=level)
    lines = ["Moving normally"]
    if gs.destination and gs.destination.get("name"):
        lines.append(f"On route to {gs.destination['name']}")
    else:
        lines.append("On expected route")
    lines.append("No anomalies detected")
    return AIInsight(state="clear", title="AI INSIGHT", lines=lines, risk_level=level)


def _compute_movement_summary(
    points: list[LocationTrailPoint],
    deviation_detected: bool,
    deviation_m: float,
) -> Optional[MovementSummary]:
    if len(points) < 2:
        return None

    first = points[0]
    last = points[-1]
    total_dist = 0.0
    stop_count = 0
    stop_total_s = 0.0
    in_stop = False
    stop_start = None

    for i in range(1, len(points)):
        total_dist += _haversine_m(points[i - 1].lat, points[i - 1].lng, points[i].lat, points[i].lng)
        if points[i].is_stop:
            if not in_stop:
                in_stop = True
                stop_start = points[i].recorded_at
                stop_count += 1
        else:
            if in_stop and stop_start:
                stop_total_s += (points[i].recorded_at - stop_start).total_seconds()
            in_stop = False
            stop_start = None

    if in_stop and stop_start:
        stop_total_s += (last.recorded_at - stop_start).total_seconds()

    dur_s = (last.recorded_at - first.recorded_at).total_seconds()
    stops_min = int(stop_total_s / 60)

    # AI interpretation
    if not deviation_detected and stop_count == 0:
        interp = "Moving normally \u00b7 Following expected route \u00b7 No stops detected"
    elif not deviation_detected and stop_count > 0:
        interp = f"Mostly on route \u00b7 Stopped for {stops_min} min at {stop_count} location(s) \u00b7 Continuing normally"
    elif deviation_detected and stop_count == 0:
        interp = f"Route deviation detected ({int(deviation_m)}m off) \u00b7 Not on expected path \u00b7 Guardian notified"
    else:
        interp = f"Route deviation detected ({int(deviation_m)}m off) \u00b7 Stopped at unusual location for {stops_min} min \u00b7 Risk elevated"

    return MovementSummary(
        started_at_ist=_to_ist(first.recorded_at),
        total_distance_km=round(total_dist / 1000, 2),
        total_duration_min=max(1, int(dur_s / 60)),
        stop_count=stop_count,
        stops_total_min=stops_min,
        deviation_detected=deviation_detected,
        deviation_m=deviation_m,
        ai_interpretation=interp,
    )


async def _broadcast_tracking_event(event_type: str, user_name: str, token: str, user_id: str, **extra):
    try:
        from app.api.ws_command_center import broadcast_to_command_center
        now = datetime.now(timezone.utc)
        await broadcast_to_command_center({
            "type": event_type,
            "data": {"user_name": user_name, "user_id": user_id, "token": token, "tracking_url": f"/track/{token}", **extra},
            "timestamp": now.isoformat(),
        })
    except Exception as e:
        logger.warning(f"Failed to broadcast {event_type}: {e}")


async def _record_trail_point(session: AsyncSession, token: str, lat: float, lng: float, speed_mps: float, share_name: str, user_id: str, deviation_detected: bool = False, deviation_m: float = 0.0):
    """Record a GPS trail point if enough time has elapsed since the last one."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=TRAIL_MAX_AGE_H)

    # Get last point to check timing and stop detection
    last_two = (await session.execute(
        select(LocationTrailPoint)
        .where(LocationTrailPoint.share_token == token)
        .order_by(LocationTrailPoint.recorded_at.desc())
        .limit(2)
    )).scalars().all()

    if last_two:
        last = last_two[0]
        elapsed = (now - last.recorded_at).total_seconds()
        if elapsed < TRAIL_INTERVAL_S:
            return  # too soon

    speed_kmh = (speed_mps or 0.0) * 3.6

    # Stop detection: speed < 1.5 km/h for 2+ consecutive points
    is_stop = False
    if speed_kmh < STOP_SPEED_KMH and len(last_two) >= 2:
        if all(p.speed_kmh < STOP_SPEED_KMH for p in last_two):
            is_stop = True

    # Check if this is a new stop (transition from moving to stopped)
    was_stopped = last_two[0].is_stop if last_two else False
    new_stop_detected = is_stop and not was_stopped

    pt = LocationTrailPoint(
        share_token=token, lat=lat, lng=lng, speed_kmh=speed_kmh, is_stop=is_stop, recorded_at=now,
    )
    session.add(pt)

    # Auto-trim old points
    await session.execute(
        delete(LocationTrailPoint).where(and_(
            LocationTrailPoint.share_token == token,
            LocationTrailPoint.recorded_at < cutoff,
        ))
    )
    await session.flush()

    # Broadcast Command Centre events for new stops
    if new_stop_detected:
        ist_time = _to_ist(now)
        await _broadcast_tracking_event(
            "tracking_stop_detected", share_name, token, user_id,
            detail=f"Stationary for 2+ min \u00b7 {ist_time}",
            severity="notice",
        )

    # Broadcast deviation event if newly deviated
    if deviation_detected and last_two and not any(True for _ in []):
        # Only broadcast if the previous point was not already in a deviation context
        # We check by looking at the previous broadcast state — simplified: always broadcast
        # but the Command Centre will deduplicate by token
        pass  # deviation is broadcast from the main tracking endpoint below


# ── 1. Create share link ──

@router.post("/share", response_model=CreateShareResponse)
async def create_share_link(
    body: CreateShareRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    gs = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == user.id, GuardianSession.status == "active",
        ))
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=body.duration_hours)
    share_name = body.share_name or user.full_name or user.email.split("@")[0]

    share = LocationShare(
        user_id=user.id, session_id=gs.id if gs else None,
        token=token, share_name=share_name, expires_at=expires_at,
    )
    session.add(share)
    await session.flush()

    await _broadcast_tracking_event("live_tracking_started", share_name, token, str(user.id))

    return CreateShareResponse(token=token, tracking_url=f"/track/{token}", expires_at=expires_at.isoformat(), share_name=share_name)


# ── 2. Get tracking data (PUBLIC) ──

@router.get("/track/{token}", response_model=TrackingDataResponse)
async def get_tracking_data(
    token: str,
    session: AsyncSession = Depends(get_db_session),
):
    share = (await session.execute(
        select(LocationShare).where(LocationShare.token == token)
    )).scalar_one_or_none()
    if not share:
        raise HTTPException(404, "Tracking link not found")

    now = datetime.now(timezone.utc)

    if not share.is_active:
        return TrackingDataResponse(status="inactive", share_name=share.share_name or "Unknown", user_name="", expires_at=share.expires_at.isoformat())

    if now > share.expires_at:
        return TrackingDataResponse(status="expired", share_name=share.share_name or "Unknown", user_name="", expires_at=share.expires_at.isoformat())

    user = (await session.execute(select(User).where(User.id == share.user_id))).scalar_one_or_none()
    user_name = (user.full_name or user.email.split("@")[0]) if user else "Unknown"

    gs = (await session.execute(
        select(GuardianSession).where(and_(GuardianSession.user_id == share.user_id, GuardianSession.status == "active"))
    )).scalar_one_or_none()

    if not gs:
        last_gs = (await session.execute(
            select(GuardianSession).where(GuardianSession.user_id == share.user_id)
            .order_by(GuardianSession.started_at.desc()).limit(1)
        )).scalar_one_or_none()
        loc = last_gs.current_location if last_gs else None
        return TrackingDataResponse(
            status="live", share_name=share.share_name or user_name, user_name=user_name,
            lat=loc.get("lat") if loc else None, lng=loc.get("lng") if loc else None,
            accuracy_m=loc.get("accuracy_m") if loc else None, risk_level="SAFE", session_active=False,
            last_updated=loc.get("updated_at") if loc else None, expires_at=share.expires_at.isoformat(),
            ai_insight=AIInsight(state="clear", title="AI INSIGHT", lines=["Last known location", "No active session", "Tracking link active"], risk_level="SAFE"),
        )

    loc = gs.current_location or {}
    duration_s = int((now - gs.started_at).total_seconds()) if gs.started_at else 0

    # Record trail point (side effect)
    if loc.get("lat") and loc.get("lng"):
        await _record_trail_point(
            session, token, loc["lat"], loc["lng"], gs.speed_mps or 0.0,
            share.share_name or user_name, str(share.user_id),
            deviation_detected=gs.route_deviated, deviation_m=gs.route_deviation_m,
        )

        # Broadcast deviation event if active
        if gs.route_deviated and gs.route_deviation_m > 50:
            ist_time = _to_ist(now)
            await _broadcast_tracking_event(
                "tracking_deviation", share.share_name or user_name, token, str(share.user_id),
                detail=f"{int(gs.route_deviation_m)}m off expected route \u00b7 {ist_time}",
                severity="warning",
            )

    return TrackingDataResponse(
        status="live", share_name=share.share_name or user_name, user_name=user_name,
        lat=loc.get("lat"), lng=loc.get("lng"), accuracy_m=loc.get("accuracy_m"),
        heading=loc.get("heading"), speed_mps=gs.speed_mps,
        risk_level=gs.risk_level or "SAFE", risk_score=gs.risk_score or 0.0,
        session_active=True, destination_name=gs.destination.get("name") if gs.destination else None,
        total_distance_m=gs.total_distance_m or 0.0, session_duration_s=duration_s,
        last_updated=loc.get("updated_at"), expires_at=share.expires_at.isoformat(),
        route_deviated=gs.route_deviated or False, route_deviation_m=gs.route_deviation_m or 0.0,
        is_idle=gs.is_idle or False, ai_insight=_compute_ai_insight(gs),
    )


# ── 3. Get trail data (PUBLIC) ──

@router.get("/track/{token}/trail", response_model=TrailResponse)
async def get_trail_data(
    token: str,
    session: AsyncSession = Depends(get_db_session),
):
    share = (await session.execute(
        select(LocationShare).where(LocationShare.token == token)
    )).scalar_one_or_none()
    if not share:
        raise HTTPException(404, "Tracking link not found")

    now = datetime.now(timezone.utc)
    if not share.is_active or now > share.expires_at:
        return TrailResponse(trail=[], has_data=False)

    # Fetch trail points (last 2 hours, ordered by time)
    cutoff = now - timedelta(hours=TRAIL_MAX_AGE_H)
    points = (await session.execute(
        select(LocationTrailPoint)
        .where(and_(LocationTrailPoint.share_token == token, LocationTrailPoint.recorded_at >= cutoff))
        .order_by(LocationTrailPoint.recorded_at.asc())
    )).scalars().all()

    if not points:
        return TrailResponse(trail=[], has_data=False)

    # Check current session for deviation info
    gs = (await session.execute(
        select(GuardianSession).where(and_(GuardianSession.user_id == share.user_id, GuardianSession.status == "active"))
    )).scalar_one_or_none()

    deviation_detected = gs.route_deviated if gs else False
    deviation_m = gs.route_deviation_m if gs else 0.0

    # Build trail output
    trail = [
        TrailPointOut(
            lat=p.lat, lng=p.lng, speed_kmh=round(p.speed_kmh, 1),
            recorded_at_ist=_to_ist(p.recorded_at), is_stop=p.is_stop,
        )
        for p in points
    ]

    summary = _compute_movement_summary(points, deviation_detected, deviation_m)

    return TrailResponse(trail=trail, movement_summary=summary, has_data=True)


# ── 4. Deactivate share ──

@router.delete("/share/{token}")
async def deactivate_share(
    token: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    share = (await session.execute(
        select(LocationShare).where(and_(LocationShare.token == token, LocationShare.user_id == user.id))
    )).scalar_one_or_none()
    if not share:
        raise HTTPException(404, "Share link not found")

    share.is_active = False
    await session.flush()

    await _broadcast_tracking_event("live_tracking_ended", share.share_name or "Unknown", token, str(user.id))

    return {"status": "deactivated", "token": token}


# ── 5. Get geofence context (PUBLIC) ──

@router.get("/track/{token}/context")
async def get_geofence_context(
    token: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Public endpoint: returns geofence zones, timeline, and AI context for a tracking token."""
    from app.services.geofence_context import compute_geofence_context, ContextResponse, broadcast_zone_events

    share = (await session.execute(
        select(LocationShare).where(LocationShare.token == token)
    )).scalar_one_or_none()
    if not share:
        raise HTTPException(404, "Tracking link not found")

    now = datetime.now(timezone.utc)
    if not share.is_active or now > share.expires_at:
        return ContextResponse(zones=[], current_zone=None, timeline=[], ai_context="Tracking link is no longer active")

    # Get current location from active session or last session
    gs = (await session.execute(
        select(GuardianSession).where(and_(GuardianSession.user_id == share.user_id, GuardianSession.status == "active"))
    )).scalar_one_or_none()

    if gs:
        loc = gs.current_location or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        route_deviated = gs.route_deviated or False
        total_dist = gs.total_distance_m or 0.0
        dur_min = int((now - gs.started_at).total_seconds() / 60) if gs.started_at else 0
    else:
        last_gs = (await session.execute(
            select(GuardianSession).where(GuardianSession.user_id == share.user_id)
            .order_by(GuardianSession.started_at.desc()).limit(1)
        )).scalar_one_or_none()
        loc = last_gs.current_location if last_gs else None
        lat = loc.get("lat") if loc else None
        lng = loc.get("lng") if loc else None
        route_deviated = False
        total_dist = 0.0
        dur_min = 0

    if not lat or not lng:
        return ContextResponse(zones=[], current_zone=None, timeline=[], ai_context="Waiting for location data")

    ctx = await compute_geofence_context(
        session, str(share.user_id), token, lat, lng,
        route_deviated=route_deviated,
        total_distance_m=total_dist,
        total_duration_min=dur_min,
    )

    # Broadcast zone events to Command Centre (fire-and-forget, deduped in-memory)
    user_name = share.share_name or "Unknown"
    await broadcast_zone_events(ctx.timeline, user_name, token, str(share.user_id), ctx.zones, _zone_broadcast_cache.setdefault(token, set()))

    return ctx


# In-memory dedup cache for zone broadcasts per token
_zone_broadcast_cache: dict[str, set] = {}

