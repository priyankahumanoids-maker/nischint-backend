"""
SMS Service — Twilio SMS delivery for safety alerts and guardian notifications.
Gracefully degrades if Twilio credentials are not configured.
"""
import os
import logging

logger = logging.getLogger(__name__)

SMS_PROVIDER = "stub"
_twilio_client = None
_twilio_from = None


def _init_twilio():
    """Initialize the Twilio client from environment variables."""
    global SMS_PROVIDER, _twilio_client, _twilio_from

    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    except Exception:
        pass

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_PHONE_NUMBER") or os.environ.get("TWILIO_FROM_NUMBER")

    if not all([sid, token, from_number]):
        logger.info("Twilio credentials not configured — SMS disabled")
        return

    try:
        from twilio.rest import Client
        _twilio_client = Client(sid, token)
        _twilio_from = from_number
        SMS_PROVIDER = "twilio"
        logger.info(f"Twilio SMS initialized — from {from_number}")
        # NISCH-008: validate auth handshake at boot. Doesn't crash on
        # failure (we want the app to start either way), just logs LIVE
        # vs UNAUTHORIZED so the operator instantly sees the state in
        # `/var/log/supervisor/backend.err.log`.
        try:
            acc = _twilio_client.api.accounts(sid).fetch()
            logger.warning(
                f"[TWILIO_AUTH_OK] LIVE — account={acc.friendly_name} "
                f"status={acc.status} type={acc.type}"
            )
        except Exception as auth_err:
            logger.error(
                f"[TWILIO_AUTH_FAIL] credentials present but auth failed: "
                f"{type(auth_err).__name__}: {auth_err}. "
                f"SMS/voice will silently no-op until creds are fixed."
            )
            try:
                from app.services.health_alerter import notify_failure
                notify_failure(
                    level="critical",
                    kind="twilio_auth",
                    message="Twilio credentials are configured but auth handshake FAILED at boot. SMS/voice will not deliver.",
                    details={
                        "error":  f"{type(auth_err).__name__}: {auth_err}",
                        "from":   from_number,
                        "sid_prefix": (sid or "")[:8] + "...",
                    },
                )
            except Exception:
                pass  # never let the alerter break boot
    except ImportError:
        logger.info("twilio package not installed — SMS disabled")
    except Exception as e:
        logger.warning(f"Twilio init failed: {e}")


# Initialize on module load
_init_twilio()


def send_sms(to: str, body: str) -> bool:
    """
    Send an SMS message via Twilio.
    Phone number must be in E.164 format (e.g., +14155552671).
    Returns True on success.

    NISCH-008 hardening: routed through `twilio_safe.safe_call` so we
    get a 5s hard timeout, one retry on transient failure, and a
    structured `[TWILIO_OK]` / `[TWILIO_FAIL]` log line per attempt.
    Latency is recorded into `ttfa_recorder` under kind `twilio:sms`.
    """
    if SMS_PROVIDER != "twilio" or not _twilio_client:
        logger.info(f"SMS (stub): To={to}, Body={body[:80]}...")
        return False

    from app.services.twilio_safe import safe_call
    out = safe_call(
        _twilio_client.messages.create,
        kind="sms",
        kwargs={"body": body, "from_": _twilio_from, "to": to},
    )
    if out["success"]:
        msg = out["result"]
        logger.info(
            f"[SMS_SENT] to={to} sid={msg.sid} status={msg.status} "
            f"latency_ms={out['latency_ms']} attempts={out['attempts']}"
        )
        return msg.status in ("queued", "sent", "delivered")
    logger.error(
        f"[SMS_FAILED] to={to} err={out['error']} "
        f"latency_ms={out['latency_ms']} attempts={out['attempts']}"
    )
    return False


def send_sos_sms(to: str, user_name: str, location: dict = None) -> bool:
    """Send SOS emergency SMS to a guardian."""
    from app.services.notification_formatter import sms_sos
    return send_sms(to, sms_sos(user_name, location))


