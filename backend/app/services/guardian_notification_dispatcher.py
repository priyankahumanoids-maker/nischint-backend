# Guardian Notification Dispatcher
# Dispatches real FCM push + Twilio SMS to guardians when alerts fire.
# Respects per-guardian notification preferences, implements rate limiting.

import asyncio
import logging
import time
from datetime import datetime, timezone
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import Guardian, GuardianAlert
from app.models.user import User
from app.services.notification_service import _send_twilio_sms
from app.services.push_service import get_user_push_tokens, send_push_to_tokens
from app.core.config import settings

logger = logging.getLogger(__name__)

# Rate limit: max 1 SMS per (guardian_id, alert_type) within 5 min
_sms_rate_limit: dict[str, float] = {}  # key: "guardian_id:alert_type" -> last_sent timestamp
SMS_RATE_LIMIT_S = 300  # 5 minutes

# Alert dispatch rules: which channels per alert type
DISPATCH_RULES = {
    "zone_risk":     {"push": True,  "sms": True,  "priority": "HIGH"},
    "route_deviation": {"push": True, "sms": False, "priority": "MEDIUM"},
    "idle":          {"push": True,  "sms": False, "priority": "MEDIUM"},
    "emergency":     {"push": True,  "sms": True,  "priority": "CRITICAL"},
    "arrived":       {"push": True,  "sms": False, "priority": "INFO"},
    "safety_confirmed": {"push": False, "sms": False, "priority": "INFO"},
    "sos":            {"push": True,  "sms": True,  "priority": "CRITICAL"},
    "fall_detected":  {"push": True,  "sms": True,  "priority": "CRITICAL"},
    "help_requested": {"push": True,  "sms": True,  "priority": "CRITICAL"},
    "geofence_breach": {"push": True, "sms": False, "priority": "HIGH"},
    "geofence_recovery": {"push": True, "sms": False, "priority": "INFO"},
    "environmental_hazard": {"push": True, "sms": False, "priority": "HIGH"},
    "low_battery": {"push": True, "sms": False, "priority": "MEDIUM"},
    "wearable_impact": {"push": True, "sms": False, "priority": "HIGH"},
    "wearable_tamper": {"push": True, "sms": False, "priority": "HIGH"},
    "health_anomaly": {"push": True, "sms": False, "priority": "HIGH"},
}


def _is_sms_rate_limited(guardian_id: str, alert_type: str) -> bool:
    key = f"{guardian_id}:{alert_type}"
    last = _sms_rate_limit.get(key, 0)
    return (time.time() - last) < SMS_RATE_LIMIT_S


def _mark_sms_sent(guardian_id: str, alert_type: str):
    key = f"{guardian_id}:{alert_type}"
    _sms_rate_limit[key] = time.time()


def _format_push_title(alert_type: str, severity: str) -> str:
    if alert_type in ("emergency", "sos"):
        return "\U0001F534 NISCHINT ALERT"
    if alert_type == "fall_detected":
        return "\U0001F534 NISCHINT POSSIBLE FALL"
    if alert_type == "help_requested":
        return "\U0001F534 NISCHINT HELP REQUEST"
    if alert_type == "geofence_breach":
        return "\U0001F7E1 NISCHINT SAFETY ZONE"
    if alert_type == "geofence_recovery":
        return "\U0001F7E2 NISCHINT BACK IN SAFE AREA"
    if alert_type == "environmental_hazard":
        return "\U0001F7E0 NISCHINT AREA WARNING"
    if alert_type == "low_battery":
        return "\U0001F7E1 NISCHINT LOW BATTERY"
    if alert_type in ("wearable_impact", "wearable_tamper", "health_anomaly"):
        return "\U0001F7E1 NISCHINT DEVICE ALERT"
    if alert_type == "zone_risk":
        return "\U0001F7E1 NISCHINT ALERT"
    if alert_type == "idle":
        return "\U0001F7E1 NISCHINT ALERT"
    if alert_type == "arrived":
        return "\U0001F7E2 NISCHINT SAFE"
    if alert_type == "route_deviation":
        return "\U0001F7E1 NISCHINT ALERT"
    return "\U0001F534 NISCHINT ALERT"


