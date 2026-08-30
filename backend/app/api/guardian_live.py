# Guardian Live Status API — Real-time monitoring for guardians
# Powers the Guardian Live Map mobile screen

import uuid
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.guardian import GuardianSession, GuardianAlert
from app.models.guardian_network import GuardianRelationship

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian/live", tags=["Guardian Live Map"])


@router.get("/protected-users")
async def get_protected_users(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get all users this guardian protects, with basic live status.
    Includes self for personal safety monitoring."""
    users = []

    # 1. Users where current user is listed as guardian (via User.guardian_id)
    rels = (await session.execute(
        select(User).where(and_(
            User.guardian_id == user.id,
            User.is_active == True,
        ))
    )).scalars().all()

    seen_ids = set()
    for u in rels:
        if u.id in seen_ids:
            continue
        seen_ids.add(u.id)

        active = (await session.execute(
            select(GuardianSession).where(and_(
                GuardianSession.user_id == u.id,
                GuardianSession.status == "active",
            )).limit(1)
        )).scalar_one_or_none()

        users.append({
            "user_id": str(u.id),
            "name": u.full_name or u.email,
            "email": u.email,
            "relationship": "family",
            "has_active_session": active is not None,
            "risk_level": active.risk_level if active else "SAFE",
            "risk_score": round(active.risk_score, 1) if active else 0,
            "is_self": False,
        })

    # 2. Always include self for personal safety monitoring
    if user.id not in seen_ids:
        self_active = (await session.execute(
            select(GuardianSession).where(and_(
                GuardianSession.user_id == user.id,
                GuardianSession.status == "active",
            )).limit(1)
        )).scalar_one_or_none()

        users.insert(0, {
            "user_id": str(user.id),
            "name": f"{user.full_name or user.email} (You)",
            "email": user.email,
            "relationship": "self",
            "has_active_session": self_active is not None,
            "risk_level": self_active.risk_level if self_active else "SAFE",
            "risk_score": round(self_active.risk_score, 1) if self_active else 0,
            "is_self": True,
        })

    return {"protected_users": users, "count": len(users)}


@router.get("/status/{user_id}")
async def get_live_status(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get comprehensive live status for a protected user — powers Guardian Live Map."""
    try:
        target_uid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid user ID format")

    # Allow self-view OR verify guardian relationship via User.guardian_id
    is_self = target_uid == user.id
    if not is_self:
        rel = (await session.execute(
            select(User).where(and_(
                User.id == target_uid,
                User.guardian_id == user.id,
                User.is_active == True,
            )).limit(1)
        )).scalar_one_or_none()

        if not rel:
            raise HTTPException(403, "You are not a guardian of this user")
        relationship = "family"
    else:
        relationship = "self"

    # Get target user info
    target = (await session.execute(select(User).where(User.id == target_uid))).scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")

    # Get active session
    active = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == target_uid,
            GuardianSession.status == "active",
        )).order_by(desc(GuardianSession.started_at)).limit(1)
    )).scalar_one_or_none()

    # Compute a read-only live-risk snapshot.
    #
    # This endpoint is polled frequently by the Guardian Live Map.  Do not
    # call compute_risk_score() here: that service persists GuardianRiskScore
    # and GuardianRiskEvent rows and flushes the request session.  A failed
    # optional AI write must never poison this read-only status request.
    risk_data = None
    try:
        live_risk = await _compute_child_risk(
            session,
            target_uid,
            datetime.now(timezone.utc),
        )
        if isinstance(live_risk, dict):
            risk_data = {
                "score": live_risk.get("score", 0),
                "level": live_risk.get("risk", "GREEN"),
                "factors": live_risk.get("factors", []),
            }
    except Exception as e:
        logger.exception(
            "[GUARDIAN_LIVE_STATUS] live risk computation failed "
            "user=%s err=%s",
            target_uid,
            e,
        )

    # Get recent alerts (last 10)
    recent_alerts = []
    if active:
        alerts_q = await session.execute(
            select(GuardianAlert)
            .where(GuardianAlert.session_id == active.id)
            .order_by(desc(GuardianAlert.created_at))
            .limit(10)
        )
        for a in alerts_q.scalars().all():
            recent_alerts.append({
                "id": str(a.id),
                "type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "recommendation": a.recommendation,
                "location": a.location,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            })

    # Build response
    now = datetime.now(timezone.utc)
    session_data = None
    if active:
        duration = int((now - active.started_at).total_seconds()) if active.started_at else 0
        last_update_seconds = 0
        if active.previous_update_at:
            last_update_seconds = int((now - active.previous_update_at).total_seconds())

        session_data = {
            "session_id": str(active.id),
            "started_at": active.started_at.isoformat(),
            "duration_seconds": duration,
            "destination": active.destination,
            "risk_level": active.risk_level,
            "risk_score": round(active.risk_score, 2),
            "current_location": active.current_location,
            "route_points": active.route_points,
            "speed_kmh": round(active.speed_mps * 3.6, 1) if active.speed_mps else 0,
            "total_distance_m": round(active.total_distance_m, 1),
            "is_idle": active.is_idle,
            "is_night": active.is_night,
            "route_deviated": active.route_deviated,
            "escalation_level": active.escalation_level,
            "alert_count": active.alert_count,
            "last_update_seconds": last_update_seconds,
        }

    # Derive the Guardian intelligence labels from the same GREEN/YELLOW/RED
    # live-risk classification used by /guardian/live/risk.
    behavior_pattern = "Normal"
    recommendation = "No action needed"
    if risk_data:
        level = str(risk_data.get("level", "GREEN")).upper()

        if level == "RED":
            behavior_pattern = "Critical Alert"
            recommendation = "Immediate contact required"
        elif level == "YELLOW":
            behavior_pattern = "Deviating"
            recommendation = "Check-in with user"

    # Get last 5 completed sessions for history context
    past_sessions = []
    past_q = await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == target_uid,
            GuardianSession.status != "active",
        )).order_by(desc(GuardianSession.ended_at)).limit(5)
    )
    for ps in past_q.scalars().all():
        past_sessions.append({
            "session_id": str(ps.id),
            "started_at": ps.started_at.isoformat() if ps.started_at else None,
            "ended_at": ps.ended_at.isoformat() if ps.ended_at else None,
            "risk_level": ps.risk_level,
            "distance_m": round(ps.total_distance_m, 1),
        })

    return {
        "user_id": str(target_uid),
        "user_name": target.full_name or target.email,
        "email": target.email,
        "relationship": relationship,
        "session_active": active is not None,
        "session": session_data,
        "risk": {
            "score": risk_data.get("score", 0) if risk_data else 0,
            "level": risk_data.get("level", "SAFE") if risk_data else "SAFE",
            "factors": risk_data.get("factors", []) if risk_data else [],
        },
        "behavior_pattern": behavior_pattern,
        "recommendation": recommendation,
        "recent_alerts": recent_alerts,
        "past_sessions": past_sessions,
        "last_update": now.isoformat(),
    }


