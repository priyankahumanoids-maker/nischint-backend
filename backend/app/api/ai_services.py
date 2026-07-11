# Mobile-facing AI Services REST API
#
# Exposes the platform's built AI engines to authenticated mobile users
# (guardian / child roles) — previously locked behind operator-only endpoints.
#
# Routes:
#   GET  /ai/life-pattern         — Life pattern analysis for family members
#   GET  /ai/digital-twin         — Digital twin behavioural profile
#   GET  /ai/risk-forecast        — Predicted risk for next 24h
#   GET  /ai/environment-risk     — Environmental conditions at a location
#   GET  /ai/behavior-analysis    — Behavioral anomaly detection
#   GET  /ai/twin-evolution       — Digital twin evolution/change history
#   GET  /ai/hotspot-trends       — Local safety hotspot trends

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.senior import Senior
from app.models.device import Device

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI Services (Mobile)"])


# ── Helpers ──

async def _get_family_devices(session: AsyncSession, user: User) -> list[dict]:
    """Resolve all device_ids in the user's family scope."""
    from app.services.dashboard_service import _get_family_senior_ids

    senior_ids = await _get_family_senior_ids(session, user.id)
    if not senior_ids:
        return []

    result = await session.execute(
        select(Device.id, Device.device_identifier, Device.senior_id, Senior.full_name)
        .join(Senior, Device.senior_id == Senior.id)
        .where(Device.senior_id.in_(senior_ids))
    )
    return [
        {
            "device_id": str(row.id),
            "device_identifier": row.device_identifier,
            "senior_id": str(row.senior_id),
            "name": row.full_name,
        }
        for row in result.all()
    ]


async def _require_family_device(
    session: AsyncSession, user: User, device_id: str | None = None,
) -> dict:
    """Return a single family device — first match or specific by id."""
    devices = await _get_family_devices(session, user)
    if not devices:
        raise HTTPException(404, "No linked devices found for your family")

    if device_id:
        match = next((d for d in devices if d["device_id"] == device_id), None)
        if not match:
            raise HTTPException(403, "Device not in your family scope")
        return match

    return devices[0]


# ── 1. Life Pattern ──

