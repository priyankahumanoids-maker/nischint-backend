# Push Notification Service (FCM via HTTP v1)
import json
import logging
from uuid import UUID

import google.auth.transport.requests
from google.oauth2 import service_account
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.log_sanitizer import mask_token

logger = logging.getLogger(__name__)

FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
_credentials = None


def _get_credentials():
    global _credentials
    if _credentials is None:
        sa_path = settings.firebase_sa_key_path
        if sa_path and __import__("os").path.exists(sa_path):
            _credentials = service_account.Credentials.from_service_account_file(
                sa_path, scopes=FCM_SCOPES
            )
        else:
            sa_json = settings.firebase_sa_key_json
            if sa_json:
                info = json.loads(sa_json)
                _credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=FCM_SCOPES
                )
    return _credentials


def _get_access_token() -> str:
    creds = _get_credentials()
    if creds is None:
        raise RuntimeError("Firebase service account not configured")
    request = google.auth.transport.requests.Request()
    creds.refresh(request)
    return creds.token


# ── Dead-token recognition (FCM v1 error codes) ─────────────────────
# Per Google docs, FCM v1 returns 404 / 400 with these errorCodes when
# the token is permanently invalid (uninstall, app data wipe, malformed
# token). Anything matching is purged immediately — keeps the
# notification dispatch fan-out tight and stops noisy retries.
_DEAD_TOKEN_ERRORS = {
    "UNREGISTERED",                      # 404 — uninstalled / token revoked
    "NOT_FOUND",                         # 404 — legacy phrasing
    "INVALID_ARGUMENT",                  # 400 — malformed
    "INVALID_REGISTRATION",              # legacy
    "REGISTRATION_TOKEN_NOT_REGISTERED", # legacy v1 phrasing
    "SENDER_ID_MISMATCH",                # 403 — token belongs to a different project
}


def _is_dead_token_response(status_code: int, body: str) -> bool:
    if status_code not in (400, 403, 404):
        return False
    if not body:
        return False
    # Normalize legacy dashed phrasing (e.g. `registration-token-not-registered`)
    # to the underscored canonical form before matching.
    upper = body.upper().replace("-", "_")
    return any(code in upper for code in _DEAD_TOKEN_ERRORS)


async def _purge_dead_token(token: str, reason: str) -> None:
    """Delete a known-dead FCM token from the DB. Best-effort — never raises."""
    try:
        from app.db.session import async_session as _session_factory
        async with _session_factory() as s:
            await s.execute(
                text("DELETE FROM push_tokens WHERE token = :t"),
                {"t": token},
            )
            await s.commit()
        logger.info(f"[FCM_TOKEN_PURGED] {mask_token(token)} reason={reason}")
    except Exception as e:
        logger.warning(f"[FCM_TOKEN_PURGE_FAIL] {mask_token(token)} {e}")


async def _record_token_success(token: str) -> None:
    """Bump last_success_at + reset consecutive_failures on a 200."""
    try:
        from app.db.session import async_session as _session_factory
        async with _session_factory() as s:
            await s.execute(
                text("""
                    UPDATE push_tokens
                       SET last_success_at = NOW(),
                           consecutive_failures = 0,
                           last_failure_reason = NULL
                     WHERE token = :t
                """),
                {"t": token},
            )
            await s.commit()
    except Exception as e:
        logger.debug(f"[FCM_HEALTH_SUCCESS_FAIL] {mask_token(token)} {e}")


async def _record_token_failure(token: str, reason: str) -> None:
    """Bump last_failure_at + increment consecutive_failures on a non-200.
    Called for transient failures too — ops want to see 'token X had 4
    consecutive 503s in 24h' to spot dying devices early."""
    try:
        from app.db.session import async_session as _session_factory
        async with _session_factory() as s:
            await s.execute(
                text("""
                    UPDATE push_tokens
                       SET last_failure_at = NOW(),
                           consecutive_failures = COALESCE(consecutive_failures, 0) + 1,
                           last_failure_reason = :r
                     WHERE token = :t
                """),
                {"t": token, "r": reason[:64]},
            )
            await s.commit()
    except Exception as e:
        logger.debug(f"[FCM_HEALTH_FAIL_FAIL] {mask_token(token)} {e}")


