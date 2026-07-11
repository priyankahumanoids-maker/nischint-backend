# Guardian AI API — Predictive intelligence endpoints
import logging
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.user import User
from app.services import guardian_ai_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/guardian-ai", tags=["guardian-ai"])

_ai_role = require_role(["guardian", "operator", "admin"])


class ConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    sensitivity: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    notification_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    call_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    sos_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    auto_trigger: Optional[bool] = None
    cooldown_minutes: Optional[int] = Field(None, ge=5, le=1440)


class PredictRisk(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


class RespondAction(BaseModel):
    response: str = Field("accept", pattern="^(accept|dismiss)$")


@router.get("/config")
async def get_config(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_ai_role),
):
    config = await svc.get_or_create_config(session, user.id)
    await session.commit()
    return config


@router.put("/config")
async def update_config(
    body: ConfigUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_ai_role),
):
    return await svc.update_config(session, user.id, body.model_dump(exclude_unset=True))


@router.post("/predict-risk")
async def predict_risk(
    body: PredictRisk,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_ai_role),
):
    return await svc.predict_risk(session, user.id, lat=body.lat, lng=body.lng)


@router.post("/accept-action/{prediction_id}")
async def accept_action(
    prediction_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_ai_role),
):
    result = await svc.respond_to_prediction(
        session, user.id, uuid.UUID(prediction_id), "accept",
    )
    if not result:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return result


@router.post("/dismiss/{prediction_id}")
async def dismiss_prediction(
    prediction_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_ai_role),
):
    result = await svc.respond_to_prediction(
        session, user.id, uuid.UUID(prediction_id), "dismiss",
    )
    if not result:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return result


@router.get("/history")
async def prediction_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_ai_role),
):
    predictions = await svc.get_history(session, user.id, limit)
    return {"predictions": predictions, "count": len(predictions)}
