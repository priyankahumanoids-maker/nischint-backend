"""
Notification Service — Centralized push notification dispatch.
Handles FCM push, in-app alerts, and notification history.
"""
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Singleton Firebase init flag
_firebase_initialized = False


class NotificationService:
    """Centralized notification dispatcher for Nischint Safety Platform."""

    def __init__(self, db_session_factory):
        self.db = db_session_factory
        self.fcm_available = False
        self._init_fcm()

    def _init_fcm(self):
        """Initialize Firebase Admin SDK if credentials are available."""
        global _firebase_initialized
        try:
            import firebase_admin
            from firebase_admin import credentials

            # Ensure .env is loaded
            try:
                from dotenv import load_dotenv
                from pathlib import Path
                load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
            except Exception:
                pass

            # Check both env var names for backwards compat
            cred_path = os.environ.get("FIREBASE_SA_KEY_PATH") or os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")
            cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
            elif cred_json:
                cred = credentials.Certificate(json.loads(cred_json))
            else:
                logger.info("FCM credentials not configured — push notifications disabled")
                return

            if not firebase_admin._apps and not _firebase_initialized:
                firebase_admin.initialize_app(cred)
                _firebase_initialized = True

            self.fcm_available = True
            logger.info("FCM initialized successfully — push notifications ACTIVE")
        except ImportError:
            logger.info("firebase-admin not installed — push notifications disabled")
        except Exception as e:
            logger.warning(f"FCM init failed: {e}")

    async def get_device_tokens(self, user_id: str) -> list:
        """Get all registered device tokens for a user."""
        from sqlalchemy import text
        async with self.db() as session:
            result = await session.execute(
                text("SELECT device_token, device_type FROM device_tokens WHERE user_id = :uid AND is_active = true"),
                {"uid": user_id}
            )
            return [{"token": r[0], "type": r[1]} for r in result.fetchall()]

    async def send_push(self, user_id: str, title: str, body: str,
                        data: Optional[dict] = None, tag: str = "nischint-alert",
                        url: str = "/m/home"):
        """Send push notification to all user devices via FCM."""
        tokens = await self.get_device_tokens(user_id)
        if not tokens:
            logger.debug(f"No device tokens for user {user_id}")
            return {"sent": 0, "reason": "no_tokens"}

        # Store notification in DB
        await self._store_notification(user_id, title, body, data, tag)

        if not self.fcm_available:
            logger.info(f"FCM unavailable — notification stored but not pushed: {title}")
            return {"sent": 0, "stored": True, "reason": "fcm_unavailable"}

        # Ensure all data values are strings (FCM requirement)
        fcm_data = {"tag": tag, "url": url}
        for k, v in (data or {}).items():
            fcm_data[k] = str(v)

        # Build absolute URL for webpush link — always use production URL
        base_url = "https://nischint.care"

        sent = 0
        failed_tokens = []
        try:
            from firebase_admin import messaging

            for device in tokens:
                try:
                    webpush_config = messaging.WebpushConfig(
                        notification=messaging.WebpushNotification(
                            title=title,
                            body=body,
                            icon="/icons/icon-192.png",
                            badge="/icons/icon-192.png",
                            tag=tag,
                            require_interaction=tag == "nischint-sos",
                        ),
                    )
                    # Only set fcm_options.link if we have a valid HTTPS base URL
                    if base_url and base_url.startswith("https://"):
                        webpush_config = messaging.WebpushConfig(
                            notification=messaging.WebpushNotification(
                                title=title,
                                body=body,
                                icon="/icons/icon-192.png",
                                badge="/icons/icon-192.png",
                                tag=tag,
                                require_interaction=tag == "nischint-sos",
                            ),
                            fcm_options=messaging.WebpushFCMOptions(
                                link=f"{base_url}{url}",
                            ),
                        )

                    message = messaging.Message(
                        notification=messaging.Notification(title=title, body=body),
                        data=fcm_data,
                        token=device["token"],
                        webpush=webpush_config,
                        android=messaging.AndroidConfig(
                            priority="high",
                            notification=messaging.AndroidNotification(
                                sound="default",
                                click_action="https://nischint.care/family",
                            ),
                        ),
                        apns=messaging.APNSConfig(
                            payload=messaging.APNSPayload(
                                aps=messaging.Aps(sound="default", badge=1),
                            ),
                        ),
                    )
                    messaging.send(message)
                    sent += 1
                    logger.info(f"FCM push sent to {user_id}: {title}")
                except Exception as e:
                    err_str = str(e)
                    if "not found" in err_str.lower() or "not a valid" in err_str.lower() or "invalid-registration" in err_str.lower():
                        failed_tokens.append(device["token"])
                        logger.debug(f"Invalid FCM token for {user_id}, deactivating")
                    else:
                        logger.warning(f"FCM send error for {user_id}: {e}")

        except Exception as e:
            logger.error(f"FCM messaging error: {e}")

        # Deactivate invalid tokens
        if failed_tokens:
            await self._deactivate_tokens(failed_tokens)

        return {"sent": sent, "failed": len(failed_tokens)}

    async def send_sos_notification(self, user_id: str, user_name: str,
                                     location: Optional[dict] = None,
                                     guardian_ids: list = None):
        """Send SOS alert to all guardians."""
        from app.services.notification_formatter import push_sos
        title, body = push_sos(user_name, location)

        for gid in (guardian_ids or []):
            await self.send_push(
                user_id=gid,
                title=title,
                body=body,
                data={"type": "sos", "source_user": user_id},
                tag="nischint-sos",
                url="/m/alerts",
            )

    async def send_risk_alert(self, user_id: str, user_name: str,
                               risk_level: str, guardian_ids: list = None):
        """Send risk level spike alert to guardians."""
        from app.services.notification_formatter import _now_str
        emoji = "\U0001F534" if risk_level in ("critical", "high") else "\U0001F7E1"
        t = _now_str()
        for gid in (guardian_ids or []):
            await self.send_push(
                user_id=gid,
                title=f"{emoji} NISCHINT RISK {risk_level.upper()}",
                body=f"{user_name} \u2014 risk elevated to {risk_level.upper()}\n{t}",
                data={"type": "risk_alert", "risk_level": risk_level},
                tag="nischint-risk",
                url="/m/alerts",
            )

    async def send_guardian_alert(self, guardian_id: str, alert_type: str,
                                   message: str):
        """Send generic guardian notification."""
        await self.send_push(
            user_id=guardian_id,
            title=f"Nischint: {alert_type.replace('_', ' ').title()}",
            body=message,
            data={"type": "guardian_alert", "alert_type": alert_type},
            tag="nischint-guardian",
        )

    async def send_session_alert(self, user_id: str, session_event: str,
                                  details: str = "", guardian_ids: list = None,
                                  user_name: str = "", destination: str = ""):
        """Send session-related notification (start, end, deviation)."""
        from app.services.notification_formatter import push_journey_started, push_arrived_safely, _now_str
        name = user_name or "User"

        if session_event == "started":
            title, body = push_journey_started(name, destination)
            url = "/m/live"
        elif session_event == "ended":
            title, body = push_arrived_safely(name, destination)
            url = "/m/home"
        elif session_event == "deviation":
            t = _now_str()
            title = "\U0001F7E1 NISCHINT ROUTE DEVIATION"
            body = f"{name} \u2014 deviated from planned route\n{t}"
            url = "/m/live"
        else:
            t = _now_str()
            title = "\U0001F535 NISCHINT SESSION"
            body = details or f"{name} \u2014 session {session_event}\n{t}"
            url = "/m/live"

        for gid in (guardian_ids or []):
            await self.send_push(
                user_id=gid,
                title=title,
                body=body,
                data={"type": "session", "event": session_event},
                tag="nischint-session",
                url=url,
            )

    async def send_incident_alert(self, incident_type: str, user_name: str,
                                   location: Optional[dict] = None,
                                   guardian_ids: list = None):
        """Send incident notification (push + stored) to guardians."""
        from app.services.notification_formatter import push_fall, push_zone_breach, push_sos, _now_str

        if incident_type == "fall_detected":
            title, body = push_fall(user_name, location)
        elif incident_type in ("zone_breach", "safe_zone_exit"):
            title, body = push_zone_breach(user_name, location=location)
        elif incident_type == "sos":
            title, body = push_sos(user_name, location)
        else:
            t = _now_str()
            loc = ""
            if location and location.get("lat"):
                loc = f"\n{location['lat']:.4f}, {location['lng']:.4f} \u00b7 "
            label = incident_type.replace('_', ' ').title()
            title = f"\U0001F7E1 NISCHINT {label.upper()}"
            body = f"{user_name} \u2014 {label}{loc}{t}"

        for gid in (guardian_ids or []):
            await self.send_push(
                user_id=gid,
                title=title,
                body=body,
                data={"type": "incident", "incident_type": incident_type},
                tag="nischint-incident",
                url="/m/alerts",
            )

    async def send_invite_notification(self, guardian_id: str, inviter_name: str):
        """Push notification when someone invites you as guardian."""
        await self.send_push(
            user_id=guardian_id,
            title="Guardian Invite Received",
            body=f"{inviter_name} added you as a guardian on Nischint. Tap to accept.",
            data={"type": "guardian_invite"},
            tag="nischint-invite",
            url="/m/guardians",
        )

    async def _store_notification(self, user_id: str, title: str, body: str,
                                   data: Optional[dict], tag: str):
        """Store notification in database for history.

        Compensating action for schema-drift / transient DB outages:
        narrowed `except` over `ProgrammingError` (table missing) and
        `OperationalError` (connection / timeout) only — other
        exceptions propagate so they surface in CI / alerting. On
        catch, the inbox row is pushed to a bounded Redis DLQ
        (`nischint:dlq:notification_history`) so an out-of-band
        reconciler can replay it once the schema is migrated. The
        canonical delivery channel (FCM push) is unaffected — only
        the in-app inbox row is affected here."""
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, ProgrammingError
        try:
            async with self.db() as session:
                await session.execute(
                    text("""
                        INSERT INTO push_notifications (user_id, title, body, data, tag, created_at, is_read)
                        VALUES (:uid, :title, :body, :data, :tag, :created_at, false)
                    """),
                    {
                        "uid": user_id,
                        "title": title,
                        "body": body,
                        "data": json.dumps(data or {}),
                        "tag": tag,
                        "created_at": datetime.now(timezone.utc),
                    }
                )
                await session.commit()
        except (ProgrammingError, OperationalError) as e:
            _push_history_dlq(
                {
                    "user_id":    user_id,
                    "title":      title,
                    "body":       body,
                    "data":       data or {},
                    "tag":        tag,
                    "failed_at":  datetime.now(timezone.utc).isoformat(),
                    "error_type": type(e).__name__,
                    "error":      str(e)[:200],
                }
            )
            logger.warning(
                "notification_history_dlq",
                extra={
                    "event":      "notification_history_dlq",
                    "user_id":    user_id,
                    "tag":        tag,
                    "error_type": type(e).__name__,
                },
            )

    async def _deactivate_tokens(self, tokens: list):
        """Mark invalid device tokens as inactive.

        Compensating action: token cleanup is best-effort housekeeping
        — the next FCM send re-detects invalid tokens and re-attempts
        deactivation organically (self-healing). Narrow the catch to
        `OperationalError` (transient DB connectivity); other errors
        propagate to surface in alerting."""
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError
        try:
            async with self.db() as session:
                for token in tokens:
                    await session.execute(
                        text("UPDATE device_tokens SET is_active = false WHERE device_token = :t"),
                        {"t": token}
                    )
                await session.commit()
        except OperationalError as e:
            logger.warning(
                "token_deactivation_deferred",
                extra={
                    "event":       "token_deactivation_deferred",
                    "token_count": len(tokens),
                    "error_type":  type(e).__name__,
                },
            )


