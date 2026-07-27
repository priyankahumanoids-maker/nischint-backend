"""Truthful protected-device location availability and stale-heartbeat alerts."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.redis_service import get_json, set_json

logger = logging.getLogger(__name__)

STATUS_NAMESPACE = "location_availability"
REGISTRY_NAMESPACE = "location_monitor"
REGISTRY_KEY = "protected_users"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_user(user_id: str) -> None:
    registry = get_json(REGISTRY_NAMESPACE, REGISTRY_KEY) or {"ids": []}
    ids = [str(value) for value in registry.get("ids", []) if value]
    if user_id not in ids:
        ids.append(user_id)
        set_json(REGISTRY_NAMESPACE, REGISTRY_KEY, {"ids": ids[-5000:]})


async def record_location_availability(
    session: AsyncSession,
    user_id: str,
    *,
    available: bool,
    reason: str,
    source: str,
) -> dict:
    """Record a real status transition and notify guardians exactly once."""
    user_id = str(user_id)
    _register_user(user_id)
    previous = get_json(STATUS_NAMESPACE, user_id) or {}
    was_available = previous.get("available")
    now = _now_iso()

    state = {
        "user_id": user_id,
        "available": bool(available),
        "reason": reason,
        "source": source,
        "checked_at": now,
        "last_seen_at": (
            now
            if available and source == "protected_device"
            else previous.get("last_seen_at")
        ),
    }
    set_json(STATUS_NAMESPACE, user_id, state, ttl=7 * 24 * 3600)

    should_alert_unavailable = not available and was_available is not False
    should_alert_recovery = available and was_available is False
    if not should_alert_unavailable and not should_alert_recovery:
        return {**state, "transition": False}

    try:
        from app.services.alert_trigger import trigger_alert

        if available:
            await trigger_alert(
                session,
                kind="location_restored",
                user_id=user_id,
                severity="low",
                message="Location tracking is available again.",
                details="The protected device sent a current location heartbeat.",
                sse_event_type="safety_alert",
                sse_payload_extras={
                    "event_type": "location_tracking_restored",
                    "availability": "available",
                    "reason": reason,
                    "source": source,
                },
                idempotency_key="location-restored",
                cooldown_s=60,
                suppress_co_located=False,
            )
        else:
            reason_text = {
                "location_services_disabled": "Device Location Services are turned off.",
                "foreground_permission_denied": "Location permission is not granted.",
                "background_permission_denied": "Always/background location permission is not granted.",
                "heartbeat_stale": "The protected device stopped sending current location updates.",
            }.get(reason, "The protected device cannot currently share location.")
            await trigger_alert(
                session,
                kind="location_unavailable",
                user_id=user_id,
                severity="high",
                message="Location tracking unavailable.",
                details=reason_text,
                sse_event_type="safety_alert",
                sse_payload_extras={
                    "event_type": "location_tracking_unavailable",
                    "availability": "unavailable",
                    "reason": reason,
                    "source": source,
                },
                idempotency_key=f"location-unavailable:{reason}",
                cooldown_s=5 * 60,
                suppress_co_located=False,
            )
    except Exception as exc:
        logger.warning(
            "[LOCATION_AVAILABILITY] guardian alert failed user=%s: %s",
            user_id,
            exc,
        )

    return {**state, "transition": True}


async def detect_stale_location_heartbeats(session: AsyncSession) -> int:
    """Mark enrolled protected devices unavailable after heartbeat silence."""
    registry = get_json(REGISTRY_NAMESPACE, REGISTRY_KEY) or {"ids": []}
    now = datetime.now(timezone.utc)
    marked = 0
    for raw_user_id in registry.get("ids", []):
        user_id = str(raw_user_id)
        state = get_json(STATUS_NAMESPACE, user_id) or {}
        if state.get("available") is not True or not state.get("last_seen_at"):
            continue
        try:
            last_seen = datetime.fromisoformat(
                str(state["last_seen_at"]).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            continue
        if (now - last_seen).total_seconds() < settings.location_stale_threshold_seconds:
            continue
        await record_location_availability(
            session,
            user_id,
            available=False,
            reason="heartbeat_stale",
            source="server_watchdog",
        )
        marked += 1
    if marked:
        await session.commit()
    return marked
