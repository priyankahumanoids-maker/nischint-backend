# SOS Silent Mode Service — Business logic for covert emergency triggers
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sos import SOSConfig, SOSLog
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)


async def _get_user_name(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Look up the user's full name for incident display."""
    from app.models.user import User
    result = await session.execute(
        select(User.full_name).where(User.id == user_id)
    )
    name = result.scalar_one_or_none()
    return name or "Unknown User"


DEFAULT_CONFIG = {
    "enabled": True,
    "voice_keywords": ["help me", "sos now", "emergency"],
    "chain_notification": True,
    "chain_notification_delay": 10,
    "chain_call": True,
    "chain_call_delay": 40,
    "chain_call_preset_name": "Boss",
    "chain_notification_title": "Team Meeting in 5 min",
    "chain_notification_message": "Your 3:30 PM standup starts soon. Join the call now.",
    "trusted_contacts": [],
    "auto_share_location": True,
    "silent_mode": True,
}


def _config_to_dict(cfg: SOSConfig) -> dict:
    return {
        "id": str(cfg.id),
        "user_id": str(cfg.user_id),
        "enabled": cfg.enabled,
        "voice_keywords": cfg.voice_keywords,
        "chain_notification": cfg.chain_notification,
        "chain_notification_delay": cfg.chain_notification_delay,
        "chain_call": cfg.chain_call,
        "chain_call_delay": cfg.chain_call_delay,
        "chain_call_preset_name": cfg.chain_call_preset_name,
        "chain_notification_title": cfg.chain_notification_title,
        "chain_notification_message": cfg.chain_notification_message,
        "trusted_contacts": cfg.trusted_contacts,
        "auto_share_location": cfg.auto_share_location,
        "silent_mode": cfg.silent_mode,
        "updated_at": cfg.updated_at.isoformat(),
    }


async def get_or_create_config(session: AsyncSession, user_id: uuid.UUID) -> dict:
    result = await session.execute(
        select(SOSConfig).where(SOSConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = SOSConfig(user_id=user_id, **DEFAULT_CONFIG)
        session.add(cfg)
        await session.flush()
        logger.info(f"Created default SOS config for user {user_id}")
    return _config_to_dict(cfg)


async def update_config(session: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    result = await session.execute(
        select(SOSConfig).where(SOSConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        cfg = SOSConfig(user_id=user_id, **DEFAULT_CONFIG)
        session.add(cfg)
        await session.flush()

    updatable = (
        "enabled", "voice_keywords", "chain_notification", "chain_notification_delay",
        "chain_call", "chain_call_delay", "chain_call_preset_name",
        "chain_notification_title", "chain_notification_message",
        "trusted_contacts", "auto_share_location", "silent_mode",
    )
    for key in updatable:
        if key in data:
            setattr(cfg, key, data[key])
    cfg.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return _config_to_dict(cfg)


async def trigger_sos(
    session: AsyncSession,
    user_id: uuid.UUID,
    trigger_type: str = "manual",
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> dict:
    # Load config
    config_result = await session.execute(
        select(SOSConfig).where(SOSConfig.user_id == user_id)
    )
    cfg = config_result.scalar_one_or_none()

    log = SOSLog(
        user_id=user_id,
        trigger_type=trigger_type,
        status="active",
        lat=lat,
        lng=lng,
    )
    session.add(log)
    await session.flush()

    # Build chain info
    chain_info = {"notification": None, "call": None}
    if cfg:
        if cfg.chain_notification:
            chain_info["notification"] = {
                "delay_seconds": cfg.chain_notification_delay,
                "title": cfg.chain_notification_title,
                "message": cfg.chain_notification_message,
            }
            log.chain_notification_triggered = True
        if cfg.chain_call:
            chain_info["call"] = {
                "delay_seconds": cfg.chain_call_delay,
                "caller_name": cfg.chain_call_preset_name,
            }
            log.chain_call_triggered = True
        if cfg.trusted_contacts:
            log.alert_sent_to = cfg.trusted_contacts
        await session.flush()

    sos_data = {
        "sos_id": str(log.id),
        "user_id": str(user_id),
        "trigger_type": trigger_type,
        "status": "active",
        "lat": lat,
        "lng": lng,
        "chain": chain_info,
        "trusted_contacts_alerted": log.alert_sent_to,
        "triggered_at": log.triggered_at.isoformat(),
    }

    # Broadcast SOS to user's guardians and operators
    await broadcaster.broadcast_to_user(str(user_id), "sos_triggered", sos_data)
    await broadcaster.broadcast_to_operators("sos_triggered", sos_data)
    logger.warning(f"SOS TRIGGERED for user {user_id} via {trigger_type} at ({lat}, {lng})")

    # Publish to incident_stream Redis channel for Command Center
    user_name = await _get_user_name(session, user_id)
    from app.services.redis_service import publish_event
    publish_event("incident_stream", {
        "type": "SOS_ALERT",
        "incident_id": str(log.id),
        "user_id": str(user_id),
        "user_name": user_name,
        "lat": lat,
        "lng": lng,
        "risk_score": 7.6,
        "trigger_type": trigger_type,
        "timestamp": log.triggered_at.isoformat(),
    })

    # Send directly to Command Center WebSocket clients
    try:
        from app.api.ws_command_center import broadcast_to_command_center
        await broadcast_to_command_center({
            "type": "SOS_ALERT",
            "data": {
                "incident_id": str(log.id),
                "user_id": str(user_id),
                "user_name": user_name,
                "lat": lat,
                "lng": lng,
                "risk_score": 7.6,
                "trigger_type": trigger_type,
            },
            "timestamp": log.triggered_at.isoformat(),
        })
    except Exception as e:
        logger.warning(f"Failed to broadcast to CC WebSocket: {e}")

    # Record metric for monitoring
    from app.services.monitoring_service import record_sos_trigger
    record_sos_trigger()

    # Enqueue to incident queue for async processing
    from app.services.queue_service import enqueue_incident
    enqueue_incident({
        "type": "sos",
        "user_id": str(user_id),
        "sos_id": str(log.id),
        "trigger_type": trigger_type,
        "lat": lat,
        "lng": lng,
    }, priority="critical")

    return sos_data


async def cancel_sos(
    session: AsyncSession,
    user_id: uuid.UUID,
    sos_id: uuid.UUID,
    resolved_by: str = "user",
) -> Optional[dict]:
    result = await session.execute(
        select(SOSLog).where(SOSLog.id == sos_id, SOSLog.user_id == user_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        return None

    log.status = "resolved"
    log.resolved_by = resolved_by
    log.resolved_at = datetime.now(timezone.utc)
    await session.flush()

    resolved_data = {
        "sos_id": str(log.id),
        "status": "resolved",
        "resolved_by": resolved_by,
        "resolved_at": log.resolved_at.isoformat(),
    }

    await broadcaster.broadcast_to_user(str(user_id), "sos_resolved", resolved_data)
    await broadcaster.broadcast_to_operators("sos_resolved", resolved_data)
    logger.info(f"SOS resolved for user {user_id}: {sos_id} by {resolved_by}")

    return resolved_data


async def get_history(session: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> list[dict]:
    result = await session.execute(
        select(SOSLog)
        .where(SOSLog.user_id == user_id)
        .order_by(SOSLog.triggered_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(entry.id),
            "trigger_type": entry.trigger_type,
            "status": entry.status,
            "lat": entry.lat,
            "lng": entry.lng,
            "chain_notification_triggered": entry.chain_notification_triggered,
            "chain_call_triggered": entry.chain_call_triggered,
            "alert_sent_to": entry.alert_sent_to,
            "resolved_by": entry.resolved_by,
            "triggered_at": entry.triggered_at.isoformat(),
            "resolved_at": entry.resolved_at.isoformat() if entry.resolved_at else None,
        }
        for entry in result.scalars().all()
    ]
