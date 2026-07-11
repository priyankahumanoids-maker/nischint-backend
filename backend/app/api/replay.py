# Journey Replay API — builds a chronological event stream from existing data
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.roles import require_role
from app.models.user import User
from app.models.guardian import GuardianSession, GuardianAlert
from app.models.incident import Incident
from app.models.senior import Senior
from app.models.caregiver import VisitLog

router = APIRouter(prefix="/replay", tags=["Journey Replay"])


EVENT_ICONS = {
    "session_start": "play",
    "session_end": "stop",
    "movement": "move",
    "idle_start": "pause",
    "route_deviation": "alert",
    "risk_change": "shield",
    "guardian_alert": "bell",
    "incident_created": "siren",
    "incident_acknowledged": "check",
    "caregiver_assigned": "user-check",
    "caregiver_visit": "clipboard",
    "incident_resolved": "check-circle",
}

EVENT_COLORS = {
    "session_start": "#3b82f6",
    "session_end": "#64748b",
    "movement": "#06b6d4",
    "idle_start": "#f59e0b",
    "route_deviation": "#f97316",
    "risk_change": "#a855f7",
    "guardian_alert": "#ef4444",
    "incident_created": "#ef4444",
    "incident_acknowledged": "#3b82f6",
    "caregiver_assigned": "#f59e0b",
    "caregiver_visit": "#22c55e",
    "incident_resolved": "#22c55e",
}


