# Fake Notification API — Escape notification management and triggering
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.user import User
from app.services import fake_notification_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fake-notification", tags=["fake-notification"])

_escape_role = require_role(["guardian", "operator", "admin"])


# ── Schemas ──

class PresetCreate(BaseModel):
    title: str = Field(..., max_length=200)
    message: str = Field("", max_length=500)
    category: str = Field("Custom", max_length=50)
    icon_style: str = Field("default", max_length=30)
    auto_dismiss_seconds: Optional[int] = Field(None, ge=0, le=120)


class PresetUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    message: Optional[str] = Field(None, max_length=500)
    category: Optional[str] = Field(None, max_length=50)
    icon_style: Optional[str] = Field(None, max_length=30)
    auto_dismiss_seconds: Optional[int] = Field(None, ge=0, le=120)


class TriggerNotification(BaseModel):
    preset_id: Optional[str] = None
    title: Optional[str] = Field(None, max_length=200)
    message: Optional[str] = Field(None, max_length=500)
    category: str = Field("Custom", max_length=50)
    delay_seconds: int = Field(0, ge=0, le=300)
    trigger_method: str = Field("manual", max_length=30)


class CompleteNotification(BaseModel):
    viewed: bool = False
    dismissed: bool = False
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
async def trigger_notification(
    body: TriggerNotification,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    preset_uuid = uuid.UUID(body.preset_id) if body.preset_id else None

    title = body.title
    message = body.message or ""
    category = body.category

    if not title and preset_uuid:
        presets = await svc.list_presets(session, user.id)
        match = next((p for p in presets if p["id"] == body.preset_id), None)
        if match:
            title = match["title"]
            message = match["message"]
            category = match["category"]

    if not title:
        title = "New Notification"

    return await svc.trigger_notification(
        session, user.id, preset_uuid,
        title=title, message=message, category=category,
        delay_seconds=body.delay_seconds,
        trigger_method=body.trigger_method,
    )


@router.post("/complete/{notif_id}")
async def complete_notification(
    notif_id: str,
    body: CompleteNotification,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    result = await svc.complete_notification(
        session, user.id, uuid.UUID(notif_id),
        viewed=body.viewed, dismissed=body.dismissed, send_alert=body.send_alert,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Notification not found")
    return result


# ── History ──

@router.get("/history")
async def notification_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    logs = await svc.get_history(session, user.id, limit)
    return {"history": logs, "count": len(logs)}
