# Guardian Notification Dispatcher
# Dispatches real FCM push + Twilio SMS to guardians when alerts fire.
# Respects per-guardian notification preferences, implements rate limiting.

import logging
import time
from datetime import datetime, timezone
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import Guardian, GuardianAlert
from app.services.notification_service import _send_twilio_sms
from app.services.push_service import send_push_to_user
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
}


def _is_sms_rate_limited(guardian_id: str, alert_type: str) -> bool:
    key = f"{guardian_id}:{alert_type}"
    last = _sms_rate_limit.get(key, 0)
    return (time.time() - last) < SMS_RATE_LIMIT_S


def _mark_sms_sent(guardian_id: str, alert_type: str):
    key = f"{guardian_id}:{alert_type}"
    _sms_rate_limit[key] = time.time()


def _format_push_title(alert_type: str, severity: str) -> str:
    if alert_type == "emergency":
        return "\U0001F534 NISCHINT ALERT"
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
    if not guardians:
        logger.info(f"No active guardians for user {user_id}")
        return {"dispatched": False, "reason": "no_guardians", "push_sent": 0, "sms_sent": 0}

    push_sent = 0
    sms_sent = 0
    sms_skipped = 0
    errors = []

    for g in guardians:
        prefs = g.notification_pref or {}
        g_id = str(g.id)

        # Push notification — calls FCM via push_service.send_push_to_user.
        # Previously this was a logger.info() stub; now it actually
        # ships. Each guardian's User row owns the push tokens.
        if rules["push"] and prefs.get("push", True):
            try:
                title = _format_push_title(alert.alert_type, alert.severity)
                if louder:
                    title = f"\U0001F6A8 {title} \u2014 ESCALATED"
                body = f"{alert.message}"
                if alert.details:
                    body += f" \u2014 {alert.details}"
                payload_data = {
                    "type": "SAFETY_ALERT",
                    "alert_id": str(alert.id),
                    "session_id": session_id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                }
                # Push to the GUARDIAN's user account, not the child's.
                # `g.guardian_user_id` is set when the guardian themselves
                # has a user record. Falls back to the alert's owning
                # user if the guardian is contact-only (SMS).
                target_user_id = getattr(g, "guardian_user_id", None) or g.user_id
                if target_user_id:
                    sent = await send_push_to_user(
                        session, target_user_id, title, body,
                        data=payload_data,
                        channel_id="safety-alerts",
                        louder=louder,
                    )
                    push_sent += sent
                    logger.info(
                        f"PUSH{' LOUDER' if louder else ''} "
                        f"[{alert.alert_type}] to guardian {g.name}: "
                        f"sent={sent}"
                    )
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
                    success = _send_twilio_sms(g.phone, sms_body)
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

    result = {
        "dispatched": True,
        "guardians_count": len(guardians),
        "push_sent": push_sent,
        "sms_sent": sms_sent,
        "sms_skipped_rate_limit": sms_skipped,
        "errors": errors,
        "alert_type": alert.alert_type,
        "priority": rules["priority"],
    }
    logger.info(f"Guardian alert dispatched: {result}")
    return result