@router.get("/life-pattern")
async def get_life_pattern(
    device_id: str | None = Query(None, description="Specific device UUID, or omit for primary"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns the life pattern analysis for a family member.
    Includes daily rhythm, activity windows, and routine deviations.
    """
    dev = await _require_family_device(session, user, device_id)
    did = UUID(dev["device_id"])

    from app.services.life_pattern_engine import build_life_pattern
    pattern = await build_life_pattern(session, did)

    return {
        "device_id": dev["device_id"],
        "name": dev["name"],
        "life_pattern": pattern,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 2. Digital Twin ──

@router.get("/digital-twin")
async def get_digital_twin(
    device_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns the digital twin behavioural model for a family member.
    Includes wake/sleep rhythm, peak activity, movement intervals, personalized thresholds.
    """
    dev = await _require_family_device(session, user, device_id)
    did = dev["device_id"]

    row = (await session.execute(text("""
        SELECT confidence_score, wake_hour, sleep_hour, peak_activity_hour,
               typical_inactivity_max_minutes, daily_rhythm, activity_windows,
               profile_summary, training_data_points, twin_version,
               last_trained_at, created_at, updated_at
        FROM device_digital_twins WHERE device_id = :did
    """), {"did": did})).fetchone()

    if not row:
        return {
            "device_id": did,
            "name": dev["name"],
            "twin_exists": False,
            "message": "Digital twin not yet built. Needs more activity data.",
        }

    return {
        "device_id": did,
        "name": dev["name"],
        "twin_exists": True,
        "confidence": round(row.confidence_score, 3),
        "wake_hour": row.wake_hour,
        "sleep_hour": row.sleep_hour,
        "peak_activity_hour": row.peak_activity_hour,
        "typical_inactivity_max_minutes": row.typical_inactivity_max_minutes,
        "daily_rhythm": row.daily_rhythm,
        "activity_windows": row.activity_windows,
        "profile_summary": row.profile_summary,
        "training_data_points": row.training_data_points,
        "twin_version": row.twin_version,
        "last_trained_at": row.last_trained_at.isoformat() if row.last_trained_at else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 3. Risk Forecast ──

@router.get("/risk-forecast")
async def get_risk_forecast(
    device_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns predicted risk levels for the next 24h.
    Uses the forecast engine's time-series model.
    """
    dev = await _require_family_device(session, user, device_id)

    from app.services.forecast_engine import generate_forecast
    forecast = await generate_forecast(session, dev["device_id"])

    return {
        "device_id": dev["device_id"],
        "name": dev["name"],
        "forecast": forecast,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 4. Environment Risk ──

@router.get("/environment-risk")
async def get_environment_risk(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    user: User = Depends(get_current_user),
):
    """
    Returns environmental risk assessment for a specific location.
    Includes weather hazards, air quality, UV index, visibility conditions.
    """
    from app.services.environment_risk_engine import evaluate_environment_risk
    risk = await evaluate_environment_risk(lat, lng)

    return {
        "lat": lat,
        "lng": lng,
        "environment_risk": risk,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 5. Behavior Analysis ──

@router.get("/behavior-analysis")
async def get_behavior_analysis(
    device_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns recent behavioral anomaly analysis for a family member.
    Includes anomaly scores, deviation reasons, and trend direction.
    """
    dev = await _require_family_device(session, user, device_id)
    did = dev["device_id"]

    rows = (await session.execute(text("""
        SELECT metric, score, reason_json, window_start, created_at
        FROM device_anomalies
        WHERE device_id = :did
        ORDER BY created_at DESC
        LIMIT 20
    """), {"did": did})).fetchall()

    anomalies = [
        {
            "metric": r.metric,
            "score": round(r.score, 3),
            "reasons": r.reason_json,
            "window_start": r.window_start.isoformat() if r.window_start else None,
            "detected_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    # Also get baseline for context
    baselines = (await session.execute(text("""
        SELECT metric, expected_value, lower_band, upper_band, updated_at
        FROM device_baselines
        WHERE device_id = :did
    """), {"did": did})).fetchall()

    baseline_map = {
        b.metric: {
            "expected_value": round(b.expected_value, 3) if b.expected_value else None,
            "lower_band": round(b.lower_band, 3) if b.lower_band else None,
            "upper_band": round(b.upper_band, 3) if b.upper_band else None,
        }
        for b in baselines
    }

    return {
        "device_id": did,
        "name": dev["name"],
        "anomalies": anomalies,
        "baselines": baseline_map,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 6. Twin Evolution ──

@router.get("/twin-evolution")
async def get_twin_evolution(
    device_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns the digital twin's evolution history — how the behavioural model
    has changed over time as more data is collected.
    """
    dev = await _require_family_device(session, user, device_id)

    from app.services.twin_evolution_engine import get_twin_evolution as fetch_evolution
    evolution = await fetch_evolution(session, dev["device_id"])

    return {
        "device_id": dev["device_id"],
        "name": dev["name"],
        "evolution": evolution,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 7. Hotspot Trends ──

@router.get("/hotspot-trends")
async def get_hotspot_trends(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_km: float = Query(5.0, ge=0.5, le=50),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns safety hotspot trends near a location.
    Includes incident density, time-of-day patterns, and trend direction.
    """
    from app.services.hotspot_trend_engine import get_trend_summary
    trends = await get_trend_summary(session)

    return {
        "lat": lat,
        "lng": lng,
        "radius_km": radius_km,
        "trends": trends,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 8. Family AI Summary ──

@router.get("/family-summary")
async def get_family_ai_summary(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Returns a compact AI summary across all family members.
    Shows risk scores, anomaly counts, and twin confidence per member.
    """
    devices = await _get_family_devices(session, user)
    if not devices:
        return {"members": [], "message": "No linked devices found"}

    members = []
    for dev in devices:
        did = dev["device_id"]

        # Latest risk score
        risk_row = (await session.execute(text("""
            SELECT score, created_at
            FROM safety_scores
            WHERE device_id = :did
            ORDER BY created_at DESC LIMIT 1
        """), {"did": did})).fetchone()

        # Anomaly count (last 24h)
        anomaly_count = (await session.execute(text("""
            SELECT COUNT(*) FROM device_anomalies
            WHERE device_id = :did AND created_at > NOW() - INTERVAL '24 hours'
        """), {"did": did})).scalar() or 0

        # Twin confidence
        twin_row = (await session.execute(text("""
            SELECT confidence_score, profile_summary FROM device_digital_twins
            WHERE device_id = :did
        """), {"did": did})).fetchone()

        members.append({
            "device_id": did,
            "name": dev["name"],
            "risk_score": round(risk_row.score, 2) if risk_row else None,
            "risk_updated_at": risk_row.created_at.isoformat() if risk_row else None,
            "anomalies_24h": anomaly_count,
            "twin_confidence": round(twin_row.confidence_score, 3) if twin_row else None,
            "twin_summary": twin_row.profile_summary if twin_row else None,
        })

    return {
        "family_member_count": len(members),
        "members": members,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