def send_fall_sms(to: str, user_name: str, location: dict = None) -> bool:
    """Send fall detection SMS to a guardian."""
    from app.services.notification_formatter import sms_fall
    return send_sms(to, sms_fall(user_name, location))


def send_zone_breach_sms(to: str, user_name: str, zone_name: str = "safe zone", location: dict = None) -> bool:
    """Send safe zone breach SMS to a guardian."""
    from app.services.notification_formatter import sms_zone_breach
    return send_sms(to, sms_zone_breach(user_name, zone_name, location))


def send_journey_started_sms(to: str, user_name: str, destination: str = "") -> bool:
    """Send journey started SMS to a guardian."""
    from app.services.notification_formatter import sms_journey_started
    return send_sms(to, sms_journey_started(user_name, destination))


def send_arrived_safely_sms(to: str, user_name: str, destination: str = "") -> bool:
    """Send arrived safely SMS to a guardian."""
    from app.services.notification_formatter import sms_arrived_safely
    return send_sms(to, sms_arrived_safely(user_name, destination))


def send_incident_sms(to: str, user_name: str, incident_type: str, severity: str) -> bool:
    """Send incident notification SMS."""
    from app.services.notification_formatter import sms_sos, sms_fall
    if incident_type == "fall_detected":
        return send_sms(to, sms_fall(user_name))
    if incident_type == "sos":
        return send_sms(to, sms_sos(user_name))
    from app.services.notification_formatter import _now_str
    emoji = "\U0001F534" if severity in ("critical", "high") else "\U0001F7E1"
    label = incident_type.replace('_', ' ').title()
    body = f"{emoji} NISCHINT {label.upper()}\n{user_name} \u2014 {label}\n{_now_str()} \u00b7 {severity.upper()}\nhttps://nischint.care/m/alerts \u2192"
    return send_sms(to, body)


def send_escalation_sms(to: str, user_name: str, level: int, incident_type: str) -> bool:
    """Send escalation notification SMS."""
    from app.services.notification_formatter import sms_escalation
    return send_sms(to, sms_escalation(user_name, level, incident_type))


def is_available() -> bool:
    """Check if SMS sending is available."""
    return SMS_PROVIDER == "twilio" and _twilio_client is not None


def send_failsafe_sms(
    to: str,
    child_name: str,
    alert_type: str,
    last_seen: str = "unknown",
    contact_name: str = "",
) -> bool:
    """Send Tier 2 failsafe SMS to an emergency contact.
    Includes: child name, alert type, last seen time, callback link.
    """
    alert_label = alert_type.replace("_", " ").upper()
    greeting = f"Hi {contact_name}, " if contact_name else ""
    body = (
        f"\U0001F6A8 NISCHINT SAFETY ALERT\n"
        f"{greeting}{child_name} may need help.\n"
        f"Alert: {alert_label}\n"
        f"Last seen: {last_seen}\n"
        f"No guardian has responded in 60s.\n"
        f"View live status: https://nischint.care/m/alerts\n"
        f"If you can help, please call {child_name} or reply to this message."
    )
    return send_sms(to, body)


# ── VOICE CALLING (TWILIO) ──
# Sequential calls for CRITICAL alerts only
# Uses TwiML <Say> to speak the alert message
# Retry: 3 attempts per contact, SMS fallback on exhaustion

import time

VOICE_MAX_RETRIES = 3
VOICE_RETRY_BACKOFF_S = 5  # seconds between retries

# In-memory dedup: {event_id: set(phone)}
_voice_calls_sent: dict[str, set[str]] = {}


