# Safety API — Consumer-facing safe zone detection
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models import User

router = APIRouter(prefix="/safety", tags=["safety"])


class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class CheckZoneRequest(BaseModel):
    user_id: Optional[str] = None
    location: LocationInput
    timestamp: Optional[str] = None


@router.post("/check-zone")
async def check_zone_endpoint(
    req: CheckZoneRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Check the safety zone for a location. Returns risk level, score, and recommendations."""
    from app.services.safe_zone_engine import check_zone

    uid = req.user_id or str(user.id)
    ts = None
    if req.timestamp:
        try:
            ts = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass

    result = await check_zone(session, uid, req.location.lat, req.location.lng, ts)
    return result


@router.get("/zone-map")
async def get_zone_map_endpoint(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Return all active risk zones for map rendering."""
    from app.services.safe_zone_engine import get_zone_map
    return await get_zone_map(session)
