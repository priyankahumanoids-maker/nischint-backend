# Safety Score API (Phase 40)
# Location, Route, and Journey safety scores.

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User

router = APIRouter(prefix="/safety-score", tags=["safety-score"])


class RouteScoreRequest(BaseModel):
    origin: dict  # {"lat": float, "lng": float}
    destination: dict


@router.get("/location")
async def get_location_score(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get safety score for a specific location."""
    from app.services.location_safety_score_engine import calculate_location_score
    return await calculate_location_score(session, lat, lng)


@router.post("/route")
async def get_route_score(
    req: RouteScoreRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get safety score for a route between two points."""
    from app.services.location_safety_score_engine import calculate_route_score
    return await calculate_route_score(session, req.origin, req.destination)


@router.get("/journey/{session_id}")
async def get_journey_score(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get safety score for a completed or active guardian journey."""
    from app.services.location_safety_score_engine import calculate_journey_score
    result = await calculate_journey_score(session, session_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
