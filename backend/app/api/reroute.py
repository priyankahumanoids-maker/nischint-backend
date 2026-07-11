# Predictive Safety Reroute API
#
# POST /api/reroute/suggest           — Compute safer route (manual or auto)
# POST /api/reroute/{id}/approve      — Guardian approves reroute
# POST /api/reroute/{id}/dismiss      — Guardian dismisses suggestion
# GET  /api/reroute/history           — Past reroute suggestions

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models import User

router = APIRouter(prefix="/reroute", tags=["reroute"])


class RerouteSuggestRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Current latitude")
    lng: float = Field(..., ge=-180, le=180, description="Current longitude")
    destination_lat: Optional[float] = Field(None, ge=-90, le=90)
    destination_lng: Optional[float] = Field(None, ge=-180, le=180)
    reason: str = Field("Manual reroute request", description="Why reroute is needed")


@router.post("/suggest")
async def suggest_reroute(
    req: RerouteSuggestRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Manually trigger a safer route suggestion."""
    from app.services.predictive_reroute_service import suggest_reroute as _suggest

    result = await _suggest(
        session=session,
        user_id=str(user.id),
        current_lat=req.lat,
        current_lng=req.lng,
        destination_lat=req.destination_lat,
        destination_lng=req.destination_lng,
        trigger_type="manual",
        risk_score=0.0,
        risk_level="manual",
        reason=req.reason,
    )

    if result.get("status") == "cooldown":
        raise HTTPException(429, result["message"])
    if result.get("status") == "error":
        raise HTTPException(400, result["message"])
    return result


@router.post("/{suggestion_id}/approve")
async def approve_reroute(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Approve a reroute suggestion — switch to safer route."""
    from app.services.predictive_reroute_service import approve_reroute as _approve

    result = await _approve(session, suggestion_id, str(user.id))
    if "error" in result:
        raise HTTPException(404 if "not found" in result["error"].lower() else 400, result["error"])
    return result


@router.post("/{suggestion_id}/dismiss")
async def dismiss_reroute(
    suggestion_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Dismiss a reroute suggestion."""
    from app.services.predictive_reroute_service import dismiss_reroute as _dismiss

    result = await _dismiss(session, suggestion_id, str(user.id))
    if "error" in result:
        raise HTTPException(404 if "not found" in result["error"].lower() else 400, result["error"])
    return result


@router.get("/history")
async def reroute_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get past reroute suggestions."""
    from app.services.predictive_reroute_service import get_reroute_history

    user_id = None if user.role in ("operator", "admin") else str(user.id)
    history = await get_reroute_history(session, user_id=user_id, limit=limit)
    return {"suggestions": history, "count": len(history)}
