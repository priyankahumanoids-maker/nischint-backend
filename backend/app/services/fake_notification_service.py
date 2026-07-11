# Fake Notification Service — Business logic for escape notifications
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fake_notification import FakeNotificationPreset, FakeNotificationLog
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

DEFAULT_PRESETS = [
    {
        "title": "Team Meeting in 5 min",
        "message": "Your 3:30 PM standup starts soon. Join the call now.",
        "category": "Work",
        "icon_style": "calendar",
        "is_default": True,
    },
    {
        "title": "Your package has arrived",
        "message": "Your delivery is at the front desk. Pick up before 6 PM.",
        "category": "Delivery",
        "icon_style": "package",
        "is_default": True,
    },
    {
        "title": "Security Alert: Verify login",
        "message": "Unusual sign-in detected on your account. Tap to verify now.",
        "category": "Security",
        "icon_style": "shield",
        "is_default": True,
    },
    {
        "title": "Mom: Call me when you can",
        "message": "Hey, tried calling you. Please call back when free. It's important.",
        "category": "Message",
        "icon_style": "message",
        "is_default": True,
    },
]


async def ensure_default_presets(session: AsyncSession, user_id: uuid.UUID):
    result = await session.execute(
        select(func.count()).select_from(FakeNotificationPreset)
        .where(FakeNotificationPreset.user_id == user_id)
    )
    if result.scalar() > 0:
        return
    for p in DEFAULT_PRESETS:
        session.add(FakeNotificationPreset(user_id=user_id, **p))
    await session.flush()
    logger.info(f"Seeded {len(DEFAULT_PRESETS)} default notification presets for user {user_id}")


async def list_presets(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    result = await session.execute(
        select(FakeNotificationPreset)
        .where(FakeNotificationPreset.user_id == user_id)
        .order_by(FakeNotificationPreset.is_default.desc(), FakeNotificationPreset.created_at)
    )
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "message": p.message,
            "category": p.category,
            "icon_style": p.icon_style,
            "auto_dismiss_seconds": p.auto_dismiss_seconds,
            "is_default": p.is_default,
            "created_at": p.created_at.isoformat(),
        }
        for p in result.scalars().all()
    ]


async def create_preset(session: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    preset = FakeNotificationPreset(
        user_id=user_id,
        title=data["title"],
        message=data.get("message", ""),
        category=data.get("category", "Custom"),
        icon_style=data.get("icon_style", "default"),
        auto_dismiss_seconds=data.get("auto_dismiss_seconds"),
        is_default=False,
    )
    session.add(preset)
    await session.flush()
    return {
        "id": str(preset.id),
        "title": preset.title,
        "message": preset.message,
        "category": preset.category,
        "icon_style": preset.icon_style,
        "auto_dismiss_seconds": preset.auto_dismiss_seconds,
        "is_default": False,
        "created_at": preset.created_at.isoformat(),
    }


async def update_preset(session: AsyncSession, user_id: uuid.UUID, preset_id: uuid.UUID, data: dict) -> Optional[dict]:
    result = await session.execute(
        select(FakeNotificationPreset)
        .where(FakeNotificationPreset.id == preset_id, FakeNotificationPreset.user_id == user_id)
    )
    preset = result.scalar_one_or_none()
    if not preset:
        return None
    for key in ("title", "message", "category", "icon_style", "auto_dismiss_seconds"):
        if key in data:
            setattr(preset, key, data[key])
    await session.flush()
    return {
        "id": str(preset.id),
        "title": preset.title,
        "message": preset.message,
        "category": preset.category,
        "icon_style": preset.icon_style,
        "auto_dismiss_seconds": preset.auto_dismiss_seconds,
        "is_default": preset.is_default,
    }


async def delete_preset(session: AsyncSession, user_id: uuid.UUID, preset_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(FakeNotificationPreset)
        .where(
            FakeNotificationPreset.id == preset_id,
            FakeNotificationPreset.user_id == user_id,
            FakeNotificationPreset.is_default.is_(False),
        )
    )
    return result.rowcount > 0


async def trigger_notification(
    session: AsyncSession,
    user_id: uuid.UUID,
    preset_id: Optional[uuid.UUID],
    title: str,
    message: str,
    category: str = "Custom",
    delay_seconds: int = 0,
    trigger_method: str = "manual",
) -> dict:
    log = FakeNotificationLog(
        user_id=user_id,
        preset_id=preset_id,
        title=title,
        message=message,
        category=category,
        trigger_method=trigger_method,
        delay_seconds=delay_seconds,
        status="triggered",
    )
    session.add(log)
    await session.flush()

    notif_data = {
        "notification_id": str(log.id),
        "title": title,
        "message": message,
        "category": category,
        "delay_seconds": delay_seconds,
        "trigger_method": trigger_method,
        "triggered_at": log.triggered_at.isoformat(),
    }

    await broadcaster.broadcast_to_user(str(user_id), "fake_notification_incoming", notif_data)
    logger.info(f"Fake notification triggered for user {user_id}: {title} (delay={delay_seconds}s)")

    from app.services.monitoring_service import record_fake_notification
    record_fake_notification()
    return notif_data


async def complete_notification(
    session: AsyncSession,
    user_id: uuid.UUID,
    notif_id: uuid.UUID,
    viewed: bool = False,
    dismissed: bool = False,
    send_alert: bool = False,
) -> Optional[dict]:
    result = await session.execute(
        select(FakeNotificationLog)
        .where(FakeNotificationLog.id == notif_id, FakeNotificationLog.user_id == user_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        return None

    log.status = "completed"
    log.viewed = viewed
    log.dismissed = dismissed
    log.alert_sent = send_alert
    log.completed_at = datetime.now(timezone.utc)
    await session.flush()

    if send_alert:
        await broadcaster.broadcast_to_user(str(user_id), "escape_alert", {
            "notification_id": str(notif_id),
            "type": "fake_notification_escape",
            "message": f"Escape notification used ({log.title}). Check in with your family member.",
            "timestamp": log.completed_at.isoformat(),
        })
        logger.info(f"Escape alert sent for user {user_id} after notification {notif_id}")

    return {
        "notification_id": str(log.id),
        "status": "completed",
        "viewed": viewed,
        "dismissed": dismissed,
        "alert_sent": send_alert,
    }


async def get_history(session: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> list[dict]:
    result = await session.execute(
        select(FakeNotificationLog)
        .where(FakeNotificationLog.user_id == user_id)
        .order_by(FakeNotificationLog.triggered_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(entry.id),
            "title": entry.title,
            "message": entry.message,
            "category": entry.category,
            "trigger_method": entry.trigger_method,
            "delay_seconds": entry.delay_seconds,
            "status": entry.status,
            "viewed": entry.viewed,
            "dismissed": entry.dismissed,
            "alert_sent": entry.alert_sent,
            "triggered_at": entry.triggered_at.isoformat(),
            "completed_at": entry.completed_at.isoformat() if entry.completed_at else None,
        }
        for entry in result.scalars().all()
    ]
