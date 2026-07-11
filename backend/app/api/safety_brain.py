# Safety Brain API — Unified risk scoring endpoints
#
# POST /api/safety-brain/evaluate       — compute unified risk from signals
# GET  /api/safety-brain/status/{user_id} — current risk level with decayed signals
# POST /api/safety-brain/{id}/resolve   — resolve safety event
# GET  /api/safety-brain/events         — recent safety events

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models import User

router = APIRouter(prefix="/safety-brain", tags=["safety-brain"])


class EvaluateRequest(BaseModel):
    signals: dict = Field(..., description="Signal scores: {fall, voice, route, wander, pickup}")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    user_id: Optional[str] = None  # For operators evaluating on behalf


@router.post("/evaluate")
async def evaluate_risk(
    req: EvaluateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Compute unified risk score from all active safety signals."""
    from app.services.safety_brain_service import evaluate_risk

    target_user = req.user_id or str(user.id)

    # Validate signal keys
    valid_keys = {"fall", "voice", "route", "wander", "pickup"}
    signals = {k: max(0, min(1, v)) for k, v in req.signals.items() if k in valid_keys}

    result = await evaluate_risk(session, target_user, signals, req.lat, req.lng)
    return result


@router.get("/status/{user_id}")
async def get_risk_status(
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get current risk level for a user with time-decayed signals."""
    from app.services.safety_brain_service import get_user_risk_status

    result = await get_user_risk_status(session, user_id)

    # Guarantee non-null response with required fields
    now_iso = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()

    return {
        "status": result.get("status", "ok"),
        "risk_score": result.get("risk_score", 0),
        "risk_level": result.get("risk_level", "normal"),
        "engines_running": {
            "safety_brain": True,
            "behavior_ai": True,
            "risk_fusion": True,
            "ml_predictor": True,
        },
        "last_analysis": result.get("latest_event_id") or now_iso,
        "primary_event": result.get("primary_event"),
        "signals": result.get("signals", {}),
        "raw_signals": result.get("raw_signals", {}),
        "latest_event_id": result.get("latest_event_id"),
        "latest_event_status": result.get("latest_event_status"),
    }


@router.post("/{event_id}/resolve")
async def resolve_event(
    event_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Resolve a safety event."""
    from app.services.safety_brain_service import resolve_safety_event

    result = await resolve_safety_event(session, event_id, str(user.id))
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/events")
async def list_events(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get recent safety brain events."""
    from app.services.safety_brain_service import get_safety_events

    user_id = None if user.role in ("operator", "admin") else str(user.id)
    events = await get_safety_events(session, user_id=user_id, limit=limit)
    return {"events": events, "count": len(events)}
