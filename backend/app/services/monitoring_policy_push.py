"""Data-only FCM wake-up for member monitoring-policy changes.

This is CONTROL PLANE traffic only. It does not create a safety event, Guardian
alert, SOS, or visible emergency notification. Its sole purpose is to wake the
protected member's own app/headless task so the persisted per-member AI/Mic/
Location policy can be applied while the UI is backgrounded or terminated.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


def _string_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def build_monitoring_policy_push_data(policy: dict[str, Any]) -> dict[str, str]:
    return {
        "event_type": "monitoring_policy_changed",
        "member_id": str(policy.get("member_id") or ""),
        "ai_enabled": _string_bool(policy.get("ai_enabled")),
        "location_enabled": _string_bool(policy.get("location_enabled")),
        "microphone_enabled": _string_bool(policy.get("microphone_enabled")),
        "version": str(int(policy.get("version") or 0)),
        "updated_at": str(policy.get("updated_at") or ""),
        "updated_by": str(policy.get("updated_by") or ""),
        "source": "monitoring_policy_fcm",
    }


async def send_monitoring_policy_wake(
    session: AsyncSession,
    member_id: str,
    policy: dict[str, Any],
) -> int:
    """Send a HIGH-priority DATA-ONLY FCM message to the protected member.

    No ``notification`` object is included. Android therefore routes this as a
    headless/background data message instead of displaying a second user-facing
    alert. Failure is best-effort and must never roll back the already-committed
    monitoring policy.
    """
    try:
        target_uuid = uuid.UUID(str(member_id))
    except (TypeError, ValueError, AttributeError):
        return 0

    try:
        # Reuse the project's existing token registry and Firebase OAuth source;
        # do not introduce a second credential configuration.
        from app.services.push_service import get_user_push_tokens, _get_access_token

        tokens = list(dict.fromkeys(await get_user_push_tokens(session, target_uuid)))
        if not tokens:
            logger.info("[MONITORING_POLICY_FCM] no token for member=%s", member_id)
            return 0

        access_token = await asyncio.to_thread(_get_access_token)
        project_id = settings.firebase_project_id
        if not project_id or not access_token:
            return 0

        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        data = build_monitoring_policy_push_data(policy)

        async with httpx.AsyncClient(timeout=10.0) as client:
            async def send_one(token: str) -> int:
                payload = {
                    "message": {
                        "token": token,
                        "data": data,
                        "android": {
                            "priority": "high",
                            "ttl": "300s",
                        },
                        "apns": {
                            "headers": {
                                "apns-priority": "5",
                                "apns-push-type": "background",
                            },
                            "payload": {
                                "aps": {
                                    "content-available": 1,
                                }
                            },
                        },
                    }
                }
                try:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if response.status_code == 200:
                        return 1
                    logger.warning(
                        "[MONITORING_POLICY_FCM] send failed member=%s status=%s body=%s",
                        member_id,
                        response.status_code,
                        response.text[:300],
                    )
                except Exception as exc:  # best-effort wake only
                    logger.warning(
                        "[MONITORING_POLICY_FCM] send error member=%s error=%s",
                        member_id,
                        exc,
                    )
                return 0

            results = await asyncio.gather(*(send_one(token) for token in tokens))
            sent = sum(results)
            logger.info(
                "[MONITORING_POLICY_FCM] member=%s version=%s sent=%s/%s",
                member_id,
                policy.get("version"),
                sent,
                len(tokens),
            )
            return sent
    except Exception as exc:
        logger.warning(
            "[MONITORING_POLICY_FCM] wake deferred member=%s error=%s",
            member_id,
            exc,
        )
        return 0
