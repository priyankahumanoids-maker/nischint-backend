# Night Safety Guardian Engine — DB-backed persistent sessions
# Active safety monitoring during night hours.
# Monitors user journeys, detects zone changes, route deviations, idle states.
# Triggers alerts to user and guardian on risk escalation.

import logging
import math
import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import GuardianSession, GuardianAlert
from app.services.safe_zone_engine import check_zone, generate_zone_id

logger = logging.getLogger(__name__)

# ── Constants ──
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 5
ROUTE_DEVIATION_THRESHOLD_M = 120
IDLE_SPEED_THRESHOLD = 0.5       # m/s
IDLE_DURATION_THRESHOLD_S = 120  # 2 minutes
POLL_MOVING_S = 10
POLL_IDLE_S = 30

# Escalation tiers
class AlertLevel(str, Enum):
    NONE = "none"
    USER = "user"
    GUARDIAN = "guardian"
    EMERGENCY = "emergency"

RISK_ALERT_MAP = {
    "SAFE": AlertLevel.NONE,
    "LOW": AlertLevel.NONE,
    "HIGH": AlertLevel.USER,
    "CRITICAL": AlertLevel.GUARDIAN,
}


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_night_hour(hour: int) -> bool:
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def _estimate_eta_minutes(lat: float, lng: float, dest_lat: float, dest_lng: float, speed_mps: float) -> float | None:
    if speed_mps < 0.3:
        return None
    dist = _haversine(lat, lng, dest_lat, dest_lng)
    return round(dist / speed_mps / 60, 1)


def _compute_speed(prev_lat, prev_lng, prev_ts, cur_lat, cur_lng, cur_ts) -> float:
    dist = _haversine(prev_lat, prev_lng, cur_lat, cur_lng)
    dt = (cur_ts - prev_ts).total_seconds()
    if dt <= 0:
        return 0.0
    return dist / dt


def _distance_to_route(lat: float, lng: float, route_points: list[dict]) -> float:
    if not route_points:
        return 0.0
    min_d = float('inf')
    for pt in route_points:
        d = _haversine(lat, lng, pt["lat"], pt["lng"])
        if d < min_d:
            min_d = d
    return min_d


