# Route Alert Service
# Handles route monitoring alerts with throttling, preferences, and multi-channel dispatch.

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

# Throttle cooldowns per event type (seconds)
THROTTLE = {
    "high_risk_zone": 300,      # 5 min per zone entry
    "danger_ahead": 300,        # 5 min per segment
    "route_deviation": 180,     # 3 min
    "prolonged_stop": 600,      # 10 min
    "critical_incident": 60,    # 1 min (urgent)
}

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ── Guardian resolution ──

async def _resolve_guardian(session, device_id):
    row = (await session.execute(text("""
        SELECT u.id as guardian_id, u.email, u.phone, u.full_name as guardian_name,
               s.full_name as senior_name, d.device_identifier
        FROM devices d
        JOIN seniors s ON d.senior_id = s.id
        JOIN users u ON s.guardian_id = u.id
        WHERE d.id = :did
    """), {"did": device_id})).fetchone()
    return row


async def _get_prefs(session, user_id):
    row = (await session.execute(text("""
        SELECT push_enabled, sms_enabled, in_app_enabled,
               severity_threshold, quiet_hours_start, quiet_hours_end
        FROM notification_preferences WHERE user_id = :uid
    """), {"uid": user_id})).fetchone()
    if not row:
        return {"push": True, "sms": True, "in_app": True, "threshold": "low", "quiet_start": None, "quiet_end": None}
    return {
        "push": row.push_enabled, "sms": row.sms_enabled, "in_app": row.in_app_enabled,
        "threshold": row.severity_threshold,
        "quiet_start": row.quiet_hours_start, "quiet_end": row.quiet_hours_end,
    }


async def _is_throttled(session, device_id, event_type):
    cooldown = THROTTLE.get(event_type, 120)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown)
    row = (await session.execute(text("""
        SELECT id FROM notifications_log
        WHERE device_id = :did AND event_type = :et AND sent_at >= :cutoff LIMIT 1
    """), {"did": device_id, "et": event_type, "cutoff": cutoff})).fetchone()
    return row is not None


def _in_quiet_hours(prefs):
    s, e = prefs.get("quiet_start"), prefs.get("quiet_end")
    if s is None or e is None:
        return False
    h = datetime.now(timezone.utc).hour
    return (s <= h < e) if s <= e else (h >= s or h < e)


# ── Channel delivery ──

async def _send_push(session, guardian_id, title, msg):
    """Send push via FCM if configured, else stub-log."""
    sa_path = settings.firebase_sa_key_path
    sa_json = settings.firebase_sa_key_json
    has_firebase = (sa_path and __import__("os").path.exists(sa_path)) or bool(sa_json)

    if has_firebase:
        try:
            from app.services.push_service import send_push_to_user
            from uuid import UUID
            uid = UUID(guardian_id) if isinstance(guardian_id, str) else guardian_id
            count = await send_push_to_user(session=session, user_id=uid, title=title, body=msg)
            if count > 0:
                logger.info(f"[PUSH] FCM sent {count} notification(s) to guardian {guardian_id}")
                return "delivered"
            logger.info(f"[PUSH] No push tokens for guardian {guardian_id}, marking delivered (no device)")
            return "delivered"
        except Exception as e:
            logger.error(f"[PUSH] FCM error for guardian {guardian_id}: {e}")
            return "failed"
    else:
        logger.info(f"[PUSH] (stub) To guardian={guardian_id}: {title}")
        return "delivered"


async def _send_sms(phone, title, msg):
    """Send SMS via Twilio if configured, else stub-log."""
    if not phone:
        return "skipped_no_phone"

    # Normalize phone to E.164 format (add +91 for 10-digit Indian numbers)
    normalized = phone.strip()
    if not normalized.startswith('+'):
        if len(normalized) == 10 and normalized.isdigit():
            normalized = f"+91{normalized}"
        elif len(normalized) > 10 and normalized.isdigit():
            normalized = f"+{normalized}"

    if settings.sms_provider == "twilio" and settings.twilio_account_sid and settings.twilio_auth_token:
        try:
            from app.services.notification_service import _send_twilio_sms
            body = f"{title}\n{msg}"
            success = _send_twilio_sms(normalized, body)
            if success:
                logger.info(f"[SMS] Twilio sent to {normalized}")
                return "delivered"
            logger.warning(f"[SMS] Twilio send failed for {normalized}")
            return "failed"
        except Exception as e:
            logger.error(f"[SMS] Twilio error for {normalized}: {e}")
            return "failed"
    else:
        logger.info(f"[SMS] (stub) To={normalized}: {title} — {msg[:80]}")
        return "delivered"