@router.get("/sessions")
async def list_replay_sessions(
    limit: int = Query(30, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """List guardian sessions available for replay, most recent first."""
    from app.models.user import User as UserModel

    stmt = (
        select(
            GuardianSession.id,
            GuardianSession.user_id,
            GuardianSession.status,
            GuardianSession.risk_level,
            GuardianSession.started_at,
            GuardianSession.ended_at,
            GuardianSession.alert_count,
            GuardianSession.total_distance_m,
            GuardianSession.location_updates,
            UserModel.full_name,
        )
        .join(UserModel, GuardianSession.user_id == UserModel.id, isouter=True)
        .order_by(GuardianSession.started_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    return {
        "sessions": [
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                "user_name": r.full_name or "Unknown",
                "status": r.status,
                "risk_level": r.risk_level,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "alert_count": r.alert_count,
                "total_distance_m": round(r.total_distance_m or 0, 1),
                "location_updates": r.location_updates,
            }
            for r in rows
        ]
    }


@router.get("/{session_id}")
async def get_replay(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """Build a full chronological event stream for journey replay."""
    try:
        sid = uuid_mod.UUID(session_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid session ID format")

    # 1. Get the guardian session
    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == sid)
    )).scalar_one_or_none()
    if not gs:
        raise HTTPException(404, "Session not found")

    # Base location (Mumbai)
    base_lat = 19.076
    base_lng = 72.877

    events = []

    # 2. Session start event
    loc = gs.current_location or gs.destination or {}
    events.append({
        "timestamp": gs.started_at.isoformat() if gs.started_at else None,
        "type": "session_start",
        "lat": loc.get("lat", base_lat),
        "lng": loc.get("lng", base_lng),
        "description": "Guardian session started",
        "icon": EVENT_ICONS["session_start"],
        "color": EVENT_COLORS["session_start"],
        "severity": "info",
    })

    # 3. Simulate movement points from route_points if available
    if gs.route_points and isinstance(gs.route_points, list):
        total = len(gs.route_points)
        start_ts = gs.started_at or datetime.now(timezone.utc)
        end_ts = gs.ended_at or datetime.now(timezone.utc)
        duration = (end_ts - start_ts).total_seconds() or 1

        for i, pt in enumerate(gs.route_points):
            frac = i / max(total - 1, 1)
            ts = start_ts.timestamp() + duration * frac
            events.append({
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "type": "movement",
                "lat": pt.get("lat", pt.get("latitude", base_lat)),
                "lng": pt.get("lng", pt.get("longitude", base_lng)),
                "description": f"Location update {i+1}/{total}",
                "icon": EVENT_ICONS["movement"],
                "color": EVENT_COLORS["movement"],
                "severity": "info",
            })
    else:
        # Generate synthetic movement between start/current location
        import random
        start_ts = gs.started_at or datetime.now(timezone.utc)
        cloc = gs.current_location or {}
        slat = cloc.get("lat", base_lat + (random.random() - 0.5) * 0.02)
        slng = cloc.get("lng", base_lng + (random.random() - 0.5) * 0.02)
        n_points = max(gs.location_updates or 5, 5)
        for i in range(n_points):
            frac = i / max(n_points - 1, 1)
            ts = start_ts.timestamp() + frac * 600  # spread over ~10 minutes
            events.append({
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "type": "movement",
                "lat": base_lat + (slat - base_lat) * frac + (random.random() - 0.5) * 0.003,
                "lng": base_lng + (slng - base_lng) * frac + (random.random() - 0.5) * 0.003,
                "description": f"Location update {i+1}",
                "icon": EVENT_ICONS["movement"],
                "color": EVENT_COLORS["movement"],
                "severity": "info",
            })

    # 4. Idle event
    if gs.is_idle and gs.idle_since:
        events.append({
            "timestamp": gs.idle_since.isoformat(),
            "type": "idle_start",
            "lat": loc.get("lat", base_lat),
            "lng": loc.get("lng", base_lng),
            "description": f"User idle for {int(gs.idle_duration_s)}s",
            "icon": EVENT_ICONS["idle_start"],
            "color": EVENT_COLORS["idle_start"],
            "severity": "warning",
        })

    # 5. Route deviation
    if gs.route_deviated:
        events.append({
            "timestamp": gs.started_at.isoformat() if gs.started_at else None,
            "type": "route_deviation",
            "lat": loc.get("lat", base_lat) + 0.002,
            "lng": loc.get("lng", base_lng) + 0.001,
            "description": f"Route deviation: {int(gs.route_deviation_m)}m off course",
            "icon": EVENT_ICONS["route_deviation"],
            "color": EVENT_COLORS["route_deviation"],
            "severity": "warning",
        })

    # 6. Guardian alerts
    alerts = (await session.execute(
        select(GuardianAlert)
        .where(GuardianAlert.session_id == sid)
        .order_by(GuardianAlert.created_at)
    )).scalars().all()

    for alert in alerts:
        aloc = alert.location or {}
        events.append({
            "timestamp": alert.created_at.isoformat() if alert.created_at else None,
            "type": "guardian_alert",
            "lat": aloc.get("lat", base_lat + 0.003),
            "lng": aloc.get("lng", base_lng + 0.002),
            "description": alert.message or f"{alert.alert_type} alert",
            "icon": EVENT_ICONS["guardian_alert"],
            "color": EVENT_COLORS["guardian_alert"],
            "severity": alert.severity,
            "details": alert.details,
            "recommendation": alert.recommendation,
        })

    # 7. Related incidents (by user_id within session time window)
    inc_conditions = [Incident.is_test == False]
    if gs.started_at:
        inc_conditions.append(Incident.created_at >= gs.started_at)
    if gs.ended_at:
        inc_conditions.append(Incident.created_at <= gs.ended_at)

    # Get incidents from user's seniors
    from app.models.device import Device
    user_incidents = (await session.execute(
        select(Incident, Senior.full_name)
        .join(Senior, Incident.senior_id == Senior.id, isouter=True)
        .where(and_(*inc_conditions))
        .order_by(Incident.created_at)
        .limit(20)
    )).all()

    for inc, senior_name in user_incidents:
        events.append({
            "timestamp": inc.created_at.isoformat(),
            "type": "incident_created",
            "lat": base_lat + 0.004,
            "lng": base_lng + 0.003,
            "description": f"{inc.incident_type.replace('_', ' ').title()} — {senior_name or 'Unknown'}",
            "icon": EVENT_ICONS["incident_created"],
            "color": EVENT_COLORS["incident_created"],
            "severity": inc.severity,
        })

        if inc.acknowledged_at:
            events.append({
                "timestamp": inc.acknowledged_at.isoformat(),
                "type": "incident_acknowledged",
                "lat": base_lat + 0.004,
                "lng": base_lng + 0.003,
                "description": "Incident acknowledged",
                "icon": EVENT_ICONS["incident_acknowledged"],
                "color": EVENT_COLORS["incident_acknowledged"],
                "severity": "info",
            })

        if inc.assigned_at:
            events.append({
                "timestamp": inc.assigned_at.isoformat(),
                "type": "caregiver_assigned",
                "lat": base_lat + 0.005,
                "lng": base_lng + 0.004,
                "description": "Caregiver dispatched",
                "icon": EVENT_ICONS["caregiver_assigned"],
                "color": EVENT_COLORS["caregiver_assigned"],
                "severity": "info",
            })

        if inc.resolved_at:
            events.append({
                "timestamp": inc.resolved_at.isoformat(),
                "type": "incident_resolved",
                "lat": base_lat + 0.005,
                "lng": base_lng + 0.004,
                "description": "Incident resolved",
                "icon": EVENT_ICONS["incident_resolved"],
                "color": EVENT_COLORS["incident_resolved"],
                "severity": "info",
            })

    # 8. Session end event
    if gs.ended_at:
        events.append({
            "timestamp": gs.ended_at.isoformat(),
            "type": "session_end",
            "lat": loc.get("lat", base_lat),
            "lng": loc.get("lng", base_lng),
            "description": "Guardian session ended",
            "icon": EVENT_ICONS["session_end"],
            "color": EVENT_COLORS["session_end"],
            "severity": "info",
        })

    # Sort chronologically
    events.sort(key=lambda e: e["timestamp"] or "")

    # Session summary
    duration_s = 0
    if gs.started_at:
        end = gs.ended_at or datetime.now(timezone.utc)
        duration_s = int((end - gs.started_at).total_seconds())

    return {
        "session_id": str(gs.id),
        "user_id": str(gs.user_id),
        "status": gs.status,
        "risk_level": gs.risk_level,
        "started_at": gs.started_at.isoformat() if gs.started_at else None,
        "ended_at": gs.ended_at.isoformat() if gs.ended_at else None,
        "duration_seconds": duration_s,
        "total_distance_m": round(gs.total_distance_m or 0, 1),
        "alert_count": gs.alert_count,
        "event_count": len(events),
        "events": events,
    }


@router.get("/{session_id}/analysis")
async def get_replay_analysis(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin", "operator")),
):
    """AI analysis of a replay session — risk peaks, response times, recommendations."""
    from app.models.guardian_ai_v2 import GuardianRiskScore
    from app.models.caregiver import CaregiverStatus

    try:
        sid = uuid_mod.UUID(session_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid session ID format")

    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == sid)
    )).scalar_one_or_none()
    if not gs:
        raise HTTPException(404, "Session not found")

    # 1. Fetch risk scores during session window
    risk_conditions = [GuardianRiskScore.user_id == gs.user_id]
    if gs.started_at:
        risk_conditions.append(GuardianRiskScore.timestamp >= gs.started_at)
    if gs.ended_at:
        risk_conditions.append(GuardianRiskScore.timestamp <= gs.ended_at)

    risk_scores = (await session.execute(
        select(GuardianRiskScore)
        .where(and_(*risk_conditions))
        .order_by(GuardianRiskScore.timestamp)
    )).scalars().all()

    # 2. Find peak risk
    peak_score = 0.0
    peak_time = None
    peak_level = "low"
    peak_factors = []
    risk_timeline = []
    for rs in risk_scores:
        risk_timeline.append({
            "timestamp": rs.timestamp.isoformat(),
            "score": rs.final_score,
            "level": rs.risk_level,
        })
        if rs.final_score > peak_score:
            peak_score = rs.final_score
            peak_time = rs.timestamp.isoformat()
            peak_level = rs.risk_level
            peak_factors = rs.top_factors or []

    # If no risk scores, use session data
    if not risk_scores:
        raw_score = gs.risk_score or 0.0
        peak_score = min(raw_score / 10.0, 1.0) if raw_score > 1.0 else raw_score
        peak_level = gs.risk_level or "SAFE"
        peak_time = gs.started_at.isoformat() if gs.started_at else None
        peak_factors = []
        if gs.route_deviated:
            peak_factors.append({
                "factor": "route_deviation",
                "description": f"Route deviation of {int(gs.route_deviation_m)}m detected",
                "category": "location",
                "impact": 0.2,
            })
        if gs.is_idle and gs.idle_duration_s > 300:
            peak_factors.append({
                "factor": "inactivity_anomaly",
                "description": f"Extended idle period of {int(gs.idle_duration_s / 60)} minutes",
                "category": "behavior",
                "impact": 0.15,
            })
        if gs.is_night:
            peak_factors.append({
                "factor": "night_risk",
                "description": "Session during night hours with elevated risk",
                "category": "environment",
                "impact": 0.1,
            })

    # 3. Incident response analysis
    inc_conditions = [Incident.is_test == False]
    if gs.started_at:
        inc_conditions.append(Incident.created_at >= gs.started_at)
    if gs.ended_at:
        inc_conditions.append(Incident.created_at <= gs.ended_at)

    incidents = (await session.execute(
        select(Incident, Senior.full_name)
        .join(Senior, Incident.senior_id == Senior.id, isouter=True)
        .where(and_(*inc_conditions))
        .order_by(Incident.created_at)
        .limit(20)
    )).all()

    response_metrics = []
    total_ack_time = 0
    total_dispatch_time = 0
    total_resolution_time = 0
    ack_count = 0
    dispatch_count = 0
    resolution_count = 0

    for inc, sname in incidents:
        metric = {
            "incident_id": str(inc.id),
            "type": inc.incident_type,
            "severity": inc.severity,
            "senior_name": sname or "Unknown",
            "created_at": inc.created_at.isoformat(),
            "ack_time_s": None,
            "dispatch_time_s": None,
            "resolution_time_s": None,
        }
        if inc.acknowledged_at:
            ack = int((inc.acknowledged_at - inc.created_at).total_seconds())
            metric["ack_time_s"] = ack
            total_ack_time += ack
            ack_count += 1
        if inc.assigned_at:
            disp = int((inc.assigned_at - inc.created_at).total_seconds())
            metric["dispatch_time_s"] = disp
            total_dispatch_time += disp
            dispatch_count += 1
        if inc.resolved_at:
            res = int((inc.resolved_at - inc.created_at).total_seconds())
            metric["resolution_time_s"] = res
            total_resolution_time += res
            resolution_count += 1
        response_metrics.append(metric)

    avg_ack = round(total_ack_time / ack_count) if ack_count else None
    avg_dispatch = round(total_dispatch_time / dispatch_count) if dispatch_count else None
    avg_resolution = round(total_resolution_time / resolution_count) if resolution_count else None

    # 4. Preventable moments analysis
    preventable = []
    if gs.route_deviated and gs.route_deviation_m > 200:
        preventable.append({
            "moment": "Route deviation not caught early",
            "detail": f"A {int(gs.route_deviation_m)}m deviation was detected. Early geofence alerts could have prevented escalation.",
            "impact": "moderate",
        })
    if gs.is_idle and gs.idle_duration_s > 600:
        preventable.append({
            "moment": "Extended inactivity without check-in",
            "detail": f"User was idle for {int(gs.idle_duration_s / 60)} minutes. Automated wellness checks at 5-min intervals could reduce risk.",
            "impact": "high",
        })
    for inc, _ in incidents:
        if inc.severity == "critical" and inc.assigned_at and inc.created_at:
            disp_delay = (inc.assigned_at - inc.created_at).total_seconds()
            if disp_delay > 300:
                preventable.append({
                    "moment": f"Slow dispatch for {inc.incident_type.replace('_', ' ')}",
                    "detail": f"Caregiver dispatch took {int(disp_delay / 60)}m {int(disp_delay % 60)}s. Auto-dispatch for critical incidents could reduce this to under 2 minutes.",
                    "impact": "critical",
                })

    # 5. Recommendations
    recommendations = []
    if peak_score >= 0.6:
        recommendations.append("Increase monitoring frequency for this user during similar time windows.")
    if gs.is_night:
        recommendations.append("Enable enhanced night monitoring with shorter alert intervals.")
    if gs.route_deviated:
        recommendations.append("Configure tighter geofence boundaries and enable real-time deviation alerts.")
    if avg_dispatch and avg_dispatch > 180:
        recommendations.append("Implement auto-dispatch for critical incidents to reduce caregiver response time.")
    available_cg = (await session.execute(
        select(func.count()).where(CaregiverStatus.status == "available")
    )).scalar() or 0
    if available_cg < 2:
        recommendations.append("Increase caregiver coverage — only {0} currently available.".format(available_cg))
    if not recommendations:
        recommendations.append("Session within normal parameters. Continue standard monitoring protocols.")

    # Session duration
    duration_s = 0
    if gs.started_at:
        end = gs.ended_at or datetime.now(timezone.utc)
        duration_s = int((end - gs.started_at).total_seconds())

    return {
        "session_id": str(gs.id),
        "user_id": str(gs.user_id),
        "duration_seconds": duration_s,
        "risk_analysis": {
            "peak_score": round(peak_score, 3),
            "peak_time": peak_time,
            "peak_level": peak_level,
            "peak_factors": peak_factors[:3],
            "risk_timeline": risk_timeline,
            "session_risk_level": gs.risk_level,
        },
        "response_times": {
            "incidents_count": len(incidents),
            "avg_acknowledgement_s": avg_ack,
            "avg_dispatch_s": avg_dispatch,
            "avg_resolution_s": avg_resolution,
            "incidents": response_metrics,
        },
        "preventable_moments": preventable,
        "recommendations": recommendations,
    }
