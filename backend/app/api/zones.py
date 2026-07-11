# Safe Zones API — CRUD for user safe zones
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models import User

router = APIRouter(prefix="/zones", tags=["zones"])


class CreateZoneRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    radius_m: float = Field(100, ge=20, le=5000)
    zone_type: str = Field("custom", description="home|school|care_facility|custom")


@router.post("/safe-zone")
async def create_zone(
    req: CreateZoneRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.wandering_detection_service import create_safe_zone

    if req.zone_type not in ("home", "school", "care_facility", "custom"):
        raise HTTPException(400, f"Invalid zone_type: {req.zone_type}")

    result = await create_safe_zone(session, str(user.id), req.name, req.lat, req.lng, req.radius_m, req.zone_type)
    return result


@router.get("/safe-zones")
async def list_zones(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.wandering_detection_service import get_safe_zones

    zones = await get_safe_zones(session, str(user.id))
    return {"zones": zones, "count": len(zones)}


@router.delete("/safe-zone/{zone_id}")
async def remove_zone(
    zone_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.wandering_detection_service import delete_safe_zone

    result = await delete_safe_zone(session, zone_id, str(user.id))
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
