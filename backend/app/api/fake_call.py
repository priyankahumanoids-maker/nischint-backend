# Fake Call API — Escape call management and triggering
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.user import User
from app.services import fake_call_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fake-call", tags=["fake-call"])

# Role access: guardian, operator, admin
_escape_role = require_role(["guardian", "operator", "admin"])


# ── Schemas ──

class PresetCreate(BaseModel):
    caller_name: str = Field(..., max_length=120)
    caller_label: str = Field("Custom", max_length=50)
    caller_avatar_url: Optional[str] = None
    ringtone_style: str = Field("default", max_length=30)
    auto_answer_seconds: Optional[int] = Field(None, ge=0, le=120)


class PresetUpdate(BaseModel):
    caller_name: Optional[str] = Field(None, max_length=120)
    caller_label: Optional[str] = Field(None, max_length=50)
    caller_avatar_url: Optional[str] = None
    ringtone_style: Optional[str] = Field(None, max_length=30)
    auto_answer_seconds: Optional[int] = Field(None, ge=0, le=120)


class TriggerCall(BaseModel):
    preset_id: Optional[str] = None
    caller_name: Optional[str] = Field(None, max_length=120)
    delay_seconds: int = Field(0, ge=0, le=300)
    trigger_method: str = Field("manual", max_length=30)
    lat: Optional[float] = None
    lng: Optional[float] = None


class CompleteCall(BaseModel):
    answered: bool = False
    duration_seconds: int = Field(0, ge=0)
    send_alert: bool = False


# ── Presets ──

@router.get("/presets")
async def list_presets(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    await svc.ensure_default_presets(session, user.id)
    await session.commit()
    presets = await svc.list_presets(session, user.id)
    return {"presets": presets}


@router.post("/presets", status_code=status.HTTP_201_CREATED)
async def create_preset(
    body: PresetCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    return await svc.create_preset(session, user.id, body.model_dump())


@router.put("/presets/{preset_id}")
async def update_preset(
    preset_id: str,
    body: PresetUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    result = await svc.update_preset(session, user.id, uuid.UUID(preset_id), body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail="Preset not found")
    return result


@router.delete("/presets/{preset_id}")
async def delete_preset(
    preset_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    ok = await svc.delete_preset(session, user.id, uuid.UUID(preset_id))
    if not ok:
        raise HTTPException(status_code=404, detail="Preset not found or is default")
    return {"deleted": True}


# ── Trigger ──

@router.post("/trigger")
async def trigger_call(
    body: TriggerCall,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    preset_uuid = uuid.UUID(body.preset_id) if body.preset_id else None

    # Resolve caller_name: from preset or body
    caller_name = body.caller_name
    if not caller_name and preset_uuid:
        presets = await svc.list_presets(session, user.id)
        match = next((p for p in presets if p["id"] == body.preset_id), None)
        if match:
            caller_name = match["caller_name"]
    if not caller_name:
        caller_name = "Unknown Caller"

    return await svc.trigger_fake_call(
        session,
        user.id,
        preset_uuid,
        caller_name,
        delay_seconds=body.delay_seconds,
        trigger_method=body.trigger_method,
        lat=body.lat,
        lng=body.lng,
    )


@router.post("/complete/{call_id}")
async def complete_call(
    call_id: str,
    body: CompleteCall,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    result = await svc.complete_fake_call(
        session, user.id, uuid.UUID(call_id),
        answered=body.answered,
        duration_seconds=body.duration_seconds,
        send_alert=body.send_alert,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Call not found")
    return result


# ── History ──

@router.get("/history")
async def call_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    logs = await svc.get_call_history(session, user.id, limit)
    return {"history": logs, "count": len(logs)}
