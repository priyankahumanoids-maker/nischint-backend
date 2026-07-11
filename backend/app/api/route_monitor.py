# Consumer Route Monitor API — Live route tracking with corridor deviation detection
#
# Endpoints:
#   POST /api/route-monitor/start    — Start monitoring a route
#   POST /api/route-monitor/stop     — Stop monitoring
#   POST /api/route-monitor/location — Process GPS location update
#   GET  /api/route-monitor/session  — Get current monitoring session

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.api.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/route-monitor", tags=["route-monitor"])


class StartMonitorRequest(BaseModel):
    route_coords: list[list[float]] = Field(..., min_length=2, description="[[lng,lat], ...] route polyline")
    mode: str = Field("balanced", description="Route mode: fastest|safest|balanced|night_guardian")
    destination: dict = Field(default_factory=dict, description="Destination {lat, lng, name}")
    route_risk_score: float = Field(5.0, ge=0, le=10, description="Overall route risk score")


class LocationUpdateRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


@router.post("/start")
async def start_monitoring(
    req: StartMonitorRequest,
    user: User = Depends(get_current_user),
):
    """Start live route monitoring. Generates corridor and stores in Redis."""
    from app.services.route_monitor_service import start_route_monitoring

    if req.mode not in ("fastest", "safest", "balanced", "night_guardian"):
        raise HTTPException(400, f"Invalid mode: {req.mode}")

    result = await start_route_monitoring(
        user_id=str(user.id),
        route_coords=req.route_coords,
        mode=req.mode,
        destination=req.destination,
        route_risk_score=req.route_risk_score,
    )

    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/stop")
async def stop_monitoring(
    user: User = Depends(get_current_user),
):
    """Stop live route monitoring. Returns journey summary."""
    from app.services.route_monitor_service import stop_route_monitoring

    result = await stop_route_monitoring(str(user.id))
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/location")
async def update_location(
    req: LocationUpdateRequest,
    user: User = Depends(get_current_user),
):
    """Process GPS location update against active route corridor."""
    from app.services.route_monitor_service import process_location_update

    result = await process_location_update(str(user.id), req.lat, req.lng)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/session")
async def get_session(
    user: User = Depends(get_current_user),
):
    """Get current route monitoring session status."""
    from app.services.route_monitor_service import get_monitoring_session

    session = get_monitoring_session(str(user.id))
    if not session:
        return {"status": "none", "message": "No active route monitoring session"}

    # Don't return full corridor/trail in session status (too large)
    return {
        "status": session.get("status", "unknown"),
        "user_id": session.get("user_id"),
        "mode": session.get("mode"),
        "corridor_width_m": session.get("corridor", {}).get("properties", {}).get("width_m"),
        "destination": session.get("destination"),
        "route_risk_score": session.get("route_risk_score"),
        "started_at": session.get("started_at"),
        "last_update": session.get("last_update"),
        "trail_length": len(session.get("trail", [])),
        "escalation_level": session.get("escalation_level", 0),
        "off_route_count": session.get("off_route_count", 0),
        "total_deviations": session.get("total_deviations", 0),
        "max_distance_m": session.get("max_distance_m", 0),
    }
