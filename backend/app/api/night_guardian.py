# Night Guardian API — Active safety monitoring during night journeys
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models import User

router = APIRouter(prefix="/night-guardian", tags=["night-guardian"])


class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RoutePoint(BaseModel):
    lat: float
    lng: float


class StartRequest(BaseModel):
    user_id: Optional[str] = None
    location: LocationInput
    destination: Optional[LocationInput] = None
    route_points: Optional[list[RoutePoint]] = None


class UpdateLocationRequest(BaseModel):
    user_id: Optional[str] = None
    location: LocationInput
    timestamp: Optional[str] = None


class StopRequest(BaseModel):
    user_id: Optional[str] = None


@router.post("/start")
async def start_guardian(
    req: StartRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Start Night Safety Guardian monitoring."""
    from app.services.night_guardian_engine import start_session

    uid = req.user_id or str(user.id)
    route_pts = [{"lat": p.lat, "lng": p.lng} for p in req.route_points] if req.route_points else None

    result = await start_session(
        session, uid,
        req.location.lat, req.location.lng,
        dest_lat=req.destination.lat if req.destination else None,
        dest_lng=req.destination.lng if req.destination else None,
        route_points=route_pts,
    )
    return result


@router.post("/stop")
async def stop_guardian(
    req: StopRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Stop Night Safety Guardian monitoring."""
    from app.services.night_guardian_engine import stop_session

    uid = req.user_id or str(user.id)
    return await stop_session(session, uid)


@router.get("/status")
async def guardian_status(
    user_id: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get current Night Guardian status for a user."""
    from app.services.night_guardian_engine import get_session_status

    uid = user_id or str(user.id)
    status = await get_session_status(session, uid)
    if not status:
        return {"active": False, "user_id": uid, "message": "No active guardian session"}
    return status


@router.get("/sessions")
async def list_active_sessions(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List all active Night Guardian sessions (operator view)."""
    from app.services.night_guardian_engine import get_all_active_sessions

    if user.role != "operator":
        raise HTTPException(403, "Operator access required")
    return {"sessions": await get_all_active_sessions(session)}


@router.post("/update-location")
async def update_user_location(
    req: UpdateLocationRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Process a location update during active monitoring."""
    from app.services.night_guardian_engine import update_location

    uid = req.user_id or str(user.id)
    ts = None
    if req.timestamp:
        try:
            ts = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass

    result = await update_location(session, uid, req.location.lat, req.location.lng, ts)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/acknowledge-safety")
async def acknowledge_safety(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
    user_id: Optional[str] = None,
):
    """Acknowledge a safety check (user confirms they are safe)."""
    from app.services.night_guardian_engine import acknowledge_safety_check

    uid = user_id or str(user.id)
    result = await acknowledge_safety_check(session, uid)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