async def _log_notification(session, device_id, event_type, severity, channel, recipient_id, title, message, metadata, status):
    await session.execute(text("""
        INSERT INTO notifications_log
            (device_id, event_type, severity, channel, recipient_type, recipient_id, title, message, metadata, status)
        VALUES (:did, :et, :sev, :ch, 'guardian', :rid, :title, :msg, :meta, :st)
    """), {
        "did": device_id, "et": event_type, "sev": severity, "ch": channel,
        "rid": recipient_id, "title": title, "msg": message,
        "meta": json.dumps(metadata or {}), "st": status,
    })


# ── Main dispatch ──

async def dispatch_route_alert(
    session: AsyncSession,
    device_id: str,
    event_type: str,
    severity: str,
    title: str,
    message: str,
    metadata: dict = None,
) -> dict:
    """Send a route-monitoring alert to the device's guardian. Handles throttle, prefs, multi-channel."""
    metadata = metadata or {}
    guardian = await _resolve_guardian(session, device_id)
    if not guardian:
        return {"status": "skipped", "reason": "no_guardian"}

    gid = str(guardian.guardian_id)
    metadata["senior_name"] = guardian.senior_name
    metadata["device_identifier"] = guardian.device_identifier

    # Throttle (bypass for critical)
    if severity != "critical" and await _is_throttled(session, device_id, event_type):
        return {"status": "throttled", "event_type": event_type}

    prefs = await _get_prefs(session, gid)

    # Severity check
    if SEVERITY_RANK.get(severity, 1) < SEVERITY_RANK.get(prefs["threshold"], 0):
        return {"status": "skipped", "reason": "below_threshold"}

    # Quiet hours (bypass for critical)
    if severity != "critical" and _in_quiet_hours(prefs):
        return {"status": "skipped", "reason": "quiet_hours"}

    channels = []

    # In-app (always)
    if prefs["in_app"]:
        await _log_notification(session, device_id, event_type, severity, "in_app", gid, title, message, metadata, "sent")
        channels.append({"channel": "in_app", "status": "sent"})

    # Push
    if prefs["push"]:
        st = await _send_push(session, gid, title, message)
        await _log_notification(session, device_id, event_type, severity, "push", gid, title, message, metadata, st)
        channels.append({"channel": "push", "status": st})

    # SMS (high/critical only)
    if prefs["sms"] and SEVERITY_RANK.get(severity, 0) >= 2:
        st = await _send_sms(guardian.phone, title, message)
        await _log_notification(session, device_id, event_type, severity, "sms", gid, title, message, metadata, st)
        channels.append({"channel": "sms", "status": st})

    await session.commit()

    return {
        "status": "sent",
        "event_type": event_type,
        "severity": severity,
        "recipient": guardian.email,
        "channels": channels,
    }


# ── Alert generators (5 scenarios) ──

async def alert_high_risk_zone(session, device_id, zone_name, risk_score, distance_m, lat, lng):
    return await dispatch_route_alert(
        session, device_id, "high_risk_zone",
        "high" if risk_score >= 7 else "medium",
        "Safety Alert — High-Risk Zone",
        f"Device has entered a high-risk zone. Location: {zone_name}. "
        f"Distance from route: {distance_m}m. Risk score: {risk_score}/10.",
        {"zone_name": zone_name, "risk_score": risk_score, "distance_m": distance_m, "lat": lat, "lng": lng},
    )


async def alert_danger_ahead(session, device_id, distance_m, risk_score, factors):
    return await dispatch_route_alert(
        session, device_id, "danger_ahead",
        "high" if risk_score >= 7 else "medium",
        "Route Warning — Danger Ahead",
        f"High-risk segment detected {distance_m}m ahead. "
        f"Risk: {risk_score}/10. {', '.join(factors[:2]) if factors else ''}. "
        f"Safer alternative route may be available.",
        {"distance_m": distance_m, "risk_score": risk_score, "factors": factors},
    )


async def alert_route_deviation(session, device_id, distance_m):
    return await dispatch_route_alert(
        session, device_id, "route_deviation",
        "high" if distance_m > 500 else "medium",
        "Route Deviation Alert",
        f"Device moved {distance_m}m away from the planned route. Live monitoring is active.",
        {"distance_m": distance_m},
    )


