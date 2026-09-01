# Emergency Engine — Silent SOS backend logic
#
# Flow: Trigger → Create Event → Notify Guardians (instant) → Track Location
# User gets cancel window AFTER guardians are notified.

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.emergency import EmergencyEvent
from app.models.guardian import Guardian
from app.models.user import User
from app.services.redis_service import set_json, get_json, delete_key
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)


_sos_background_tasks: set[asyncio.Task] = set()


def _spawn_sos_background(coro, *, label: str) -> None:
    """Run non-realtime notification work without holding the SOS HTTP path."""
    try:
        task = asyncio.create_task(coro)
    except RuntimeError as exc:
        try:
            coro.close()
        except Exception:
            pass
        logger.warning("[SOS_BACKGROUND_NOTIFY] schedule failed label=%s error=%s", label, exc)
        return

    _sos_background_tasks.add(task)

    def _done(done_task: asyncio.Task) -> None:
        _sos_background_tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.warning("[SOS_BACKGROUND_NOTIFY] cancelled label=%s", label)
        except Exception as exc:
            logger.warning("[SOS_BACKGROUND_NOTIFY] failed label=%s error=%s", label, exc)

    task.add_done_callback(_done)


async def _notify_guardians_background(
    user_id: str,
    event_id: str,
    lat: float,
    lng: float,
    trigger_source: str,
    timestamp: datetime,
) -> None:
    """Legacy push/SMS fan-out on a fresh DB session, never the SOS request session."""
    from app.db.session import async_session

    async with async_session() as bg_session:
        await _notify_guardians(
            bg_session,
            user_id,
            event_id,
            lat,
            lng,
            trigger_source,
            timestamp,
        )
        await bg_session.commit()


async def _notify_guardians_all_clear_background(
    user_id: str,
    event_id: str,
    status: str,
) -> None:
    """All-clear push on a fresh DB session; SSE has already been sent."""
    from app.db.session import async_session

    async with async_session() as bg_session:
        await _notify_guardians_all_clear(bg_session, user_id, event_id, status)
        await bg_session.commit()


async def _dispatch_repeat_sos_background(
    *,
    event_id: str,
    user_id: str,
    lat: float,
    lng: float,
    trigger_source: str,
    repeat_id: str,
) -> None:
    """Persist + push a repeat SOS after the realtime SSE lane has returned."""
    from app.db.session import async_session
    from app.services.alert_trigger import trigger_alert

    async with async_session() as bg_session:
        await trigger_alert(
            bg_session,
            kind="sos",
            user_id=user_id,
            severity="critical",
            message="Emergency SOS triggered again",
            details=f"Repeated SOS tap. Trigger: {trigger_source}",
            location={"lat": lat, "lng": lng},
            sse_event_type="emergency_triggered",
            sse_payload_extras={
                "event": "SOS_TRIGGERED",
                "event_id": event_id,
                "repeat_trigger_id": repeat_id,
                "trigger_source": trigger_source,
                "severity_level": 2,
                "is_repeat": True,
            },
            louder=True,
            idempotency_key=None,
            cooldown_s=0,
            suppress_co_located=False,
        )
        await bg_session.commit()


