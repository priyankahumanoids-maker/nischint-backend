# Voice Trigger Service — Recognition, matching, and action triggering
import json
import logging
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice_command import VoiceCommandConfig, VoiceTriggerLog
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

DEFAULT_COMMANDS = [
    {"phrase": "help me", "linked_action": "sos", "action_config": json.dumps({"trigger_type": "voice"}), "confidence_threshold": 0.7, "is_default": True},
    {"phrase": "call me now", "linked_action": "fake_call", "action_config": json.dumps({"caller_name": "Boss", "delay_seconds": 0}), "confidence_threshold": 0.7, "is_default": True},
    {"phrase": "notify me now", "linked_action": "fake_notification", "action_config": json.dumps({"title": "Team Meeting in 5 min", "message": "Your standup starts soon.", "category": "Work"}), "confidence_threshold": 0.7, "is_default": True},
]


def _cmd_to_dict(cmd: VoiceCommandConfig) -> dict:
    config = None
    if cmd.action_config:
        try:
            config = json.loads(cmd.action_config)
        except (json.JSONDecodeError, TypeError):
            config = None
    return {
        "id": str(cmd.id),
        "phrase": cmd.phrase,
        "linked_action": cmd.linked_action,
        "action_config": config,
        "confidence_threshold": cmd.confidence_threshold,
        "enabled": cmd.enabled,
        "is_default": cmd.is_default,
        "created_at": cmd.created_at.isoformat(),
    }


async def ensure_defaults(session: AsyncSession, user_id: uuid.UUID):
    result = await session.execute(
        select(func.count()).select_from(VoiceCommandConfig)
        .where(VoiceCommandConfig.user_id == user_id)
    )
    if result.scalar() > 0:
        return
    for d in DEFAULT_COMMANDS:
        session.add(VoiceCommandConfig(user_id=user_id, **d))
    await session.flush()
    logger.info(f"Seeded {len(DEFAULT_COMMANDS)} default voice commands for user {user_id}")


async def list_commands(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    result = await session.execute(
        select(VoiceCommandConfig)
        .where(VoiceCommandConfig.user_id == user_id)
        .order_by(VoiceCommandConfig.is_default.desc(), VoiceCommandConfig.created_at)
    )
    return [_cmd_to_dict(c) for c in result.scalars().all()]


async def create_command(session: AsyncSession, user_id: uuid.UUID, data: dict) -> dict:
    action_config = data.get("action_config")
    if isinstance(action_config, dict):
        action_config = json.dumps(action_config)
    cmd = VoiceCommandConfig(
        user_id=user_id,
        phrase=data["phrase"].lower().strip(),
        linked_action=data["linked_action"],
        action_config=action_config,
        confidence_threshold=data.get("confidence_threshold", 0.7),
        enabled=True,
        is_default=False,
    )
    session.add(cmd)
    await session.flush()
    return _cmd_to_dict(cmd)


async def delete_command(session: AsyncSession, user_id: uuid.UUID, cmd_id: uuid.UUID) -> bool:
    result = await session.execute(
        delete(VoiceCommandConfig)
        .where(
            VoiceCommandConfig.id == cmd_id,
            VoiceCommandConfig.user_id == user_id,
            VoiceCommandConfig.is_default.is_(False),
        )
    )
    return result.rowcount > 0


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


async def recognize_and_trigger(
    session: AsyncSession,
    user_id: uuid.UUID,
    transcribed_text: str,
) -> dict:
    """Match transcribed text against configured commands and trigger if confident."""
    text_lower = transcribed_text.lower().strip()

    commands = await list_commands(session, user_id)
    enabled_commands = [c for c in commands if c["enabled"]]

    best_match = None
    best_confidence = 0.0

    for cmd in enabled_commands:
        phrase = cmd["phrase"].lower()

        # Exact substring match
        if phrase in text_lower:
            confidence = 0.95
        else:
            confidence = _similarity(text_lower, phrase)
            # Boost if phrase words are all present
            phrase_words = set(phrase.split())
            text_words = set(text_lower.split())
            if phrase_words.issubset(text_words):
                confidence = max(confidence, 0.90)

        if confidence > best_confidence:
            best_confidence = confidence
            best_match = cmd

    triggered = False
    matched_phrase = None
    linked_action = None
    action_result = None

    if best_match and best_confidence >= best_match["confidence_threshold"]:
        triggered = True
        matched_phrase = best_match["phrase"]
        linked_action = best_match["linked_action"]

        # Trigger the linked action
        action_result = {
            "action": linked_action,
            "config": best_match["action_config"],
            "command_id": best_match["id"],
        }

    # Log
    log = VoiceTriggerLog(
        user_id=user_id,
        command_id=uuid.UUID(best_match["id"]) if best_match and triggered else None,
        transcribed_text=transcribed_text,
        matched_phrase=matched_phrase,
        confidence=round(best_confidence, 4),
        linked_action=linked_action,
        triggered=triggered,
        status="triggered" if triggered else "no_match",
    )
    session.add(log)
    await session.flush()

    result = {
        "log_id": str(log.id),
        "transcribed_text": transcribed_text,
        "matched_phrase": matched_phrase,
        "confidence": round(best_confidence, 4),
        "triggered": triggered,
        "linked_action": linked_action,
        "action_result": action_result,
        "timestamp": log.triggered_at.isoformat(),
    }

    if triggered:
        await broadcaster.broadcast_to_user(str(user_id), "voice_trigger_activated", result)
        await broadcaster.broadcast_to_operators("voice_trigger_activated", result)
        logger.info(f"Voice trigger activated for user {user_id}: '{matched_phrase}' → {linked_action} (confidence={best_confidence:.2f})")

    return result


async def get_history(session: AsyncSession, user_id: uuid.UUID, limit: int = 20) -> list[dict]:
    result = await session.execute(
        select(VoiceTriggerLog)
        .where(VoiceTriggerLog.user_id == user_id)
        .order_by(VoiceTriggerLog.triggered_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(entry.id),
            "transcribed_text": entry.transcribed_text,
            "matched_phrase": entry.matched_phrase,
            "confidence": entry.confidence,
            "linked_action": entry.linked_action,
            "triggered": entry.triggered,
            "status": entry.status,
            "triggered_at": entry.triggered_at.isoformat(),
        }
        for entry in result.scalars().all()
    ]
