# Pickup Verification API
#
# POST /api/pickup/authorize      — create pickup authorization
# POST /api/pickup/verify          — verify pickup (code + proximity)
# POST /api/pickup/{id}/cancel     — cancel authorization
# GET  /api/pickup/authorizations  — list pending authorizations
# GET  /api/pickup/events          — list pickup events

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models import User

router = APIRouter(prefix="/pickup", tags=["pickup"])


class AuthorizeRequest(BaseModel):
    user_id: str = Field(..., description="ID of user being picked up")
    authorized_person_name: str = Field(..., min_length=1, max_length=150)
    authorized_person_phone: Optional[str] = None
    verification_method: str = Field("pin", description="pin or qr")
    pickup_location_lat: float = Field(..., ge=-90, le=90)
    pickup_location_lng: float = Field(..., ge=-180, le=180)
    pickup_radius_m: float = Field(50, ge=10, le=500)
    pickup_location_name: Optional[str] = None
    scheduled_time: datetime


class VerifyRequest(BaseModel):
    authorization_id: str
    pickup_code: str = Field(..., min_length=4, max_length=10)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


@router.post("/authorize")
async def authorize_pickup(
    req: AuthorizeRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Create a pickup authorization. Returns the pickup code to share with the authorized person."""
    from app.services.pickup_verification_service import create_authorization

    if req.verification_method not in ("pin", "qr"):
        raise HTTPException(400, "verification_method must be 'pin' or 'qr'")

    result = await create_authorization(
        session=session,
        guardian_id=str(user.id),
        user_id=req.user_id,
        authorized_person_name=req.authorized_person_name,
        authorized_person_phone=req.authorized_person_phone,
        verification_method=req.verification_method,
        pickup_location_lat=req.pickup_location_lat,
        pickup_location_lng=req.pickup_location_lng,
        pickup_radius_m=req.pickup_radius_m,
        pickup_location_name=req.pickup_location_name,
        scheduled_time=req.scheduled_time,
    )
    return result


@router.post("/verify")
async def verify_pickup(
    req: VerifyRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Verify a pickup. Checks code validity and proximity. No auth required (pickup person uses code)."""
    from app.services.pickup_verification_service import verify_pickup

    result = await verify_pickup(session, req.authorization_id, req.pickup_code, req.lat, req.lng)

    if result.get("status") == "rate_limited":
        raise HTTPException(429, result["message"])
    if result.get("status") == "not_found":
        raise HTTPException(404, result["message"])
    return result


@router.post("/{auth_id}/cancel")
async def cancel_pickup(
    auth_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Cancel a pickup authorization."""
    from app.services.pickup_verification_service import cancel_authorization

    result = await cancel_authorization(session, auth_id, str(user.id))
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/authorizations")
async def list_authorizations(
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List pickup authorizations for the current guardian."""
    from app.services.pickup_verification_service import get_authorizations

    auths = await get_authorizations(session, str(user.id), status=status)
    return {"authorizations": auths, "count": len(auths)}


@router.get("/events")
async def list_events(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List pickup verification events."""
    from app.services.pickup_verification_service import get_pickup_events

    guardian_id = None if user.role in ("operator", "admin") else str(user.id)
    events = await get_pickup_events(session, guardian_id=guardian_id, limit=limit)
    return {"events": events, "count": len(events)}