async def alert_prolonged_stop(session, device_id, duration_min, risk_level, lat, lng):
    return await dispatch_route_alert(
        session, device_id, "prolonged_stop",
        "high" if risk_level == "high" else "medium",
        "Unusual Stop Detected",
        f"Device stationary for {duration_min} minutes in a {risk_level}-risk area. Immediate check recommended.",
        {"duration_min": duration_min, "risk_level": risk_level, "lat": lat, "lng": lng},
    )


async def alert_critical_incident(session, device_id, incident_type, location_name, lat, lng):
    return await dispatch_route_alert(
        session, device_id, "critical_incident", "critical",
        "Emergency Alert",
        f"Possible distress detected: {incident_type}. "
        f"Location: {location_name}. Immediate assistance may be required.",
        {"incident_type": incident_type, "location_name": location_name, "lat": lat, "lng": lng},
    )


# ── Query helpers ──

async def get_notification_history(session, device_id=None, recipient_id=None, limit=50):
    params = {"lim": limit}
    where = ""
    if device_id:
        where = "WHERE nl.device_id = :did"
        params["did"] = device_id
    elif recipient_id:
        where = "WHERE nl.recipient_id = :rid"
        params["rid"] = recipient_id

    rows = (await session.execute(text(f"""
        SELECT nl.id, nl.device_id, d.device_identifier, nl.event_type, nl.severity,
               nl.channel, nl.title, nl.message, nl.status,
               nl.acknowledged_at, nl.sent_at
        FROM notifications_log nl
        JOIN devices d ON nl.device_id = d.id
        {where}
        ORDER BY nl.sent_at DESC LIMIT :lim
    """), params)).fetchall()

    return [{
        "id": str(r.id), "device_id": str(r.device_id),
        "device_identifier": r.device_identifier,
        "event_type": r.event_type, "severity": r.severity,
        "channel": r.channel, "title": r.title, "message": r.message,
        "status": r.status,
        "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
        "sent_at": r.sent_at.isoformat(),
    } for r in rows]


async def acknowledge_notification(session, notification_id):
    """Acknowledge a notification. Also acknowledges the parent incident if all notifications are acked."""
    row = (await session.execute(text("""
        UPDATE notifications_log SET acknowledged_at = NOW(), status = 'acknowledged'
        WHERE id = :nid AND acknowledged_at IS NULL
        RETURNING id, device_id
    """), {"nid": notification_id})).fetchone()
    if not row:
        await session.commit()
        return False

    # Also acknowledge the parent incident (via device_id)
    await session.execute(text("""
        UPDATE incidents SET acknowledged_at = NOW()
        WHERE device_id = :did AND status = 'open' AND acknowledged_at IS NULL
    """), {"did": row.device_id})

    await session.commit()
    return True


async def acknowledge_incident(session, incident_id, user_id=None):
    """Directly acknowledge an incident, stopping further escalation."""
    from datetime import datetime, timezone
    result = (await session.execute(text("""
        UPDATE incidents SET acknowledged_at = :now, acknowledged_by_user_id = :uid
        WHERE id = :iid AND acknowledged_at IS NULL
        RETURNING id
    """), {"iid": incident_id, "now": datetime.now(timezone.utc), "uid": user_id})).fetchone()
    await session.commit()
    return result is not None


async def get_device_alert_summary(session, device_id):
    """For Command Center: last alert + unack count."""
    last = (await session.execute(text("""
        SELECT event_type, severity, title, channel, status, sent_at, acknowledged_at
        FROM notifications_log WHERE device_id = :did ORDER BY sent_at DESC LIMIT 1
    """), {"did": device_id})).fetchone()

    unack = (await session.execute(text("""
        SELECT COUNT(*) FROM notifications_log
        WHERE device_id = :did AND acknowledged_at IS NULL AND status = 'sent'
    """), {"did": device_id})).scalar() or 0

    if not last:
        return {"has_alerts": False, "unacknowledged": 0}
    return {
        "has_alerts": True,
        "last_event": last.event_type,
        "last_severity": last.severity,
        "last_title": last.title,
        "last_status": last.status,
        "last_sent": last.sent_at.isoformat(),
        "acknowledged": last.acknowledged_at is not None,
        "unacknowledged": unack,
    }