async def get_user_push_tokens(session: AsyncSession, user_id: UUID) -> list[str]:
    result = await session.execute(
        text("SELECT token FROM push_tokens WHERE user_id = :uid"),
        {"uid": user_id},
    )
    return [row[0] for row in result.fetchall()]


async def send_push_to_tokens(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
    channel_id: str = "safety-alerts",
    *,
    louder: bool = False,
) -> int:
    """Send HIGH priority push notification to a raw list of FCM tokens. Returns count sent.

    `louder=True` switches the payload to the **critical-channel**
    profile: aggressive vibration loop, sticky notification, DND
    bypass (when granted client-side), siren_loop sound. Used by the
    escalation engine on the `louder_push` step. Requires the Android
    client to have created the `critical_safety` channel — without
    that, FCM will silently downgrade to default channel.
    """
    if not tokens:
        return 0

    project_id = settings.firebase_project_id
    url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

    try:
        access_token = _get_access_token()
    except Exception as e:
        logger.error(f"Failed to get FCM access token: {e}")
        return 0

    push_data = {**(data or {}), "click_action": "FLUTTER_NOTIFICATION_CLICK"}
    if louder:
        push_data["louder_push"] = "true"
        # Force the critical-safety channel regardless of caller's
        # `channel_id` — the louder_push contract is "this MUST land
        # on the critical channel or not at all".
        channel_id = "critical_safety"

    sent = 0
    async with httpx.AsyncClient() as client:
        for token in tokens:
            android_notif = {
                "channel_id": channel_id,
                "notification_priority": "PRIORITY_MAX",
                "visibility": "PUBLIC",
            }
            apns_aps: dict = {"badge": 1, "content-available": 1}
            if louder:
                # Critical-channel profile: aggressive sound + vibration
                # loop + sticky. Must mirror the channel created on the
                # Android client. iOS gets the critical-alert headers.
                android_notif.update({
                    "sound": "siren_loop",
                    "default_vibrate_timings": False,
                    "vibrate_timings": ["0s", "0.5s", "0.5s", "0.5s"],
                    "sticky": True,
                })
                apns_aps["sound"] = {
                    "critical": 1,
                    "name": "siren_loop.caf",
                    "volume": 1.0,
                }
                apns_aps["interruption-level"] = "critical"
            else:
                android_notif["sound"] = "default"
                android_notif["default_vibrate_timings"] = True
                apns_aps["sound"] = "default"

            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": {k: str(v) for k, v in push_data.items()},
                    "android": {
                        "priority": "high",
                        "notification": android_notif,
                    },
                    "apns": {
                        "payload": {"aps": apns_aps},
                        "headers": {
                            "apns-priority": "10",
                            **({"apns-push-type": "alert"} if louder else {}),
                        },
                    },
                }
            }
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    logger.info(
                        f"[FCM_PUSH_SENT]{' LOUDER' if louder else ''} "
                        f"to={mask_token(token)} title={title}"
                    )
                    sent += 1
                    await _record_token_success(token)
                else:
                    logger.warning(f"[FCM_PUSH_FAIL] {resp.status_code}: {resp.text}")
                    if _is_dead_token_response(resp.status_code, resp.text):
                        await _purge_dead_token(token, reason=f"http={resp.status_code}")
                    else:
                        await _record_token_failure(token, reason=f"http={resp.status_code}")
            except Exception as e:
                logger.error(f"[FCM_PUSH_ERROR] {e}")
    return sent


async def send_push_to_user(
    session: AsyncSession,
    user_id: UUID,
    title: str,
    body: str,
    data: dict | None = None,
    channel_id: str = "safety-alerts",
    *,
    louder: bool = False,
) -> int:
    """Send HIGH priority push notification to all devices of a user. Returns count sent."""
    tokens = await get_user_push_tokens(session, user_id)
    if not tokens:
        logger.info(f"No push tokens for user {user_id}, skipping push")
        return 0
    sent = await send_push_to_tokens(tokens, title, body, data, channel_id, louder=louder)
    logger.info(f"[FCM_PUSH_COMPLETE]{' LOUDER' if louder else ''} "
                f"user={user_id} sent={sent}/{len(tokens)}")
    return sent
