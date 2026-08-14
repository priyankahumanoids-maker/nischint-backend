# Check-In API — 2-way safety check between guardian and child
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User

router = APIRouter(prefix="/checkin", tags=["checkin"])


class CheckInResponse(BaseModel):
    response: str  # "safe" or "help"


class SafeStatusRequest(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    message: str | None = Field(None, max_length=240)


@router.post("/safe-status")
async def report_safe_status(
    body: SafeStatusRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Protected member proactively reassures every linked guardian."""
    from app.services.checkin_service import report_safe_status as _report_safe
    result = await _report_safe(
        session,
        str(user.id),
        lat=body.lat,
        lng=body.lng,
        message=body.message,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{child_user_id}")
async def create_checkin(
    child_user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian initiates a safety check-in for a child."""
    from app.services.checkin_service import create_checkin as _create
    result = await _create(session, str(user.id), child_user_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/pending")
async def get_pending_checkins(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Child fetches their pending check-ins."""
    from app.services.checkin_service import get_pending_checkins as _get
    checkins = await _get(session, str(user.id))
    return {"check_ins": checkins}


@router.post("/{check_in_id}/respond")
async def respond_to_checkin(
    check_in_id: str,
    body: CheckInResponse,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Child responds to a check-in (safe or help)."""
    if body.response not in ("safe", "help"):
        raise HTTPException(status_code=400, detail="Response must be 'safe' or 'help'")
    from app.services.checkin_service import respond_to_checkin as _respond
    result = await _respond(session, check_in_id, str(user.id), body.response)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/status/{check_in_id}")
async def get_checkin_status(
    check_in_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian checks the status of a check-in."""
    from app.services.checkin_service import get_checkin_status as _status
    result = await _status(session, check_in_id)
    if not result:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return result


@router.get("/latest/{child_user_id}")
async def get_latest_checkin(
    child_user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian gets the latest check-in status for a specific child."""
    from app.services.checkin_service import get_latest_checkin_for_child as _latest
    result = await _latest(session, str(user.id), child_user_id)
    return result or {"status": "none"}
