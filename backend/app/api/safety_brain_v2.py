# 3-Layer AI Safety Brain API
#
# GET  /api/safety-brain/v2/fused-risk/{user_id}    — 3-layer fused risk
# GET  /api/safety-brain/v2/location-risk/{user_id}  — Location danger score
# GET  /api/safety-brain/v2/behavior/{user_id}        — Behavioral pattern analysis
# GET  /api/safety-brain/v2/predictive/{user_id}      — Predictive alert + AI narrative
# GET  /api/safety-brain/v2/heatmap                    — Danger heatmap data

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.core.rbac import require_role
from app.models import User

router = APIRouter(prefix="/safety-brain/v2", tags=["safety-brain-v2"])

_safety_role = require_role(["guardian", "operator", "caregiver", "admin"])


@router.get("/fused-risk/{user_id}")
async def get_fused_risk(
    user_id: str,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    skip_behavior: bool = Query(False, description="Skip Layer 3 for fast evaluation"),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_safety_role),
):
    """
    Compute full 3-layer fused risk score.
    Layer 1: Real-time signals (50%)
    Layer 2: Location intelligence (25%)
    Layer 3: Behavioral patterns (25%)
    """
    from app.services.risk_fusion import compute_fused_risk
    from app.services.safety_brain_service import get_user_risk_status

    # Get current real-time signals from Safety Brain
    rt_status = await get_user_risk_status(session, user_id)
    rt_score = rt_status.get("risk_score", 0.0)
    rt_signals = rt_status.get("signals", {})

    result = await compute_fused_risk(
        session=session,
        user_id=user_id,
        realtime_score=rt_score,
        realtime_signals=rt_signals,
        lat=lat, lng=lng,
        skip_behavior=skip_behavior,
    )
    return result


@router.get("/location-risk/{user_id}")
async def get_location_risk(
    user_id: str,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_safety_role),
):
    """Get location danger score for current position."""
    from app.services.location_intelligence import compute_location_risk

    result = await compute_location_risk(session, lat, lng)
    return {"user_id": user_id, **result}


@router.get("/behavior/{user_id}")
async def get_behavior_analysis(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_safety_role),
):
    """Get behavioral pattern analysis across 7/14/30 day windows."""
    from app.services.behavior_analyzer import analyze_behavior

    result = await analyze_behavior(session, user_id)
    return {"user_id": user_id, **result}


@router.get("/predictive/{user_id}")
async def get_predictive_alert(
    user_id: str,
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_safety_role),
):
    """
    Full predictive safety analysis with AI-generated narrative.
    Combines behavioral patterns + location intelligence + GPT-5.2 explanation.
    """
    from app.services.predictive_alerts import evaluate_predictive_alert

    result = await evaluate_predictive_alert(session, user_id, lat, lng)
    return result


@router.get("/heatmap")
async def get_danger_heatmap(
    south: Optional[float] = Query(None),
    north: Optional[float] = Query(None),
    west: Optional[float] = Query(None),
    east: Optional[float] = Query(None),
    limit: int = Query(200, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_safety_role),
):
    """Get danger heatmap data points for map overlay."""
    from app.services.location_intelligence import get_danger_heatmap

    bounds = None
    if all(v is not None for v in [south, north, west, east]):
        bounds = {"south": south, "north": north, "west": west, "east": east}

    data = await get_danger_heatmap(session, bounds=bounds, limit=limit)
    return {"heatmap": data, "count": len(data)}