async def _get_active_session(session: AsyncSession, user_id: str) -> GuardianSession | None:
    """Fetch the most recent active guardian session for a user from DB."""
    result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.user_id == uuid.UUID(user_id),
            GuardianSession.status == "active",
        ).order_by(GuardianSession.started_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _persist_alert(session: AsyncSession, gs: GuardianSession, alert: dict) -> None:
    """Persist an alert to the guardian_alerts table."""
    db_alert = GuardianAlert(
        session_id=gs.id,
        user_id=gs.user_id,
        alert_type=alert["type"],
        severity=alert["severity"],
        message=alert["message"],
        details=alert.get("details"),
        recommendation=alert.get("recommendation"),
        location=alert.get("location"),
    )
    session.add(db_alert)


async def start_session(
    session: AsyncSession,
    user_id: str,
    start_lat: float,
    start_lng: float,
    dest_lat: float | None = None,
    dest_lng: float | None = None,
    route_points: list[dict] | None = None,
) -> dict:
    """Start night guardian monitoring for a user."""
    now = datetime.now(timezone.utc)

    # End any existing active sessions for this user
    stale_result = await session.execute(
        select(GuardianSession).where(
            GuardianSession.user_id == uuid.UUID(user_id),
            GuardianSession.status == "active",
        )
    )
    for old_gs in stale_result.scalars().all():
        old_gs.status = "ended"
        old_gs.ended_at = now

    # Check initial zone
    zone_result = await check_zone(session, user_id, start_lat, start_lng, now)

    gs = GuardianSession(
        user_id=uuid.UUID(user_id),
        status="active",
        destination={"lat": dest_lat, "lng": dest_lng} if dest_lat else None,
        route_points=route_points or [],
        current_location={"lat": start_lat, "lng": start_lng},
        previous_location=None,
        previous_update_at=now,
        zone_id=zone_result["zone_id"],
        risk_level=zone_result["risk_level"],
        risk_score=zone_result["risk_score"],
        zone_name=zone_result["zone_name"],
        speed_mps=0.0,
        eta_minutes=None,
        is_idle=False,
        idle_since=None,
        idle_duration_s=0,
        is_night=_is_night_hour(now.hour),
        route_deviated=False,
        route_deviation_m=0.0,
        escalation_level=AlertLevel.NONE,
        alert_count=0,
        last_alert_at=None,
        total_distance_m=0.0,
        location_updates=0,
        safety_check_pending=False,
        safety_check_sent_at=None,
        started_at=now,
    )
    session.add(gs)
    await session.flush()

    return {
        "guardian_active": True,
        "user_id": user_id,
        "monitoring_started": now.isoformat(),
        "is_night": gs.is_night,
        "initial_zone": {
            "zone_id": zone_result["zone_id"],
            "risk_level": zone_result["risk_level"],
            "risk_score": zone_result["risk_score"],
            "zone_name": zone_result["zone_name"],
        },
        "destination": gs.destination,
        "has_route": bool(route_points),
    }


async def stop_session(session: AsyncSession, user_id: str) -> dict:
    """Stop night guardian monitoring."""
    now = datetime.now(timezone.utc)
    gs = await _get_active_session(session, user_id)
    if not gs:
        return {"guardian_active": False, "user_id": user_id, "message": "No active session"}

    gs.status = "ended"
    gs.ended_at = now
    duration_min = round((now - gs.started_at).total_seconds() / 60, 1)

    return {
        "guardian_active": False,
        "user_id": user_id,
        "monitoring_stopped": now.isoformat(),
        "duration_minutes": duration_min,
        "total_distance_m": round(gs.total_distance_m, 1),
        "location_updates": gs.location_updates,
        "alerts_triggered": gs.alert_count,
        "final_zone": {
            "zone_id": gs.zone_id,
            "risk_level": gs.risk_level,
            "risk_score": gs.risk_score,
            "zone_name": gs.zone_name,
        },
    }


async def get_session_status(session: AsyncSession, user_id: str) -> dict | None:
    """Get current guardian session status."""
    gs = await _get_active_session(session, user_id)
    if not gs:
        return None
    now = datetime.now(timezone.utc)
    duration_min = round((now - gs.started_at).total_seconds() / 60, 1)

    # Fetch last 10 alerts
    alert_result = await session.execute(
        select(GuardianAlert)
        .where(GuardianAlert.session_id == gs.id)
        .order_by(GuardianAlert.created_at.desc())
        .limit(10)
    )
    alerts = [
        {
            "type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "details": a.details,
            "recommendation": a.recommendation,
            "location": a.location,
            "timestamp": a.created_at.isoformat(),
        }
        for a in alert_result.scalars().all()
    ]

    return {
        "active": gs.status == "active",
        "user_id": str(gs.user_id),
        "started_at": gs.started_at.isoformat(),
        "duration_minutes": duration_min,
        "current_location": gs.current_location,
        "current_zone": {
            "zone_id": gs.zone_id,
            "risk_level": gs.risk_level,
            "risk_score": gs.risk_score,
            "zone_name": gs.zone_name,
        },
        "destination": gs.destination,
        "eta_minutes": gs.eta_minutes,
        "speed_mps": round(gs.speed_mps, 2),
        "is_night": gs.is_night,
        "is_idle": gs.is_idle,
        "idle_duration_s": gs.idle_duration_s,
        "route_deviated": gs.route_deviated,
        "route_deviation_m": round(gs.route_deviation_m, 1),
        "escalation_level": gs.escalation_level,
        "alert_count": gs.alert_count,
        "alerts": alerts,
        "total_distance_m": round(gs.total_distance_m, 1),
        "location_updates": gs.location_updates,
        "safety_check_pending": gs.safety_check_pending,
        "poll_interval_s": POLL_IDLE_S if gs.is_idle else POLL_MOVING_S,
    }


async def get_all_active_sessions(session: AsyncSession) -> list[dict]:
    """Return summary of all active guardian sessions (for operator view)."""
    result = await session.execute(
        select(GuardianSession).where(GuardianSession.status == "active")
    )
    sessions = result.scalars().all()
    now = datetime.now(timezone.utc)

    results = []
    for gs in sessions:
        results.append({
            "user_id": str(gs.user_id),
            "duration_minutes": round((now - gs.started_at).total_seconds() / 60, 1),
            "risk_level": gs.risk_level,
            "risk_score": gs.risk_score,
            "zone_name": gs.zone_name,
            "is_idle": gs.is_idle,
            "route_deviated": gs.route_deviated,
            "escalation_level": gs.escalation_level,
            "alert_count": gs.alert_count,
            "location": gs.current_location,
            "eta_minutes": gs.eta_minutes,
        })
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


async def update_location(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    timestamp: datetime | None = None,
) -> dict:
    """Process a location update for an active night guardian session."""
    gs = await _get_active_session(session, user_id)
    if not gs or gs.status != "active":
        return {"error": "No active guardian session", "user_id": user_id}

    now = timestamp or datetime.now(timezone.utc)
    prev_ts = gs.previous_update_at or gs.started_at
    prev_loc = gs.current_location or {"lat": lat, "lng": lng}

    # Compute speed and distance
    speed = _compute_speed(prev_loc["lat"], prev_loc["lng"], prev_ts, lat, lng, now)
    dist = _haversine(prev_loc["lat"], prev_loc["lng"], lat, lng)

    # Update location state
    gs.previous_location = prev_loc.copy()
    gs.current_location = {"lat": lat, "lng": lng}
    gs.previous_update_at = now
    gs.speed_mps = speed
    gs.total_distance_m += dist
    gs.location_updates += 1
    gs.is_night = _is_night_hour(now.hour)

    # ── 1. Zone Check ──
    zone_result = await check_zone(session, user_id, lat, lng, now)
    prev_risk = gs.risk_level
    new_risk = zone_result["risk_level"]

    gs.zone_id = zone_result["zone_id"]
    gs.risk_level = new_risk
    gs.risk_score = zone_result["risk_score"]
    gs.zone_name = zone_result["zone_name"]

    alerts_generated = []

    # Check for zone escalation
    risk_order = {"SAFE": 0, "LOW": 1, "HIGH": 2, "CRITICAL": 3}
    if risk_order.get(new_risk, 0) > risk_order.get(prev_risk, 0):
        alert_level = RISK_ALERT_MAP.get(new_risk, AlertLevel.NONE)
        alert = {
            "type": "zone_escalation",
            "severity": new_risk.lower(),
            "message": f"Risk escalation: {prev_risk} -> {new_risk}",
            "details": f"Entered {zone_result['zone_name']} ({new_risk} risk, score {zone_result['risk_score']})",
            "recommendation": zone_result.get("recommendation_message", ""),
            "alert_level": alert_level,
            "timestamp": now.isoformat(),
            "location": {"lat": lat, "lng": lng},
        }
        alerts_generated.append(alert)
        await _persist_alert(session, gs, alert)
        gs.alert_count += 1
        gs.last_alert_at = now
        if alert_level.value > gs.escalation_level:
            gs.escalation_level = alert_level

    # ── 2. Route Deviation ──
    route_pts = gs.route_points or []
    if route_pts:
        dev_dist = _distance_to_route(lat, lng, route_pts)
        gs.route_deviation_m = dev_dist
        if dev_dist > ROUTE_DEVIATION_THRESHOLD_M and not gs.route_deviated:
            gs.route_deviated = True
            alert = {
                "type": "route_deviation",
                "severity": "medium",
                "message": f"Route deviation detected ({round(dev_dist)}m off route)",
                "details": "You have deviated from your planned route",
                "recommendation": "Return to your planned route or update your destination",
                "alert_level": AlertLevel.USER,
                "timestamp": now.isoformat(),
                "location": {"lat": lat, "lng": lng},
            }
            alerts_generated.append(alert)
            await _persist_alert(session, gs, alert)
            gs.alert_count += 1
            gs.last_alert_at = now
        elif dev_dist <= ROUTE_DEVIATION_THRESHOLD_M:
            gs.route_deviated = False

    # ── 3. Idle State Detection ──
    if speed < IDLE_SPEED_THRESHOLD:
        if not gs.is_idle:
            gs.is_idle = True
            gs.idle_since = now
            gs.idle_duration_s = 0
        else:
            if gs.idle_since:
                gs.idle_duration_s = (now - gs.idle_since).total_seconds()

            if gs.idle_duration_s >= IDLE_DURATION_THRESHOLD_S and not gs.safety_check_pending:
                gs.safety_check_pending = True
                gs.safety_check_sent_at = now
                alert = {
                    "type": "idle_detected",
                    "severity": "medium",
                    "message": f"Stopped for {round(gs.idle_duration_s)}s — are you safe?",
                    "details": "Unexpected stop detected during night journey",
                    "recommendation": "Tap to confirm you are safe",
                    "alert_level": AlertLevel.USER,
                    "timestamp": now.isoformat(),
                    "location": {"lat": lat, "lng": lng},
                }
                alerts_generated.append(alert)
                await _persist_alert(session, gs, alert)
                gs.alert_count += 1
                gs.last_alert_at = now
    else:
        if gs.is_idle:
            gs.is_idle = False
            gs.idle_since = None
            gs.idle_duration_s = 0
            gs.safety_check_pending = False

    # ── 4. ETA Calculation ──
    if gs.destination:
        gs.eta_minutes = _estimate_eta_minutes(
            lat, lng, gs.destination["lat"], gs.destination["lng"], speed
        )
        # Check if arrived
        dest_dist = _haversine(lat, lng, gs.destination["lat"], gs.destination["lng"])
        if dest_dist < 200:
            alert = {
                "type": "arrived",
                "severity": "low",
                "message": "Arrived at destination safely",
                "details": f"Reached within {round(dest_dist)}m of destination",
                "recommendation": "Journey complete. Night Guardian will deactivate.",
                "alert_level": AlertLevel.NONE,
                "timestamp": now.isoformat(),
                "location": {"lat": lat, "lng": lng},
            }
            alerts_generated.append(alert)
            await _persist_alert(session, gs, alert)
            gs.alert_count += 1

    # ── 5. No-response escalation ──
    if gs.safety_check_pending and gs.safety_check_sent_at:
        elapsed = (now - gs.safety_check_sent_at).total_seconds()
        if elapsed > 300 and gs.escalation_level != AlertLevel.EMERGENCY:
            gs.escalation_level = AlertLevel.EMERGENCY
            alert = {
                "type": "no_response_escalation",
                "severity": "critical",
                "message": "No response to safety check — escalating to emergency",
                "details": f"User unresponsive for {round(elapsed)}s after safety check",
                "recommendation": "Emergency services may be contacted",
                "alert_level": AlertLevel.EMERGENCY,
                "timestamp": now.isoformat(),
                "location": {"lat": lat, "lng": lng},
            }
            alerts_generated.append(alert)
            await _persist_alert(session, gs, alert)
            gs.alert_count += 1
            gs.last_alert_at = now

    return {
        "user_id": user_id,
        "location": {"lat": lat, "lng": lng},
        "zone": {
            "zone_id": gs.zone_id,
            "risk_level": gs.risk_level,
            "risk_score": gs.risk_score,
            "zone_name": gs.zone_name,
        },
        "speed_mps": round(speed, 2),
        "eta_minutes": gs.eta_minutes,
        "is_idle": gs.is_idle,
        "idle_duration_s": gs.idle_duration_s,
        "route_deviated": gs.route_deviated,
        "route_deviation_m": round(gs.route_deviation_m, 1),
        "escalation_level": gs.escalation_level,
        "alerts": alerts_generated,
        "alert_count": len(alerts_generated),
        "safety_check_pending": gs.safety_check_pending,
        "poll_interval_s": POLL_IDLE_S if gs.is_idle else POLL_MOVING_S,
        "timestamp": now.isoformat(),
    }


async def acknowledge_safety_check(session: AsyncSession, user_id: str) -> dict:
    """User confirms they are safe after an idle check."""
    gs = await _get_active_session(session, user_id)
    if not gs:
        return {"error": "No active session", "user_id": user_id}

    gs.safety_check_pending = False
    gs.safety_check_sent_at = None
    now = datetime.now(timezone.utc)
    alert = {
        "type": "safety_confirmed",
        "severity": "low",
        "message": "User confirmed safe",
        "details": "Safety check acknowledged",
        "recommendation": "Continue monitoring",
        "alert_level": AlertLevel.NONE,
        "timestamp": now.isoformat(),
        "location": gs.current_location,
    }
    await _persist_alert(session, gs, alert)

    # De-escalate if was escalated due to no response
    if gs.escalation_level == AlertLevel.EMERGENCY:
        gs.escalation_level = RISK_ALERT_MAP.get(gs.risk_level, AlertLevel.NONE)

    return {
        "acknowledged": True,
        "user_id": user_id,
        "timestamp": now.isoformat(),
        "escalation_level": gs.escalation_level,
    }