def _format_sms_body(alert: GuardianAlert, user_name: str = "User", session_id: str = "") -> str:
    now = datetime.now(timezone.utc).strftime("%I:%M %p")
    loc_str = ""
    if alert.location:
        loc_str = f"{alert.location.get('lat', '?')},{alert.location.get('lng', '?')}"

    if alert.alert_type == "emergency":
        return (
            f"\U0001F534 NISCHINT ALERT\n"
            f"{user_name} triggered SOS. {loc_str} \u00b7 {now}\n"
            f"Open guardian map \u2192 https://nischint.care/family"
        )

    return (
        f"\U0001F7E1 NISCHINT ALERT\n"
        f"{user_name} \u2014 {alert.message}. {loc_str} \u00b7 {now}\n"
        f"Open guardian map \u2192 https://nischint.care/family"
    )


async def dispatch_guardian_alert(
    session: AsyncSession,
    alert: GuardianAlert,
    user_id: str,
    session_id: str,
    *,
    louder: bool = False,
    guardian_user_ids: list[str] | None = None,
) -> dict:
    """Dispatch a guardian alert to all guardians via their preferred channels.

    `louder=True` switches push payloads to the critical-channel
    profile (siren_loop sound, vibrate loop, sticky, DND-bypass when
    granted). Used by the escalation engine on the `louder_push` step.
    """
    rules = DISPATCH_RULES.get(alert.alert_type, {"push": True, "sms": False, "priority": "MEDIUM"})

    # Skip dispatch for low-priority info alerts
    if not rules["push"] and not rules["sms"]:
        return {"dispatched": False, "reason": "no_dispatch_needed"}

    # Fetch all active guardians for this user
    import uuid
    result = await session.execute(
        select(Guardian).where(
            Guardian.user_id == uuid.UUID(user_id),
            Guardian.is_active == True,  # noqa: E712
        )
    )
    guardians = result.scalars().all()
    resolved_guardian_user_ids = {
        uuid.UUID(str(guardian_id))
        for guardian_id in (guardian_user_ids or [])
    }

    if not guardians and not resolved_guardian_user_ids:
        logger.info(f"No active guardians for user {user_id}")
        return {"dispatched": False, "reason": "no_guardians", "push_sent": 0, "sms_sent": 0}

    push_sent = 0
    sms_sent = 0
    sms_skipped = 0
    errors = []
    sent_push_user_ids: set[uuid.UUID] = set()
    title = _format_push_title(alert.alert_type, alert.severity)
    if louder:
        title = f"\U0001F6A8 {title} \u2014 ESCALATED"
    body = f"{alert.message}"
    if alert.details:
        body += f" \u2014 {alert.details}"
    child_result = await session.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    child = child_result.scalar_one_or_none()
    child_name = (
        (child.full_name or child.email)
        if child
        else "Protected member"
    )
    payload_data = {
        "type": "SAFETY_ALERT",
        "alert_id": str(alert.id),
        "session_id": session_id,
        "event_type": alert.alert_type,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "child_id": user_id,
        "child_name": child_name,
        "user_name": child_name,
        "message": alert.message,
        "screen": "alerts",
    }
    if alert.location:
        if alert.location.get("lat") is not None:
            payload_data["lat"] = alert.location["lat"]
        if alert.location.get("lng") is not None:
            payload_data["lng"] = alert.location["lng"]

    push_target_ids: set[uuid.UUID] = set(resolved_guardian_user_ids)

    for g in guardians:
        prefs = g.notification_pref or {}
        g_id = str(g.id)

        # Push notification — calls FCM via push_service.send_push_to_user.
        # Previously this was a logger.info() stub; now it actually
        # ships. Each guardian's User row owns the push tokens.
        if rules["push"] and prefs.get("push", True):
            try:
                # Resolve target guardian account user ID
                target_user_id = None
                if g.email:
                    gu_result = await session.execute(
                        select(User.id).where(User.email == g.email)
                    )
                    target_user_id = gu_result.scalar_one_or_none()

                # Fallback: check if child has a primary guardian_id set in User table
                if not target_user_id:
                    child_res = await session.execute(
                        select(User.guardian_id).where(User.id == uuid.UUID(user_id))
                    )
                    target_user_id = child_res.scalar_one_or_none()

                if target_user_id:
                    push_target_ids.add(target_user_id)
            except Exception as e:
                logger.error(f"Push error for guardian {g.name}: {e}")
                errors.append(f"push:{g.name}:{e}")

        # SMS notification
        if rules["sms"] and prefs.get("sms", True) and g.phone:
            if _is_sms_rate_limited(g_id, alert.alert_type):
                logger.info(f"SMS rate-limited for guardian {g.name} ({alert.alert_type})")
                sms_skipped += 1
                continue

            try:
                sms_body = _format_sms_body(alert, session_id=session_id)
                if settings.sms_provider == "twilio" and settings.twilio_account_sid:
                    # The Twilio SDK is synchronous. Running it on the event
                    # loop delayed FCM/SSE delivery for every other guardian.
                    success = await asyncio.to_thread(
                        _send_twilio_sms,
                        g.phone,
                        sms_body,
                    )
                    if success:
                        sms_sent += 1
                        _mark_sms_sent(g_id, alert.alert_type)
                        logger.info(f"SMS sent to guardian {g.name} ({g.phone})")
                    else:
                        errors.append(f"sms:{g.name}:send_failed")
                else:
                    logger.info(f"SMS (stub) to {g.name} ({g.phone}): {sms_body[:100]}...")
                    sms_sent += 1
                    _mark_sms_sent(g_id, alert.alert_type)
            except Exception as e:
                logger.error(f"SMS error for guardian {g.name}: {e}")
                errors.append(f"sms:{g.name}:{e}")

    # Invite-code relationships resolve directly to guardian User IDs and may
    # not have a legacy Guardian row. Dispatch to those accounts as well so
    # closed-app FCM delivery works for QR/code-linked families.
    if rules["push"] and push_target_ids:
        try:
            # Resolve tokens with the request session, then make one concurrent
            # FCM fan-out. A stale/offline guardian device can no longer hold
            # up delivery to the other family devices.
            token_lists = []
            for target_user_id in push_target_ids:
                token_lists.append(
                    await get_user_push_tokens(session, target_user_id)
                )
            all_tokens = [token for tokens in token_lists for token in tokens]
            push_sent = await send_push_to_tokens(
                all_tokens,
                title,
                body,
                data=payload_data,
                channel_id="safety-alerts",
                louder=louder,
            )
            sent_push_user_ids.update(push_target_ids)
            logger.info(
                f"PUSH{' LOUDER' if louder else ''} "
                f"[{alert.alert_type}] fanout users={len(push_target_ids)} "
                f"tokens={len(all_tokens)} sent={push_sent}"
            )
        except Exception as e:
            logger.error(f"Push fanout error: {e}")
            errors.append(f"push:fanout:{e}")

    result = {
        "dispatched": True,
        "guardians_count": max(
            len(guardians),
            len(set(resolved_guardian_user_ids) | sent_push_user_ids),
        ),
        "push_sent": push_sent,
        "sms_sent": sms_sent,
        "sms_skipped_rate_limit": sms_skipped,
        "errors": errors,
        "alert_type": alert.alert_type,
        "priority": rules["priority"],
    }
    logger.info(f"Guardian alert dispatched: {result}")
    return result