async def notify_repeat_sos(
    session: AsyncSession,
    event_id: str,
    user_id: str,
    lat: float,
    lng: float,
    trigger_source: str,
) -> dict:
    """Realtime repeat SOS: SSE now, durable/push fan-out in background."""
    repeat_id = str(uuid.uuid4())

    try:
        from app.services.alert_trigger import _resolve_guardian_ids
        guardian_ids, child_name = await _resolve_guardian_ids(session, user_id)
    except Exception as exc:
        guardian_ids, child_name = [], "Protected member"
        logger.warning("[SOS_REPEAT_FAST] guardian resolution failed event=%s error=%s", event_id, exc)

    payload = {
        "event": "SOS_TRIGGERED",
        "event_id": event_id,
        "repeat_trigger_id": repeat_id,
        "trigger_source": trigger_source,
        "severity_level": 2,
        "severity": "critical",
        "is_repeat": True,
        "child_id": user_id,
        "user_id": user_id,
        "child_name": child_name or "Protected member",
        "lat": lat,
        "lng": lng,
        "message": f"EMERGENCY: {child_name or 'Protected member'} triggered SOS again!",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fast_lane": True,
    }

    await asyncio.gather(
        broadcaster.broadcast_to_operators("emergency_triggered", payload),
        broadcaster.broadcast_to_user(user_id, "emergency_triggered", payload),
        *(
            broadcaster.broadcast_to_user(gid, "emergency_triggered", payload)
            for gid in guardian_ids
        ),
        return_exceptions=True,
    )

    _spawn_sos_background(
        _dispatch_repeat_sos_background(
            event_id=event_id,
            user_id=user_id,
            lat=lat,
            lng=lng,
            trigger_source=trigger_source,
            repeat_id=repeat_id,
        ),
        label=f"repeat:{event_id}",
    )

    logger.warning(
        "[SOS_REPEAT_FAST] event=%s child=%s guardians=%s",
        event_id,
        user_id,
        guardian_ids,
    )
    return {"guardians_notified": len(guardian_ids), "repeat_trigger_id": repeat_id}


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

    # P0 realtime fast lane V6.3. Use the canonical guardian resolver so
    # primary guardian, co-parent and accepted relationship paths match the
    # already-working resolve flow. This lane deliberately runs before push/SMS.
    fast_guardian_ids: list[str] = []
    child_name_fast = "Protected member"
    try:
        from app.services.alert_trigger import _resolve_guardian_ids

        fast_guardian_ids, child_name_fast = await _resolve_guardian_ids(
            session,
            user_id,
        )
        child_name_fast = child_name_fast or "Protected member"

        fast_payload = {
            "event": "SOS_TRIGGERED",
            "event_id": event_id,
            "child_id": user_id,
            "child_name": child_name_fast,
            "user_id": user_id,
            "lat": lat,
            "lng": lng,
            "trigger_source": trigger_source,
            "severity_level": 2,
            "severity": "critical",
            "message": f"EMERGENCY: {child_name_fast} triggered SOS!",
            "timestamp": now.isoformat(),
            "fast_lane": True,
        }

        await asyncio.gather(
            broadcaster.broadcast_to_user(user_id, "emergency_triggered", fast_payload),
            *(
                broadcaster.broadcast_to_user(
                    guardian_id,
                    "emergency_triggered",
                    fast_payload,
                )
                for guardian_id in fast_guardian_ids
            ),
            return_exceptions=True,
        )

        logger.warning(
            "[SOS_FAST_SSE_V63] event=%s child=%s guardians=%s",
            event_id,
            user_id,
            fast_guardian_ids,
        )
    except Exception as fast_sse_error:
        logger.warning(
            "[SOS_FAST_SSE_V63] fallback event=%s error=%s",
            event_id,
            fast_sse_error,
        )

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
        # V6.3: realtime guardian recipients are already resolved/sent above.
        # Push/SMS is intentionally removed from the child SOS HTTP hot path.
        notified = len(fast_guardian_ids)

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

    # ── SSE BROADCAST: realtime first; push/SMS is background-only ──
    child_name = child_name_fast or "Protected member"

    # Persist exactly ONE guardian-facing alert row in the legacy path.
    if not _use_v2:
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

    # Durable event + legacy alert row before the slow transport fan-out starts.
    await session.commit()

    if not _use_v2:
        _spawn_sos_background(
            _notify_guardians_background(
                user_id,
                event_id,
                lat,
                lng,
                trigger_source,
                now,
            ),
            label=f"trigger:{event_id}",
        )

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
        "severity": "critical",
        "guardians_notified": notified,
        "timestamp": now.isoformat(),
    }

    # Operator audit remains best-effort and does not involve FCM.
    await broadcaster.broadcast_to_operators("emergency_triggered", sse_payload)

    # Fast lane already sent to child + guardians. If guardian resolution failed
    # there, make one canonical fallback attempt here without touching push/SMS.
    if not _use_v2 and not fast_guardian_ids:
        try:
            from app.services.alert_trigger import _resolve_guardian_ids
            fallback_guardian_ids, fallback_child_name = await _resolve_guardian_ids(
                session,
                user_id,
            )
            if fallback_child_name:
                sse_payload["child_name"] = fallback_child_name
            await asyncio.gather(
                broadcaster.broadcast_to_user(user_id, "emergency_triggered", sse_payload),
                *(
                    broadcaster.broadcast_to_user(
                        guardian_id,
                        "emergency_triggered",
                        sse_payload,
                    )
                    for guardian_id in fallback_guardian_ids
                ),
                return_exceptions=True,
            )
            fast_guardian_ids = fallback_guardian_ids
            notified = len(fallback_guardian_ids)
            event.guardians_notified = notified
            logger.warning(
                "[SOS_FAST_SSE_V63] compatibility fallback event=%s guardians=%s",
                event_id,
                fallback_guardian_ids,
            )
        except Exception as fallback_error:
            logger.warning(
                "[SOS_FAST_SSE_V63] compatibility fallback failed event=%s error=%s",
                event_id,
                fallback_error,
            )

    logger.info(
        "[SOS_REALTIME_V63] event=%s child=%s realtime_guardians=%s push_sms=background",
        event_id,
        user_id,
        fast_guardian_ids,
    )

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

    # Keep the same durable last-known location current during an SOS. The
    # passive geofence endpoint is intentionally bypassed while emergency
    # tracking is active, so without this update Guardian screens could fall
    # back to an older pre-SOS coordinate after the event/session ends.
    user_row = (
        await session.execute(
            select(User).where(User.id == event.user_id)
        )
    ).scalar_one_or_none()
    if user_row is not None:
        user_row.last_known_lat = float(lat)
        user_row.last_known_lng = float(lng)
        user_row.last_known_at = now

    await session.flush()

    # Update Redis
    cached = get_json("emergency", event_id)
    if cached:
        cached["lat"] = lat
        cached["lng"] = lng
        cached["location_trail"] = trail
        set_json("emergency", event_id, cached)

    # Broadcast the same live fix to operators and every linked guardian.
    # Push notifications wake a closed guardian app for the SOS itself; once
    # the app is open, these SSE updates keep the map moving without waiting
    # for its polling fallback.
    user_id = str(event.user_id)
    location_payload = {
        "event": "LOCATION_UPDATE",
        "event_id": event_id,
        "user_id": user_id,
        "child_id": user_id,
        "lat": lat,
        "lng": lng,
        "location_updates": len(trail),
        "captured_at": now.isoformat(),
    }
    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(session, user_id)
    await asyncio.gather(
        broadcaster.broadcast_to_operators(
            "emergency_location_update", location_payload
        ),
        *(
            broadcaster.broadcast_to_user(
                guardian_id,
                "emergency_location_update",
                location_payload,
            )
            for guardian_id in guardian_ids
        ),
        return_exceptions=True,
    )

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

    # V6.3: cancellation response is realtime in both directions.
    user_id = str(event.user_id)
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

    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(session, user_id)
    await asyncio.gather(
        broadcaster.broadcast_to_user(user_id, "emergency_cancelled", cancel_payload),
        broadcaster.broadcast_to_operators("emergency_cancelled", cancel_payload),
        *(
            broadcaster.broadcast_to_user(
                guardian_id,
                "emergency_cancelled",
                cancel_payload,
            )
            for guardian_id in guardian_ids
        ),
        return_exceptions=True,
    )

    _spawn_sos_background(
        _notify_guardians_all_clear_background(user_id, event_id, "cancelled"),
        label=f"cancel:{event_id}",
    )

    logger.info(
        "[SOS_CANCEL_V63] event=%s realtime_guardians=%s push=background",
        event_id,
        guardian_ids,
    )

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
    *,
    notify_guardians: bool = True,
) -> dict:
    """Mark emergency as resolved.

    notify_guardians=False is used when another authenticated workflow
    already sent the all-clear push (for example a SAFE check-in).
    SSE resolution still runs so every client can clear emergency state.
    """
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

    # V6.3: deliver the guardian response to the protected member first.
    user_id = str(event.user_id)
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

    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(session, user_id)
    await asyncio.gather(
        broadcaster.broadcast_to_user(user_id, "emergency_resolved", resolve_payload),
        broadcaster.broadcast_to_operators("emergency_resolved", resolve_payload),
        *(
            broadcaster.broadcast_to_user(
                guardian_id,
                "emergency_resolved",
                resolve_payload,
            )
            for guardian_id in guardian_ids
        ),
        return_exceptions=True,
    )

    if notify_guardians:
        _spawn_sos_background(
            _notify_guardians_all_clear_background(user_id, event_id, "resolved"),
            label=f"resolve:{event_id}",
        )

    logger.info(
        "[SOS_RESOLVE_V63] event=%s child_realtime=1 guardians=%s push=%s",
        event_id,
        guardian_ids,
        "background" if notify_guardians else "skipped",
    )

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
