"""
Device registration and notification API routes.
Handles FCM token registration and notification history.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db, async_session
from app.api.deps import get_db_session, get_current_user
from app.models.user import User

router = APIRouter(prefix="/device", tags=["Device & Notifications"])


class DeviceRegisterRequest(BaseModel):
    device_token: str
    device_type: str = "web"  # web | android | ios
    app_version: Optional[str] = None


class DeviceRegisterResponse(BaseModel):
    status: str
    device_id: Optional[str] = None


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    req: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Register a device token for push notifications (authenticated)."""
    # Ensure table exists
    await _ensure_device_table(db)

    user_id = str(user.id)

    # Upsert device token
    existing = await db.execute(
        text("SELECT id, user_id FROM device_tokens WHERE device_token = :token"),
        {"token": req.device_token}
    )
    row = existing.fetchone()

    if row:
        await db.execute(
            text("""
                UPDATE device_tokens 
                SET is_active = true, device_type = :dtype, user_id = :uid,
                    app_version = :ver, updated_at = :now
                WHERE device_token = :token
            """),
            {
                "token": req.device_token,
                "dtype": req.device_type,
                "uid": user_id,
                "ver": req.app_version,
                "now": datetime.now(timezone.utc),
            }
        )
        await db.commit()
        return DeviceRegisterResponse(status="updated", device_id=str(row[0]))
    else:
        result = await db.execute(
            text("""
                INSERT INTO device_tokens (user_id, device_token, device_type, app_version, is_active, created_at, updated_at)
                VALUES (:uid, :token, :dtype, :ver, true, :now, :now)
                RETURNING id
            """),
            {
                "uid": user_id,
                "token": req.device_token,
                "dtype": req.device_type,
                "ver": req.app_version,
                "now": datetime.now(timezone.utc),
            }
        )
        await db.commit()
        new_row = result.fetchone()
        return DeviceRegisterResponse(status="registered", device_id=str(new_row[0]) if new_row else None)


@router.delete("/unregister")
async def unregister_device(device_token: str, db: AsyncSession = Depends(get_db)):
    """Unregister a device token."""
    await db.execute(
        text("UPDATE device_tokens SET is_active = false WHERE device_token = :token"),
        {"token": device_token}
    )
    await db.commit()
    return {"status": "unregistered"}


@router.get("/notifications")
async def get_notifications(
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get notification history for the current authenticated user."""
    await _ensure_notifications_table(db)
    
    result = await db.execute(
        text("""
            SELECT id, title, body, tag, is_read, created_at 
            FROM push_notifications 
            WHERE user_id = :uid
            ORDER BY created_at DESC 
            LIMIT :limit
        """),
        {"uid": str(user.id), "limit": limit}
    )
    rows = result.fetchall()
    return {
        "notifications": [
            {
                "id": str(r[0]),
                "title": r[1],
                "body": r[2],
                "tag": r[3],
                "is_read": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    }


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, db: AsyncSession = Depends(get_db_session)):
    """Mark a notification as read."""
    await db.execute(
        text("UPDATE push_notifications SET is_read = true WHERE id = :id"),
        {"id": int(notification_id)}  # Cast to int as database column is SERIAL (integer)
    )
    await db.commit()
    return {"status": "read"}


@router.get("/push-status")
async def push_status(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Check if user has push notifications registered."""
    await _ensure_device_table(db)
    result = await db.execute(
        text("SELECT COUNT(*) FROM device_tokens WHERE user_id = :uid AND is_active = true"),
        {"uid": str(user.id)}
    )
    count = result.scalar() or 0

    from app.services.notification_service import NotificationService
    from app.db.session import async_session
    ns = NotificationService(async_session)

    return {
        "push_enabled": count > 0,
        "devices_registered": count,
        "fcm_active": ns.fcm_available,
    }


async def _ensure_device_table(db: AsyncSession):
    """Create device_tokens table if it doesn't exist."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS device_tokens (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            device_token TEXT NOT NULL UNIQUE,
            device_type VARCHAR(20) DEFAULT 'web',
            app_version VARCHAR(50),
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """))
    await db.commit()


async def _ensure_notifications_table(db: AsyncSession):
    """Create push_notifications table if it doesn't exist."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS push_notifications (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL,
            title VARCHAR(255) NOT NULL,
            body TEXT,
            data TEXT,
            tag VARCHAR(100),
            is_read BOOLEAN DEFAULT false,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """))
    await db.commit()
