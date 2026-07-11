# Safe Route API — Safety-Aware Routing
# Supports modes: fastest, safest, balanced, night_guardian
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models import User

router = APIRouter(prefix="/safe-route", tags=["safe-route"])


class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class SafeRouteRequest(BaseModel):
    origin: LocationInput
    destination: LocationInput
    mode: str = "balanced"  # fastest | safest | balanced | night_guardian
    time: Optional[str] = None  # "23:30" or ISO timestamp


@router.post("")
async def generate_route(
    req: SafeRouteRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Generate safety-aware routes between two points.

    Modes:
    - **fastest**: Prioritizes shortest travel time (80% time, 20% safety)
    - **safest**: Prioritizes lowest risk (20% time, 80% safety)
    - **balanced**: Equal weighting (50/50)
    - **night_guardian**: Auto-activated at night, 80% safety / 20% time

    Returns 3 route options with per-segment risk scoring and color coding.
    """
    from app.services.safe_route_engine import generate_safe_routes

    if req.mode not in ("fastest", "safest", "balanced", "night_guardian"):
        raise HTTPException(400, f"Invalid mode: {req.mode}. Use: fastest, safest, balanced, night_guardian")

    ts = None
    if req.time:
        try:
            if "T" in req.time:
                ts = datetime.fromisoformat(req.time.replace("Z", "+00:00"))
            else:
                parts = req.time.split(":")
                now = datetime.now(timezone.utc)
                ts = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
        except (ValueError, IndexError):
            pass

    result = await generate_safe_routes(
        session, req.origin.lat, req.origin.lng,
        req.destination.lat, req.destination.lng,
        timestamp=ts,
        mode=req.mode,
    )
    if "error" in result and not result.get("routes"):
        raise HTTPException(502, result["error"])

    # Generate corridor polygon for each route (for live monitoring visualization)
    from app.services.route_monitor_service import generate_corridor
    for route in result.get("routes", []):
        geom = route.get("geometry")
        if geom and isinstance(geom, dict):
            coords = geom.get("coordinates", [])
            if coords and len(coords) >= 2:
                corridor = generate_corridor(coords, route.get("type", req.mode))
                route["corridor"] = corridor

    return result