@router.get("/risk")
async def get_live_risk(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Per-child live risk overlay data for the Guardian Map.
    Scoring: lastSeen + nightTime + erraticMovement + recentAlert.
    Returns GeoJSON-friendly array with risk color classification.

    Hardened:
      • Wrapped in try/except so a single malformed session row never
        nukes the whole 5s polling stream — frontend gets a structured
        fallback object instead of HTTP 500.
      • Per-child compute is itself defensive: any single child error
        is logged and that child is skipped.
    """
    try:
        return await _compute_live_risk(session, user)
    except Exception as e:  # noqa: BLE001 — explicit catch-all by design
        logger.exception(f"[RISK_LIVE] FAILED guardian={user.id}: {e}")
        return {
            "risk_level": "UNKNOWN",
            "score": 0,
            "message": "Risk data temporarily unavailable",
            "cells": [],
            "is_fallback": True,
        }


# String-form escalation_level (`"none"|"user"|"guardian"|"emergency"`)
# → numeric tier for risk scoring. Previously the endpoint compared
# `active.escalation_level >= 2`, which crashed because the column is
# `String(20)`. Source of truth: app/services/guardian_mode_engine.py.
_ESC_TIER: dict[str, int] = {
    "none":      0,
    "user":      1,
    "guardian":  2,
    "emergency": 3,
}


async def _compute_live_risk(session: AsyncSession, user: User):
    now = datetime.now(timezone.utc)

    # Use the same canonical protected-member scope as the Guardian
    # Dashboard. This keeps Primary Guardian and Co-Parent monitoring
    # consistent across SSE and polling while excluding monitor-only roles
    # from the protected-member result set.
    from app.services.guardian_dashboard_engine import _get_linked_user_ids

    child_ids = set(
        await _get_linked_user_ids(
            session,
            guardian_email=user.email or "",
            guardian_user_id=str(user.id),
            user_role=user.role,
            include_checkin_recovery=False,
        )
    )

    results = []
    for child_id in child_ids:
        try:
            row = await _compute_child_risk(session, child_id, now)
            if row is not None:
                results.append(row)
        except Exception as e:  # noqa: BLE001
            logger.exception(
                f"[RISK_LIVE] child compute failed child={child_id} err={e}"
            )
            # Skip this one, keep the rest of the response intact.
            continue

    logger.info(f"[RISK_LIVE] guardian={user.id} children={len(results)} "
                f"red={sum(1 for r in results if r['risk']=='RED')} "
                f"yellow={sum(1 for r in results if r['risk']=='YELLOW')} "
                f"green={sum(1 for r in results if r['risk']=='GREEN')}")

    return results


async def _compute_child_risk(session: AsyncSession, child_id, now):
    child_user = (await session.execute(
        select(User).where(User.id == child_id)
    )).scalar_one_or_none()
    if not child_user:
        return None

    # Get active session
    active = (await session.execute(
        select(GuardianSession).where(and_(
            GuardianSession.user_id == child_id,
            GuardianSession.status == "active",
        )).order_by(desc(GuardianSession.started_at)).limit(1)
    )).scalar_one_or_none()

    # NISCH-006 Sprint-2 fix: a linked child must ALWAYS surface in the
    # guardian's live-risk list. If they're not currently in a tracked
    # journey, return an OFFLINE / IDLE row so the UI can render
    # "Aarav — not tracking right now" instead of dropping them entirely.
    # The incident lifecycle (NISCH-006) attaches to children, not sessions
    # — so even an offline child needs a slot in the feed.
    if not active or not active.current_location:
        last_known_at = child_user.last_known_at
        return {
            "child_id":   str(child_id),
            "child_name": child_user.full_name or "Unknown",
            "risk":       "GREEN",
            "score":      0,
            "factors":    ["Not currently tracking"],
            "status":     "offline",
            "last_seen":  (
                last_known_at.isoformat()
                if last_known_at is not None
                else None
            ),
            "lat":        (
                float(child_user.last_known_lat)
                if child_user.last_known_lat is not None
                else None
            ),
            "lng":        (
                float(child_user.last_known_lng)
                if child_user.last_known_lng is not None
                else None
            ),
            "session_id": None,
            "is_offline": True,
        }

    loc = active.current_location
    if not isinstance(loc, dict):
        # Defensive: payload schema drift shouldn't take down the whole
        # endpoint.
        return {
            "child_id":   str(child_id),
            "child_name": child_user.full_name or "Unknown",
            "risk":       "GREEN",
            "score":      0,
            "factors":    ["Location data malformed"],
            "status":     "degraded",
            "last_seen":  None,
            "lat":        None,
            "lng":        None,
            "session_id": str(active.id),
            "is_offline": True,
        }
    lat = loc.get("lat") or loc.get("latitude")
    lng = loc.get("lng") or loc.get("longitude")
    if lat is None or lng is None:
        return {
            "child_id":   str(child_id),
            "child_name": child_user.full_name or "Unknown",
            "risk":       "GREEN",
            "score":      0,
            "factors":    ["No location fix yet"],
            "status":     "tracking_no_fix",
            "last_seen":  None,
            "lat":        None,
            "lng":        None,
            "session_id": str(active.id),
            "is_offline": False,
        }

    # --- RISK SCORING ---
    score = 0
    factors: list[str] = []

    # Factor 1: Last seen staleness
    last_update_s = 999
    if active.previous_update_at:
        last_update_s = (now - active.previous_update_at).total_seconds()
    if last_update_s > 60:
        score += 4
        factors.append(f"No update in {int(last_update_s)}s")
    elif last_update_s > 30:
        score += 2
        factors.append(f"Stale location ({int(last_update_s)}s)")

    # Factor 2: Night time
    if active.is_night:
        score += 2
        factors.append("Night time travel")

    # Factor 3: Erratic movement (route deviation, high speed, idle too long)
    if active.route_deviated:
        score += 3
        factors.append("Route deviated")
    elif active.speed_mps and active.speed_mps > 25:  # >90 km/h
        score += 3
        factors.append(f"High speed ({round(active.speed_mps * 3.6)}km/h)")
    elif active.is_idle and last_update_s > 120:
        score += 1
        factors.append("Idle for extended period")

    # Factor 4: Recent alerts (last 5 min)
    five_min_ago = now - timedelta(minutes=5)
    recent_alert_q = await session.execute(
        select(func.count()).select_from(GuardianAlert).where(and_(
            GuardianAlert.session_id == active.id,
            GuardianAlert.created_at >= five_min_ago,
        ))
    )
    recent_alert_count = recent_alert_q.scalar() or 0
    if recent_alert_count > 0:
        score += 5
        factors.append(f"{recent_alert_count} alert(s) in last 5 min")

    # Factor 5: Existing escalation level.
    # `escalation_level` is a String(20) — `"none"|"user"|"guardian"|"emergency"`.
    # We translate to a numeric tier for the comparison; default 0 if
    # the column ever holds an unexpected value (forward compat).
    esc_raw = active.escalation_level
    esc_tier = 0
    if isinstance(esc_raw, str):
        esc_tier = _ESC_TIER.get(esc_raw.lower(), 0)
    elif isinstance(esc_raw, (int, float)):  # belt-and-braces if column ever drifts back to int
        esc_tier = int(esc_raw)
    if esc_tier >= 2:
        score += 2
        factors.append(f"Escalation: {esc_raw}")

    # Classify: CRITICAL ≥ 9, RED 7-8, YELLOW 4-6, GREEN < 4
    if score >= 9:
        risk = "CRITICAL"
    elif score >= 7:
        risk = "RED"
    elif score >= 4:
        risk = "YELLOW"
    else:
        risk = "GREEN"

    return {
        "child_id": str(child_id),
        "child_name": child_user.full_name or child_user.email,
        "lat": float(lat),
        "lng": float(lng),
        "risk": risk,
        "score": score,
        "factors": factors,
        "speed_kmh": round(active.speed_mps * 3.6, 1) if active.speed_mps else 0,
        "last_updated": active.previous_update_at.isoformat() if active.previous_update_at else now.isoformat(),
    }
