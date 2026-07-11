# Fake Call Service — Business logic for escape call system
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fake_call import FakeCallPreset, FakeCallLog
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

# ── Default presets seeded per user ──
DEFAULT_PRESETS = [
    {"caller_name": "Mom", "caller_label": "Family", "ringtone_style": "classic", "is_default": True},
    {"caller_name": "Boss", "caller_label": "Work", "ringtone_style": "professional"},
    {"caller_name": "Best Friend", "caller_label": "Friend", "ringtone_style": "upbeat"},
]


async def ensure_default_presets(session: AsyncSession, user_id: uuid.UUID):
    """Create default presets if user has none."""
    result = await session.execute(
        select(func.count()).select_from(FakeCallPreset).where(FakeCallPreset.user_id == user_id)
    )
    count = result.scalar()
    if count > 0:
        return
    for p in DEFAULT_PRESETS:
        preset = FakeCallPreset(user_id=user_id, **p)
        session.add(preset)
    await session.flush()
    logger.info(f"Seeded {len(DEFAULT_PRESETS)} default fake call presets for user {user_id}")


async def list_presets(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    result = await session.execute(
        select(FakeCallPreset)
        .where(FakeCallPreset.user_id == user_id)
        .order_by(FakeCallPreset.is_default.desc(), FakeCallPreset.created_at)
    )
    presets = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "caller_name": p.caller_name,
            "caller_label": p.caller_label,
            "caller_avatar_url": p.caller_avatar_url,
            "ringtone_style": p.ringtone_style,
            "auto_answer_seconds": p.auto_answer_seconds,
            "is_default": p.is_default,
            "created_at": p.created_at.isoformat(),
        }
        for p in presets
    ]


async def create_preset(session: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    preset = FakeCallPreset(
        user_id=user_id,
        caller_name=data["caller_name"],
        caller_label=data.get("caller_label", "Custom"),
        caller_avatar_url=data.get("caller_avatar_url"),
        ringtone_style=data.get("ringtone_style", "default"),
        auto_answer_seconds=data.get("auto_answer_seconds"),
        is_default=False,
    )
    session.add(preset)
    await session.flush()
    return {
        "id": str(preset.id),
        "caller_name": preset.caller_name,
        "caller_label": preset.caller_label,
        "ringtone_style": preset.ringtone_style,
        "auto_answer_seconds": preset.auto_answer_seconds,
        "is_default": False,
        "created_at": preset.created_at.isoformat(),
    }


async def update_preset(session: AsyncSession, user_id: uuid.UUID, preset_id: uuid.UUID, data: dict) -> Optional[dict]:
    result = await session.execute(
        select(FakeCallPreset).where(FakeCallPreset.id == preset_id, FakeCallPreset.user_id == user_id)
    )
    preset = result.scalar_one_or_none()
    if not preset:
        return None
    for key in ("caller_name", "caller_label", "caller_avatar_url", "ringtone_style", "auto_answer_seconds"):
        if key in data:
            setattr(preset, key, data[key])
    await session.flush()
    return {
        "id": str(preset.id),
        "caller_name": preset.caller_name,
        "caller_label": preset.caller_label,
        "caller_avatar_url": preset.caller_avatar_url,
        "ringtone_style": preset.ringtone_style,
        "auto_answer_seconds": preset.auto_answer_seconds,
        "is_default": preset.is_default,
    }


async def delete_preset(session: AsyncSession, user_id: uuid.UUID, preset_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(FakeCallPreset).where(FakeCallPreset.id == preset_id, FakeCallPreset.user_id == user_id, FakeCallPreset.is_default.is_(False))
    )
    return result.rowcount > 0


async def trigger_fake_call(
    session: AsyncSession,
    user_id: uuid.UUID,
    preset_id: Optional[uuid.UUID],
    caller_name: str,
    delay_seconds: int = 0,
    trigger_method: str = "manual",
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> dict:
    """Trigger a fake call: log it + broadcast SSE to the user's device."""
    log = FakeCallLog(
        user_id=user_id,
        preset_id=preset_id,
        caller_name=caller_name,
        trigger_method=trigger_method,
        delay_seconds=delay_seconds,
        status="triggered",
        lat=lat,
        lng=lng,
    )
    session.add(log)
    await session.flush()

    call_data = {
        "call_id": str(log.id),
        "caller_name": caller_name,
        "delay_seconds": delay_seconds,
        "trigger_method": trigger_method,
        "triggered_at": log.triggered_at.isoformat(),
    }

    # Broadcast to user's device via SSE
    await broadcaster.broadcast_to_user(str(user_id), "fake_call_incoming", call_data)
    logger.info(f"Fake call triggered for user {user_id}: {caller_name} (delay={delay_seconds}s)")

    from app.services.monitoring_service import record_fake_call
    record_fake_call()

    return call_data


async def complete_fake_call(
    session: AsyncSession,
    user_id: uuid.UUID,
    call_id: uuid.UUID,
    answered: bool,
    duration_seconds: int = 0,
    send_alert: bool = False,
) -> Optional[dict]:
    result = await session.execute(
        select(FakeCallLog).where(FakeCallLog.id == call_id, FakeCallLog.user_id == user_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        return None

    log.status = "completed"
    log.answered = answered
    log.duration_seconds = duration_seconds
    log.ended_at = datetime.now(timezone.utc)
    log.alert_sent = send_alert
    await session.flush()

    if send_alert:
        await broadcaster.broadcast_to_user(str(user_id), "escape_alert", {
            "call_id": str(call_id),
            "type": "fake_call_escape",
            "message": f"Escape call used ({log.caller_name}). Check in with your family member.",
            "lat": log.lat,
            "lng": log.lng,
            "timestamp": log.ended_at.isoformat(),
        })
        logger.info(f"Escape alert sent for user {user_id} after fake call {call_id}")

    return {
        "call_id": str(log.id),
        "status": "completed",
        "answered": answered,
        "duration_seconds": duration_seconds,
        "alert_sent": send_alert,
    }


async def get_call_history(session: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> list[dict]:
    result = await session.execute(
        select(FakeCallLog)
        .where(FakeCallLog.user_id == user_id)
        .order_by(FakeCallLog.triggered_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(entry.id),
            "caller_name": entry.caller_name,
            "trigger_method": entry.trigger_method,
            "delay_seconds": entry.delay_seconds,
            "status": entry.status,
            "answered": entry.answered,
            "duration_seconds": entry.duration_seconds,
            "alert_sent": entry.alert_sent,
            "triggered_at": entry.triggered_at.isoformat(),
            "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
        }
        for entry in logs
    ]
