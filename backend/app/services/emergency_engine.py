# Emergency Engine — Silent SOS backend logic
#
# Flow: Trigger → Create Event → Notify Guardians (instant) → Track Location
# User gets cancel window AFTER guardians are notified.

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.emergency import EmergencyEvent
from app.models.guardian import Guardian
from app.services.redis_service import set_json, get_json, delete_key
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)


# ── SOS Trigger (immediate) ──

async def trigger_silent_sos(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    trigger_source: str,
    cancel_pin: str | None = None,
    device_metadata: dict | None = None,
) -> dict:
    """
    Create emergency event and notify guardians IMMEDIATELY.
    Cancel window is client-side — guardians are alerted instantly.
    """
    now = datetime.now(timezone.utc)

    # Hash the cancel PIN if provided
    pin_hash = None
    if cancel_pin:
        pin_hash = hashlib.sha256(cancel_pin.encode()).hexdigest()

    # Create emergency event
    event = EmergencyEvent(
        user_id=uuid.UUID(user_id),
        lat=lat,
        lng=lng,
        trigger_source=trigger_source,
        severity_level=2,  # distress
        status="active",
        cancel_pin_hash=pin_hash,
        location_trail=[{"lat": lat, "lng": lng, "ts": now.isoformat()}],
        guardians_notified=0,
        metadata_json=device_metadata,
    )
    session.add(event)
    await session.flush()

    event_id = str(event.id)

    # ── Migration to unified `trigger_alert` (NISCH-001 Phase 2) ──
    # Behind feature flag `ALERT_TRIGGER_V2_SOS`. When True, the unified
    # path replaces the inline guardian fan-out + push + SMS block. The
    # operator + child SSE broadcasts BELOW are kept (they're not
    # guardian-facing — they're audit + self-feedback channels).
    import os as _os
    _use_v2 = _os.environ.get("ALERT_TRIGGER_V2_SOS", "false").lower() == "true"

    if _use_v2:
        from app.services.alert_trigger import trigger_alert
        result = await trigger_alert(
            session,
            kind="sos",
            user_id=user_id,
            severity="critical",
            message="Emergency SOS triggered",
            details=f"Trigger: {trigger_source}",
            location={"lat": lat, "lng": lng},
            sse_event_type="emergency_triggered",
            sse_payload_extras={
                "event": "SOS_TRIGGERED",
                "event_id": event_id,
                "trigger_source": trigger_source,
                "severity_level": 2,
            },
            louder=True,
            idempotency_key=f"sos:{event_id}",
            cooldown_s=30,
        )
        notified = result.guardians_notified
        logger.warning(
            f"[ALERT_TRIGGER_V2] sos dispatched: {result.to_dict()}"
        )
    else:
        # Legacy path — push + SMS via inline _notify_guardians.
        notified = await _notify_guardians(session, user_id, event_id, lat, lng, trigger_source, now)

    # Update notification count
    event.guardians_notified = notified
    await session.flush()

    # Store in Redis for fast access
    event_data = {
        "event_id": event_id,
        "user_id": user_id,
        "lat": lat,
        "lng": lng,
        "trigger_source": trigger_source,
        "severity_level": 2,
        "status": "active",
        "guardians_notified": notified,
        "created_at": now.isoformat(),
        "location_trail": [{"lat": lat, "lng": lng, "ts": now.isoformat()}],
    }
    set_json("emergency", event_id, event_data)  # No TTL — stays until resolved
    _update_active_list(user_id, event_id, "add")

    logger.info(f"SILENT SOS triggered: event={event_id}, user={user_id}, trigger={trigger_source}, notified={notified}")

    # Live risk assessment — ALWAYS bypass cache during active emergency (safety rule)
    from app.services.redis_service import invalidate_forecast_grid
    invalidate_forecast_grid(lat, lng)  # Clear stale forecast for this cell

    # ── SSE BROADCAST: operators + child + ALL linked guardians ──
    from app.models.user import User

    # Get child's name for the event payload
    child_result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    child_user = child_result.scalar_one_or_none()
    child_name = child_user.full_name if child_user else "Child"

    # Create GuardianAlert record so GET /guardian/dashboard/alerts surfaces the emergency
    from app.models.guardian import GuardianAlert
    alert = GuardianAlert(
        user_id=uuid.UUID(user_id),
        alert_type="emergency_triggered",
        severity="critical",
        message=f"EMERGENCY: {child_name} triggered SOS!",
        details=f"Silent SOS triggered. Emergency Event: {event_id}",
        location={"lat": lat, "lng": lng},
    )
    session.add(alert)
    await session.commit()

    sse_payload = {
        "event": "SOS_TRIGGERED",
        "event_id": event_id,
        "child_id": user_id,
        "child_name": child_name,
        "user_id": user_id,
        "lat": lat,
        "lng": lng,
        "trigger_source": trigger_source,
        "severity_level": 2,
        "guardians_notified": notified,
    }

    # Broadcast to operators
    await broadcaster.broadcast_to_operators("emergency_triggered", sse_payload)

    # Broadcast to child's own channel
    await broadcaster.broadcast_to_user(user_id, "emergency_triggered", {
        "event": "SOS_TRIGGERED",
        "event_id": event_id,
    })

    # Broadcast to ALL linked guardians (check BOTH Guardian table AND Relationship table)
    # Skipped under V2 — `trigger_alert` already SSE-broadcast to each linked guardian above.
    from app.models.guardian import Guardian
    sse_guardian_ids = []

    if not _use_v2:
        # Source 1: Guardian table (email-based join)
        g_result = await session.execute(
            select(Guardian).where(
                Guardian.user_id == uuid.UUID(user_id),
                Guardian.is_active.is_(True),
            )
        )
        guardian_contacts = g_result.scalars().all()
        for gc in guardian_contacts:
            if gc.email:
                gu_result = await session.execute(select(User).where(User.email == gc.email))
                guardian_user = gu_result.scalar_one_or_none()
                if guardian_user:
                    gid = str(guardian_user.id)
                    sse_guardian_ids.append(gid)
                    await broadcaster.broadcast_to_user(gid, "emergency_triggered", sse_payload)
                    logger.info(f"[EMERGENCY_SSE_SENT] guardian={gc.name} ({gid}) child={user_id} (via Guardian table)")
                else:
                    logger.warning(f"[SOS-SSE] Guardian {gc.name} ({gc.email}) has no User account — SMS/push only")

        # Source 2: Relationship table (code-based linking — primary link source)
        from app.models.relationship import Relationship
        rel_result = await session.execute(
            select(Relationship).where(
                Relationship.child_id == uuid.UUID(user_id),
                Relationship.status == "accepted",
            )
        )
        for rel in rel_result.scalars().all():
            gid = str(rel.guardian_id)
            if gid not in sse_guardian_ids:
                sse_guardian_ids.append(gid)
                await broadcaster.broadcast_to_user(gid, "emergency_triggered", sse_payload)
                logger.info(f"[EMERGENCY_SSE_SENT] guardian={gid} child={user_id} (via Relationship table)")

        logger.info(f"[SOS-SSE] Total SSE: operators + child + {len(sse_guardian_ids)} guardian(s) — sources: Guardian={len(guardian_contacts)} Relationship={len(sse_guardian_ids) - len([gc for gc in guardian_contacts if gc.email])}")
    else:
        logger.info(f"[SOS-SSE] guardian fan-out delegated to trigger_alert (V2). Operators + child still broadcast above.")

    return {
        "event_id": event_id,
        "status": "active",
        "severity_level": 2,
        "guardians_notified": notified,
        "created_at": now.isoformat(),
        "message": "Emergency alert sent to guardians immediately.",
    }


