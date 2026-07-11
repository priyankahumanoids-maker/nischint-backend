"""
Notification Preferences API — User notification settings.
Critical safety alerts are always ON. Other categories are toggleable.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rate_limiter import limiter
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["User Settings"])


class NotificationPreferencesResponse(BaseModel):
    general_notifications: bool = True
    guardian_alerts: bool = True
    incident_updates: bool = True
    daily_summary: bool = False
    push_enabled: bool = True
    sms_enabled: bool = True


class NotificationPreferencesUpdate(BaseModel):
    general_notifications: Optional[bool] = None
    guardian_alerts: Optional[bool] = None
    incident_updates: Optional[bool] = None
    daily_summary: Optional[bool] = None
    push_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None


@router.get("/notifications")
@limiter.limit("30/minute")
async def get_notification_preferences(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get current user's notification preferences."""
    result = await session.execute(
        text("SELECT * FROM notification_preferences WHERE user_id = :uid"),
        {"uid": str(user.id)},
    )
    row = result.mappings().first()

    if not row:
        # Return defaults
        return {
            "general_notifications": True,
            "guardian_alerts": True,
            "incident_updates": True,
            "daily_summary": False,
            "push_enabled": True,
            "sms_enabled": True,
        }

    return {
        "general_notifications": row.get("general_notifications", True),
        "guardian_alerts": row.get("guardian_alerts", True),
        "incident_updates": row.get("incident_updates", True),
        "daily_summary": row.get("daily_summary", False),
        "push_enabled": row.get("push_enabled", True),
        "sms_enabled": row.get("sms_enabled", True),
    }


@router.put("/notifications")
@limiter.limit("10/minute")
async def update_notification_preferences(
    request: Request,
    body: NotificationPreferencesUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Update notification preferences. Critical safety alerts cannot be disabled."""
    # Check if preferences exist
    result = await session.execute(
        text("SELECT id FROM notification_preferences WHERE user_id = :uid"),
        {"uid": str(user.id)},
    )
    existing = result.first()

    updates = {k: v for k, v in body.dict().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc)

    if existing:
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        await session.execute(
            text(f"UPDATE notification_preferences SET {set_clauses} WHERE user_id = :uid"),
            {**updates, "uid": str(user.id)},
        )
    else:
        defaults = {
            "user_id": str(user.id),
            "general_notifications": True,
            "guardian_alerts": True,
            "incident_updates": True,
            "daily_summary": False,
            "push_enabled": True,
            "sms_enabled": True,
            "updated_at": datetime.now(timezone.utc),
        }
        defaults.update(updates)
        cols = ", ".join(defaults.keys())
        vals = ", ".join(f":{k}" for k in defaults.keys())
        await session.execute(
            text(f"INSERT INTO notification_preferences ({cols}) VALUES ({vals})"),
            defaults,
        )

    await session.commit()

    return {"status": "success", "message": "Notification preferences updated"}
