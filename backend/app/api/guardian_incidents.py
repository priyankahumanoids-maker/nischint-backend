# Guardian Incidents API — Mobile incident replay
# Powers the Incident Replay mobile screen

import uuid
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.guardian import GuardianSession, GuardianAlert

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian/incidents", tags=["Guardian Incidents"])


@router.get("")
async def list_incidents(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List all safety incidents/alerts for the current user's sessions."""
    # Get alerts from all sessions owned by this user
    alerts = (await session.execute(
        select(GuardianAlert)
        .join(GuardianSession, GuardianAlert.session_id == GuardianSession.id)
        .where(GuardianSession.user_id == user.id)
        .order_by(desc(GuardianAlert.created_at))
        .limit(limit)
    )).scalars().all()

    # Also get SOS events from safety_events table (if exists)
    sos_events = []
    try:
        rows = (await session.execute(text("""
            SELECT id, trigger_type, location, risk_level, risk_score, 
                   guardians_notified, created_at, status
            FROM sos_events 
            WHERE user_id = :uid
            ORDER BY created_at DESC LIMIT :lim
        """), {"uid": str(user.id), "lim": limit})).fetchall()
        for r in rows:
            sos_events.append({
                "id": str(r.id),
                "type": "sos",
                "alert_type": "sos_alert",
                "severity": "critical",
                "message": f"SOS triggered ({r.trigger_type})",
                "recommendation": "Immediate response required",
                "location": r.location if isinstance(r.location, dict) else None,
                "risk_level": r.risk_level,
                "risk_score": float(r.risk_score) if r.risk_score else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "status": r.status or "triggered",
                "session_id": None,
            })
    except Exception:
        pass  # SOS table may not exist yet

    # Build combined incidents list
    incidents = []
    for a in alerts:
        incidents.append({
            "id": str(a.id),
            "type": "alert",
            "alert_type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "recommendation": a.recommendation,
            "location": a.location,
            "risk_level": a.severity.upper() if a.severity else "LOW",
            "risk_score": 0,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "session_id": str(a.session_id),
        })

    # Merge SOS events
    incidents.extend(sos_events)
    incidents.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {"incidents": incidents[:limit], "total": len(incidents)}


@router.get("/{incident_id}/replay")
async def get_incident_replay(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get full replay dataset for an incident (alert or SOS) with timeline."""
    # Try to find as a GuardianAlert first
    alert = (await session.execute(
        select(GuardianAlert)
        .join(GuardianSession, GuardianAlert.session_id == GuardianSession.id)
        .where(and_(
            GuardianAlert.id == uuid.UUID(incident_id),
            GuardianSession.user_id == user.id,
        ))
    )).scalar_one_or_none()

    if not alert:
        raise HTTPException(404, "Incident not found")

    # Get the parent session
    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == alert.session_id)
    )).scalar_one_or_none()

    if not gs:
        raise HTTPException(404, "Session not found")

    # Get all alerts from this session for the timeline
    session_alerts = (await session.execute(
        select(GuardianAlert)
        .where(GuardianAlert.session_id == gs.id)
        .order_by(GuardianAlert.created_at)
    )).scalars().all()

    # Build timeline events
    events = []
    for sa in session_alerts:
        events.append({
            "id": str(sa.id),
            "time": sa.created_at.isoformat() if sa.created_at else None,
            "type": sa.alert_type,
            "severity": sa.severity,
            "message": sa.message,
            "recommendation": sa.recommendation,
            "location": sa.location,
            "risk_score": 0,
            "risk_level": sa.severity.upper() if sa.severity else "LOW",
            "is_current": str(sa.id) == incident_id,
        })

    # Add session start/end as timeline events
    timeline = []
    if gs.started_at:
        timeline.append({
            "time": gs.started_at.isoformat(),
            "type": "session_start",
            "severity": "info",
            "message": f"Safety session started{' to ' + gs.destination.get('name', '') if gs.destination and gs.destination.get('name') else ''}",
            "location": gs.route_points[0] if gs.route_points else None,
        })

    for ev in events:
        timeline.append(ev)

    if gs.ended_at:
        timeline.append({
            "time": gs.ended_at.isoformat(),
            "type": "session_end",
            "severity": "info",
            "message": f"Session ended ({gs.status})",
            "location": gs.current_location,
        })

    timeline.sort(key=lambda x: x.get("time", ""))

    # Build location trail from route_points
    location_trail = []
    if gs.route_points:
        for i, pt in enumerate(gs.route_points):
            if isinstance(pt, dict) and pt.get("lat"):
                location_trail.append({
                    "lat": pt["lat"],
                    "lng": pt["lng"],
                    "index": i,
                })

    # AI analysis
    response_time = None
    if alert.created_at and gs.started_at:
        response_time = int((alert.created_at - gs.started_at).total_seconds())

    ai_analysis = {
        "root_cause": _determine_root_cause(alert, gs),
        "response_time_seconds": response_time,
        "preventable": alert.severity in ("low", "moderate"),
        "risk_score_at_incident": round(float(gs.risk_score), 1) if gs.risk_score else 0,
        "recommendation": alert.recommendation or "Review session for safety improvements",
        "contributing_factors": _get_contributing_factors(alert, gs),
    }

    return {
        "incident_id": str(alert.id),
        "incident_type": alert.alert_type,
        "severity": alert.severity,
        "message": alert.message,
        "incident_time": alert.created_at.isoformat() if alert.created_at else None,
        "session": {
            "id": str(gs.id),
            "started_at": gs.started_at.isoformat() if gs.started_at else None,
            "ended_at": gs.ended_at.isoformat() if gs.ended_at else None,
            "destination": gs.destination,
            "risk_level": gs.risk_level,
            "total_distance_m": round(gs.total_distance_m, 1),
        },
        "timeline": timeline,
        "location_trail": location_trail,
        "ai_analysis": ai_analysis,
        "stats": {
            "total_alerts": len(session_alerts),
            "route_points": len(location_trail),
        },
    }


def _determine_root_cause(alert, session):
    """Determine root cause based on alert type and session state."""
    causes = {
        "idle_too_long": "Extended idle period in potentially unsafe location",
        "route_deviation": "Significant deviation from planned safe route",
        "speed_anomaly": "Unusual speed pattern detected during session",
        "night_travel": "Travel detected during high-risk nighttime hours",
        "risk_escalation": "Multiple risk factors converging simultaneously",
        "geofence_exit": "Exited designated safe zone boundary",
        "sos_alert": "Manual SOS triggered by user",
    }
    base = causes.get(alert.alert_type, f"Safety alert: {alert.alert_type}")
    if session.is_night:
        base += " + Night travel"
    if session.route_deviated:
        base += " + Route deviation"
    return base


def _get_contributing_factors(alert, session):
    """Extract contributing factors from alert and session context."""
    factors = []
    if session.is_night:
        factors.append("Night travel")
    if session.is_idle:
        factors.append("Idle state")
    if session.route_deviated:
        factors.append("Route deviation")
    if float(session.risk_score) > 5:
        factors.append(f"High risk score ({session.risk_score})")
    if alert.alert_type == "speed_anomaly":
        factors.append("Speed anomaly")
    if not factors:
        factors.append("Location context")
    return factors