# ── Location Update (every 5s during emergency) ──

async def update_emergency_location(
    session: AsyncSession,
    event_id: str,
    lat: float,
    lng: float,
) -> dict:
    """Append location to emergency trail. Updates both DB and Redis."""
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(EmergencyEvent).where(EmergencyEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Emergency event not found"}
    if event.status != "active":
        return {"error": f"Event is {event.status}, not active"}

    # Append to trail
    trail = list(event.location_trail or [])
    trail.append({"lat": lat, "lng": lng, "ts": now.isoformat()})
    event.location_trail = trail
    event.lat = lat
    event.lng = lng
    await session.flush()

    # Update Redis
    cached = get_json("emergency", event_id)
    if cached:
        cached["lat"] = lat
        cached["lng"] = lng
        cached["location_trail"] = trail
        set_json("emergency", event_id, cached)

    # Broadcast location update to operators
    user_id = str(event.user_id)
    await broadcaster.broadcast_to_operators("emergency_location_update", {
        "event": "LOCATION_UPDATE",
        "event_id": event_id,
        "user_id": user_id,
        "lat": lat,
        "lng": lng,
        "location_updates": len(trail),
    })

    return {
        "event_id": event_id,
        "status": "active",
        "location_updates": len(trail),
        "latest": {"lat": lat, "lng": lng, "ts": now.isoformat()},
    }


# ── Cancel SOS (requires PIN) ──

async def cancel_emergency(
    session: AsyncSession,
    event_id: str,
    cancel_pin: str,
) -> dict:
    """Cancel SOS. Requires correct PIN to prevent attacker cancellation."""
    result = await session.execute(
        select(EmergencyEvent).where(EmergencyEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Emergency event not found"}
    if event.status != "active":
        return {"error": f"Event is already {event.status}"}

    # Verify PIN
    if event.cancel_pin_hash:
        pin_hash = hashlib.sha256(cancel_pin.encode()).hexdigest()
        if pin_hash != event.cancel_pin_hash:
            return {"error": "Invalid cancellation PIN"}

    now = datetime.now(timezone.utc)
    event.status = "cancelled"
    event.resolved_at = now
    await session.flush()

    # Clean up Redis
    delete_key("emergency", event_id)
    _update_active_list(str(event.user_id), event_id, "remove")

    # Notify guardians of cancellation
    await _notify_guardians_cancel(session, str(event.user_id), event_id)

    logger.info(f"Emergency CANCELLED: event={event_id}")

    # Broadcast cancellation via SSE to operators + guardians
    user_id = str(event.user_id)

    from app.models.user import User
    child_result_c = await session.execute(select(User).where(User.id == event.user_id))
    child_user = child_result_c.scalar_one_or_none()
    child_name = child_user.full_name if child_user else "Child"

    cancel_payload = {
        "event": "SOS_CANCELLED",
        "event_id": event_id,
        "child_id": user_id,
        "child_name": child_name,
        "user_id": user_id,
        "resolved_at": now.isoformat(),
    }
    await broadcaster.broadcast_to_operators("emergency_cancelled", cancel_payload)

    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(session, user_id)
    for guardian_id in guardian_ids:
        await broadcaster.broadcast_to_user(
            guardian_id,
            "emergency_cancelled",
            cancel_payload,
        )
    logger.info(f"[SOS-SSE] Cancellation broadcast to operators + guardians")

    return {
        "event_id": event_id,
        "status": "cancelled",
        "resolved_at": now.isoformat(),
        "message": "Emergency cancelled. Guardians have been notified.",
    }


# ── Resolve SOS (by guardian or system) ──

async def resolve_emergency(
    session: AsyncSession,
    event_id: str,
) -> dict:
    """Mark emergency as resolved."""
    result = await session.execute(
        select(EmergencyEvent).where(EmergencyEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Emergency event not found"}

    now = datetime.now(timezone.utc)
    event.status = "resolved"
    event.resolved_at = now
    await session.flush()

    delete_key("emergency", event_id)
    _update_active_list(str(event.user_id), event_id, "remove")

    await _notify_guardians_all_clear(
        session,
        str(event.user_id),
        event_id,
        "resolved",
    )

    logger.info(f"Emergency RESOLVED: event={event_id}")

    # Broadcast resolution via SSE to operators + guardians
    user_id = str(event.user_id)

    from app.models.user import User
    child_result_r = await session.execute(select(User).where(User.id == event.user_id))
    child_user = child_result_r.scalar_one_or_none()
    child_name = child_user.full_name if child_user else "Child"

    resolve_payload = {
        "event": "SOS_RESOLVED",
        "event_id": event_id,
        "child_id": user_id,
        "child_name": child_name,
        "user_id": user_id,
        "resolved_at": now.isoformat(),
    }
    await broadcaster.broadcast_to_operators("emergency_resolved", resolve_payload)

    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(session, user_id)
    for guardian_id in guardian_ids:
        await broadcaster.broadcast_to_user(
            guardian_id,
            "emergency_resolved",
            resolve_payload,
        )
    logger.info(f"[SOS-SSE] Resolution broadcast to operators + guardians")

    return {
        "event_id": event_id,
        "status": "resolved",
        "resolved_at": now.isoformat(),
        "duration_seconds": round((now - event.created_at).total_seconds()),
        "location_updates": len(event.location_trail or []),
    }


# ── Get Active Emergencies ──

async def get_active_emergencies(
    session: AsyncSession,
    user_id: str | None = None,
) -> list[dict]:
    """Get all active emergencies, optionally filtered by user."""
    query = select(EmergencyEvent).where(EmergencyEvent.status == "active")
    if user_id:
        query = query.where(EmergencyEvent.user_id == uuid.UUID(user_id))
    query = query.order_by(EmergencyEvent.created_at.desc())

    result = await session.execute(query)
    events = []
    for e in result.scalars().all():
        events.append({
            "event_id": str(e.id),
            "user_id": str(e.user_id),
            "lat": e.lat,
            "lng": e.lng,
            "trigger_source": e.trigger_source,
            "severity_level": e.severity_level,
            "status": e.status,
            "guardians_notified": e.guardians_notified,
            "location_updates": len(e.location_trail or []),
            "created_at": e.created_at.isoformat(),
        })
    return events


# ── Get Emergency Details ──

async def get_emergency_details(
    session: AsyncSession,
    event_id: str,
) -> dict:
    """Get full emergency details including location trail."""
    # Try Redis first for active events
    cached = get_json("emergency", event_id)
    if cached and cached.get("status") == "active":
        return cached

    # Fall back to DB
    result = await session.execute(
        select(EmergencyEvent).where(EmergencyEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Emergency event not found"}

    return {
        "event_id": str(event.id),
        "user_id": str(event.user_id),
        "lat": event.lat,
        "lng": event.lng,
        "trigger_source": event.trigger_source,
        "severity_level": event.severity_level,
        "status": event.status,
        "guardians_notified": event.guardians_notified,
        "location_trail": event.location_trail or [],
        "created_at": event.created_at.isoformat(),
        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
        "metadata": event.metadata_json,
    }


# ── Internal: Guardian Notification ──

async def _notify_guardians(
    session: AsyncSession,
    user_id: str,
    event_id: str,
    lat: float,
    lng: float,
    trigger_source: str,
    timestamp: datetime,
) -> int:
    """Send push + SMS to all linked guardians using unified resolution. Returns count notified."""
    from app.models.user import User
    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, child_name = await _resolve_guardian_ids(session, user_id)

    if not guardian_ids:
        logger.warning(f"No guardians found for user {user_id}")
        return 0

    notified = 0
    for gid in guardian_ids:
        try:
            # Push notification
            try:
                from app.services.push_service import send_push_to_user
                from app.services.notification_formatter import push_sos
                title, body = push_sos(child_name or "Your loved one", {"lat": lat, "lng": lng})
                await send_push_to_user(
                    session=session,
                    user_id=uuid.UUID(gid),
                    title=title,
                    body=body,
                    data={
                        "type": "EMERGENCY_TRIGGERED",
                        "event_type": "emergency_triggered",
                        "alert_type": "emergency_triggered",
                        "event_id": event_id,
                        "child_id": user_id,
                        "child_name": child_name or "Protected member",
                        "lat": lat,
                        "lng": lng,
                        "severity": "critical",
                        "screen": "alerts",
                    },
                    channel_id="critical_safety",
                    louder=True,
                )
            except Exception as push_err:
                logger.warning(f"Push failed for guardian {gid}: {push_err}")

            # SMS fallback
            try:
                g_user = (await session.execute(select(User).where(User.id == uuid.UUID(gid)))).scalar_one_or_none()
                if g_user and g_user.phone:
                    from app.services.sms_service import send_sos_sms
                    send_sos_sms(
                        to=g_user.phone,
                        user_name=child_name or "Your loved one",
                        location={"lat": lat, "lng": lng},
                    )
            except Exception as sms_err:
                logger.warning(f"SMS failed for guardian {gid}: {sms_err}")

            notified += 1
        except Exception as e:
            logger.error(f"Failed to notify guardian {gid}: {e}")

    logger.info(f"Emergency {event_id}: notified {notified}/{len(guardian_ids)} guardians")
    return notified


async def _notify_guardians_cancel(session: AsyncSession, user_id: str, event_id: str):
    """Notify guardians that the emergency was cancelled."""
    await _notify_guardians_all_clear(
        session,
        user_id,
        event_id,
        "cancelled",
    )


async def _notify_guardians_all_clear(
    session: AsyncSession,
    user_id: str,
    event_id: str,
    status: str,
):
    """Push a named all-clear to every linked guardian account."""
    from app.services.alert_trigger import _resolve_guardian_ids
    from app.services.push_service import send_push_to_user
    from app.services.notification_formatter import push_emergency_cancelled

    guardian_ids, child_name = await _resolve_guardian_ids(session, user_id)
    display_name = child_name or "Protected member"
    title, body = push_emergency_cancelled(display_name)
    event_type = (
        "emergency_resolved"
        if status == "resolved"
        else "emergency_cancelled"
    )

    for guardian_id in guardian_ids:
        try:
            await send_push_to_user(
                session=session,
                user_id=uuid.UUID(guardian_id),
                title=title,
                body=body,
                data={
                    "type": event_type.upper(),
                    "eventType": event_type,
                    "event_type": event_type,
                    "alert_type": event_type,
                    "event_id": event_id,
                    "child_id": user_id,
                    "child_name": display_name,
                    "user_name": display_name,
                    "severity": "low",
                    "screen": "alerts",
                },
                channel_id="safety-alerts",
            )
        except Exception as exc:
            logger.warning(
                "All-clear push failed guardian=%s event=%s: %s",
                guardian_id,
                event_id,
                exc,
            )


# ── Redis Active List Management ──

def _update_active_list(user_id: str, event_id: str, action: str):
    """Maintain a Redis list of active emergency event IDs per user."""
    key_data = get_json("emergency", "active") or {}
    user_events = key_data.get(user_id, [])

    if action == "add" and event_id not in user_events:
        user_events.append(event_id)
    elif action == "remove" and event_id in user_events:
        user_events.remove(event_id)

    key_data[user_id] = user_events
    set_json("emergency", "active", key_data)  # No TTL