def _build_twiml(child_name: str, alert_type: str, contact_name: str = "") -> str:
    """Build the TwiML <Say> XML for a voice call."""
    alert_label = alert_type.replace("_", " ")
    greeting = f"{contact_name}, this" if contact_name else "This"
    return (
        f'<Response>'
        f'<Say voice="alice" language="en-IN">'
        f'{greeting} is an urgent safety alert from Nischint. '
        f'{child_name} may be in danger. Alert type: {alert_label}. '
        f'No guardian has responded. '
        f'Please call {child_name} immediately or contact emergency services. '
        f'Repeating: {child_name} needs help urgently.'
        f'</Say>'
        f'<Pause length="2"/>'
        f'<Say voice="alice" language="en-IN">'
        f'{child_name} needs help. Please act now.'
        f'</Say>'
        f'</Response>'
    )


def make_voice_call(
    to: str,
    child_name: str,
    alert_type: str,
    event_id: str,
    contact_name: str = "",
) -> bool:
    """Single-attempt Twilio voice call. Returns True on success.
    Deduplicates by event_id + phone.
    """
    if SMS_PROVIDER != "twilio" or not _twilio_client:
        logger.info(f"VOICE (stub): To={to}, Child={child_name}, Event={event_id}")
        return False

    # Dedup: don't call same phone for same event
    if event_id in _voice_calls_sent and to in _voice_calls_sent[event_id]:
        logger.info(f"[VOICE_DEDUP] Already called {to} for event={event_id}")
        return False

    twiml = _build_twiml(child_name, alert_type, contact_name)

    from app.services.twilio_safe import safe_call
    out = safe_call(
        _twilio_client.calls.create,
        kind="voice",
        kwargs={"twiml": twiml, "from_": _twilio_from, "to": to, "timeout": 30},
    )
    if not out["success"]:
        logger.error(
            f"[VOICE_CALL_FAILED] to={to} event={event_id} "
            f"err={out['error']} latency_ms={out['latency_ms']} "
            f"attempts={out['attempts']}"
        )
        return False
    call = out["result"]
    # Record for dedup
    if event_id not in _voice_calls_sent:
        _voice_calls_sent[event_id] = set()
    _voice_calls_sent[event_id].add(to)
    # Cap dedup entries
    if len(_voice_calls_sent) > 500:
        oldest = next(iter(_voice_calls_sent))
        del _voice_calls_sent[oldest]

    logger.warning(
        f"[VOICE_CALL_SENT] to={to} name={contact_name} child={child_name} "
        f"event={event_id} call_sid={call.sid} status={call.status} "
        f"latency_ms={out['latency_ms']} attempts={out['attempts']}"
    )
    return call.status in ("queued", "ringing", "in-progress")


def make_voice_call_with_callback(
    to: str,
    child_name: str,
    alert_type: str,
    event_id: str,
    contact_name: str = "",
    callback_url: str = "",
) -> str | None:
    """Make a Twilio voice call with status callback + machine detection.
    Returns call_sid on success, None on failure.
    Used by the sequential escalation engine.
    """
    if SMS_PROVIDER != "twilio" or not _twilio_client:
        logger.info(f"VOICE_CB (stub): To={to}, Child={child_name}, Event={event_id}")
        return None

    twiml = _build_twiml(child_name, alert_type, contact_name)

    call_params = {
        "twiml": twiml,
        "from_": _twilio_from,
        "to": to,
        "timeout": 30,
        "machine_detection": "DetectMessageEnd",
    }
    if callback_url:
        call_params["status_callback"] = callback_url
        call_params["status_callback_event"] = ["initiated", "ringing", "answered", "completed"]
        call_params["status_callback_method"] = "POST"

    try:
        from app.services.twilio_safe import safe_call
        out = safe_call(
            _twilio_client.calls.create,
            kind="voice_cb",
            kwargs=call_params,
        )
        if not out["success"]:
            logger.error(
                f"[VOICE_CB_CALL_FAILED] to={to} event={event_id} "
                f"err={out['error']} latency_ms={out['latency_ms']} "
                f"attempts={out['attempts']}"
            )
            return None
        call = out["result"]
        logger.warning(
            f"[VOICE_CB_CALL_SENT] to={to} name={contact_name} child={child_name} "
            f"event={event_id} call_sid={call.sid} status={call.status} "
            f"callback={'YES' if callback_url else 'NO'} "
            f"latency_ms={out['latency_ms']} attempts={out['attempts']}"
        )
        return call.sid
    except Exception as e:
        logger.error(f"[VOICE_CB_CALL_FAILED] to={to} event={event_id}: {e}")
        return None