# ── DLQ helper (module-level for testability) ──────────────────────
_HISTORY_DLQ_NAMESPACE = "dlq"
_HISTORY_DLQ_KEY = "notification_history"
_HISTORY_DLQ_MAX = 1000


def _push_history_dlq(payload: dict) -> bool:
    """LPUSH the notification-history payload to a bounded Redis list
    so an out-of-band reconciler can replay it once the schema is
    healthy again. Bounded at `_HISTORY_DLQ_MAX` to protect Redis
    memory during a sustained outage. Returns True on enqueue,
    False if Redis is unavailable (caller already has a structured
    log line; this is best-effort)."""
    try:
        from app.services.redis_service import _get_client
        c = _get_client()
        if not c:
            return False
        full_key = f"{_HISTORY_DLQ_NAMESPACE}:{_HISTORY_DLQ_KEY}"
        c.lpush(full_key, json.dumps(payload, default=str))
        c.ltrim(full_key, 0, _HISTORY_DLQ_MAX - 1)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort DLQ
        logger.debug("history DLQ push skipped: %r", e)
        return False



def _send_twilio_sms(to_number: str, body: str) -> bool:
    """Send SMS via Twilio. Returns True on success."""
    try:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")

        if not all([account_sid, auth_token, from_number]):
            logger.warning("Twilio credentials not configured — SMS skipped")
            return False

        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=body,
            from_=from_number,
            to=to_number,
        )
        logger.info(f"SMS sent to {to_number}: sid={message.sid}")
        return True
    except Exception as e:
        logger.error(f"Twilio SMS failed to {to_number}: {e}")
        return False
