# Predictive Danger Alert API
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models import User

router = APIRouter(prefix="/predictive-alert", tags=["predictive-alert"])


class LocationInput(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class PredictiveAlertRequest(BaseModel):
    user_id: Optional[str] = None
    location: LocationInput
    route_coords: Optional[list[list[float]]] = None  # [[lng, lat], ...]
    speed: Optional[float] = 1.5
    timestamp: Optional[str] = None


@router.post("")
async def evaluate_prediction(
    req: PredictiveAlertRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Evaluate predictive danger for upcoming route segments."""
    from app.services.predictive_alert_engine import evaluate_predictive_risk

    uid = req.user_id or str(user.id)
    ts = None
    if req.timestamp:
        try:
            ts = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass

    return await evaluate_predictive_risk(
        session, uid, req.location.lat, req.location.lng,
        route_coords=req.route_coords,
        speed_mps=req.speed or 1.5,
        timestamp=ts,
    )


@router.post("/with-alternative")
async def prediction_with_route(
    req: PredictiveAlertRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Evaluate predictive danger AND generate alternative safe route if needed."""
    from app.services.predictive_alert_engine import evaluate_predictive_risk
    from app.services.safe_route_engine import generate_safe_routes

    uid = req.user_id or str(user.id)
    ts = None
    if req.timestamp:
        try:
            ts = datetime.fromisoformat(req.timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass

    prediction = await evaluate_predictive_risk(
        session, uid, req.location.lat, req.location.lng,
        route_coords=req.route_coords,
        speed_mps=req.speed or 1.5,
        timestamp=ts,
    )

    # If danger detected, generate alternative routes
    if prediction.get("alert") and prediction.get("alternative_route_available"):
        # Use current location as origin, find a safe destination beyond the danger zone
        danger_segs = prediction.get("danger_segments", [])
        if danger_segs:
            # Route to a point beyond the last danger segment
            last_danger = danger_segs[-1]
            dest_lat = last_danger["lat"] + 0.005
            dest_lng = last_danger["lng"] + 0.005
        else:
            dest_lat = req.location.lat + 0.01
            dest_lng = req.location.lng + 0.01

        try:
            alt_routes = await generate_safe_routes(
                session, req.location.lat, req.location.lng,
                dest_lat, dest_lng, ts,
            )
            prediction["alternative_routes"] = alt_routes.get("routes", [])
        except Exception as e:
            prediction["alternative_routes"] = []
            prediction["alt_route_error"] = str(e)

    return prediction