def escalation_flow(
    to: str,
    child_name: str,
    alert_type: str,
    event_id: str,
    contact_name: str = "",
    last_seen: str = "unknown",
) -> dict:
    """Hardened escalation: try voice call up to 3 times, fallback to SMS on failure.
    Returns {method: 'voice'|'sms'|'failed', attempts: int, success: bool}.
    """
    # Skip if already handled for this event
    if event_id in _voice_calls_sent and to in _voice_calls_sent[event_id]:
        logger.info(f"[ESCALATION_FLOW_DEDUP] Already escalated {to} for event={event_id}")
        return {"method": "dedup", "attempts": 0, "success": True}

    # Phase 1: Try voice call up to VOICE_MAX_RETRIES times
    attempts = 0
    voice_success = False

    if is_voice_available():
        while attempts < VOICE_MAX_RETRIES:
            attempts += 1
            logger.warning(
                f"[ESCALATION_FLOW] Voice attempt {attempts}/{VOICE_MAX_RETRIES} "
                f"to={to} name={contact_name} event={event_id}"
            )
            try:
                success = make_voice_call(
                    to=to,
                    child_name=child_name,
                    alert_type=alert_type,
                    event_id=event_id,
                    contact_name=contact_name,
                )
                if success:
                    voice_success = True
                    logger.warning(
                        f"[ESCALATION_FLOW_VOICE_OK] to={to} attempt={attempts} event={event_id}"
                    )
                    break
            except Exception as e:
                logger.error(f"[ESCALATION_FLOW_VOICE_ERR] attempt={attempts} to={to}: {e}")

            # Backoff before retry (skip on last attempt)
            if attempts < VOICE_MAX_RETRIES:
                time.sleep(VOICE_RETRY_BACKOFF_S)

    if voice_success:
        return {"method": "voice", "attempts": attempts, "success": True}

    # Phase 2: Voice exhausted — fallback to SMS
    logger.warning(
        f"[ESCALATION_FLOW_VOICE_EXHAUSTED] to={to} attempts={attempts} "
        f"— falling back to SMS for event={event_id}"
    )

    sms_success = False
    if is_available():
        sms_success = send_failsafe_sms(
            to=to,
            child_name=child_name,
            alert_type=alert_type,
            last_seen=last_seen,
            contact_name=contact_name,
        )
        if sms_success:
            logger.warning(f"[ESCALATION_FLOW_SMS_FALLBACK] to={to} event={event_id} — SMS sent")
        else:
            logger.error(f"[ESCALATION_FLOW_SMS_FAILED] to={to} event={event_id}")
    else:
        logger.warning(f"[ESCALATION_FLOW_NO_SMS] Twilio not configured — cannot fallback for {to}")

    # Always record the attempt to prevent infinite retry loops
    if event_id not in _voice_calls_sent:
        _voice_calls_sent[event_id] = set()
    _voice_calls_sent[event_id].add(to)

    return {
        "method": "sms_fallback" if sms_success else "failed",
        "attempts": attempts,
        "success": sms_success,
    }


def cancel_pending_voice_calls(event_id: str):
    """Mark event as resolved — prevents future voice calls for this event."""
    if event_id in _voice_calls_sent:
        logger.info(f"[VOICE_CANCEL] Marking event={event_id} as resolved (no more calls)")
    else:
        _voice_calls_sent[event_id] = {"__cancelled__"}
        logger.info(f"[VOICE_CANCEL] Event={event_id} pre-cancelled")


def is_voice_available() -> bool:
    """Check if voice calling is available."""
    return SMS_PROVIDER == "twilio" and _twilio_client is not None
