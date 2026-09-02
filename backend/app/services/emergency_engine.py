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


def _sos_external_transport_ready() -> bool:
    """True only when server-owned Firebase/Twilio credentials are provisioned."""
    try:
        from app.core.config import settings

        firebase_explicit = bool(
            getattr(settings, "firebase_sa_key_path", None)
            or getattr(settings, "firebase_sa_key_json", None)
            or (
                getattr(settings, "firebase_private_key", None)
                and getattr(settings, "firebase_client_email", None)
            )
        )
        sms_explicit = bool(getattr(settings, "twilio_account_sid", None))
        return firebase_explicit or sms_explicit
    except Exception:
        return False


async def _broadcast_fast_coparents_v65c(
    *,
    primary_guardian_id: str,
    event_type: str,
    payload: dict,
) -> list[str]:
    """Resolve + broadcast linked co-parents without blocking primary SSE.

    Uses an independent short-lived DB session so this lookup can run in
    parallel with the frozen V6.5 child/primary fast lane and the main event
    flush. Failures return only successfully delivered IDs, leaving the
    existing V6.4 resolver as the compatibility fallback.
    """
    try:
        primary_uuid = uuid.UUID(str(primary_guardian_id))
    except (ValueError, TypeError, AttributeError):
        return []

    try:
        from app.core.product_roles import is_co_guardian
        from app.db.session import async_session

        async with async_session() as bg_session:
            rows = (
                await bg_session.execute(
                    select(User.id, User.role).where(
                        User.guardian_id == primary_uuid,
                        User.is_active.is_(True),
                    )
                )
            ).all()

        co_parent_ids: list[str] = []
        for row in rows:
            if not is_co_guardian(getattr(row, "role", None)):
                continue

            candidate_id = str(getattr(row, "id", "") or "").strip()
            if (
                candidate_id
                and candidate_id != str(primary_guardian_id)
                and candidate_id not in co_parent_ids
            ):
                co_parent_ids.append(candidate_id)

        delivered_ids: list[str] = []
        if co_parent_ids:
            results = await asyncio.gather(
                *(
                    broadcaster.broadcast_to_user(
                        co_parent_id,
                        event_type,
                        payload,
                    )
                    for co_parent_id in co_parent_ids
                ),
                return_exceptions=True,
            )
            delivered_ids = [
                co_parent_id
                for co_parent_id, result in zip(co_parent_ids, results)
                if not isinstance(result, BaseException)
            ]

        logger.warning(
            "[SOS_COPARENT_SSE_V65C] primary=%s delivered=%s resolved=%s",
            primary_guardian_id,
            delivered_ids,
            co_parent_ids,
        )
        return delivered_ids

    except Exception as exc:
        logger.warning(
            "[SOS_COPARENT_SSE_V65C] fallback primary=%s error=%s",
            primary_guardian_id,
            exc,
        )
        return []


async def _resolve_fast_guardians_v64(
    session: AsyncSession,
    child_user_id: str,
) -> tuple[list[str], str]:
    """Primary guardian + current co-parent path in at most two DB reads."""
    try:
        child_uuid = uuid.UUID(str(child_user_id))
    except (ValueError, TypeError, AttributeError):
        return [], "Protected member"

    child = await session.get(User, child_uuid)
    if child is None:
        return [], "Protected member"

    child_name = child.full_name or "Protected member"
    guardian_ids: list[str] = []

    primary_guardian_id = getattr(child, "guardian_id", None)
    if primary_guardian_id:
        primary = str(primary_guardian_id)
        guardian_ids.append(primary)

        try:
            from app.core.product_roles import is_co_guardian

            co_parent_rows = (
                await session.execute(
                    select(User).where(
                        User.guardian_id == primary_guardian_id,
                        User.is_active.is_(True),
                    )
                )
            ).scalars().all()

            for candidate in co_parent_rows:
                if not is_co_guardian(candidate.role):
                    continue
                candidate_id = str(candidate.id)
                if candidate_id not in guardian_ids:
                    guardian_ids.append(candidate_id)
        except Exception as exc:
            logger.warning(
                "[SOS_FAST_RESOLVE_V64] co-parent lookup failed child=%s error=%s",
                child_user_id,
                exc,
            )

    return guardian_ids, child_name


async def _guardian_realtime_after_response_v64(
    *,
    user_id: str,
    event_type: str,
    payload: dict,
    already_sent: list[str] | None = None,
) -> None:
    """Full compatibility guardian graph after the first realtime response."""
    from app.db.session import async_session
    from app.services.alert_trigger import _resolve_guardian_ids

    sent = set(already_sent or [])
    try:
        async with async_session() as bg_session:
            guardian_ids, child_name = await _resolve_guardian_ids(bg_session, user_id)

        if child_name:
            payload = {**payload, "child_name": child_name}

        targets = [gid for gid in guardian_ids if gid not in sent]
        if targets:
            await asyncio.gather(
                *(
                    broadcaster.broadcast_to_user(gid, event_type, payload)
                    for gid in targets
                ),
                return_exceptions=True,
            )

        logger.info(
            "[SOS_COMPAT_SSE_V64] event=%s child=%s targets=%s",
            event_type,
            user_id,
            targets,
        )
    except Exception as exc:
        logger.warning(
            "[SOS_COMPAT_SSE_V64] failed event=%s child=%s error=%s",
            event_type,
            user_id,
            exc,
        )


async def _notify_guardians_background(
    user_id: str,
    event_id: str,
    lat: float,
    lng: float,
    trigger_source: str,
    timestamp: datetime,
) -> None:
    """Legacy push/SMS fan-out, isolated from the SOS hot path."""
    if not _sos_external_transport_ready():
        logger.warning(
            "[SOS_TRANSPORT_DEFERRED_V64] trigger event=%s "
            "Firebase/Twilio server credentials not provisioned",
            event_id,
        )
        return

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
    """All-clear push after realtime response, when transport is provisioned."""
    if not _sos_external_transport_ready():
        logger.warning(
            "[SOS_TRANSPORT_DEFERRED_V64] %s event=%s "
            "Firebase/Twilio server credentials not provisioned",
            status,
            event_id,
        )
        return

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
        guardian_ids, child_name = await _resolve_fast_guardians_v64(session, user_id)
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
    fast_child_name: str | None = None,
    fast_primary_guardian_id: str | None = None,
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

    # V6.5: allocate the EmergencyEvent UUID locally so the realtime
    # payload does not need to wait for a remote database flush.
    event_uuid = uuid.uuid4()

    event = EmergencyEvent(
        id=event_uuid,
        user_id=uuid.UUID(user_id),
        lat=lat,
        lng=lng,
        trigger_source=trigger_source,
        severity_level=2,
        status="active",
        cancel_pin_hash=pin_hash,
        location_trail=[{"lat": lat, "lng": lng, "ts": now.isoformat()}],
        guardians_notified=0,
        metadata_json=device_metadata,
    )

    session.add(event)
    event_id = str(event_uuid)

    # V6.5 PRIMARY GUARDIAN FAST LANE
    #
    # Authentication, role gating, active-SOS protection and rate limiting
    # have already completed in the API endpoint before this function runs.
    #
    # Reuse the authenticated User's full_name + guardian_id so the first
    # child/primary-guardian SSE does not require another DB lookup.
    child_name_fast = fast_child_name or "Protected member"

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

    primary_fast_guardian_ids: list[str] = []
    early_coparent_task: asyncio.Task | None = None

    try:
        primary_guardian_id = (
            str(fast_primary_guardian_id).strip()
            if fast_primary_guardian_id
            else ""
        )

        # Additive co-parent lane: schedule an independent lookup/broadcast,
        # but never await it in front of the proven V6.5 primary SSE.
        if (
            primary_guardian_id
            and primary_guardian_id != str(user_id)
        ):
            early_coparent_task = asyncio.create_task(
                _broadcast_fast_coparents_v65c(
                    primary_guardian_id=primary_guardian_id,
                    event_type="emergency_triggered",
                    payload=fast_payload,
                )
            )

        realtime_tasks = [
            broadcaster.broadcast_to_user(
                user_id,
                "emergency_triggered",
                fast_payload,
            )
        ]

        if (
            primary_guardian_id
            and primary_guardian_id != str(user_id)
        ):
            primary_fast_guardian_ids.append(primary_guardian_id)

            realtime_tasks.append(
                broadcaster.broadcast_to_user(
                    primary_guardian_id,
                    "emergency_triggered",
                    fast_payload,
                )
            )

        await asyncio.gather(
            *realtime_tasks,
            return_exceptions=True,
        )

        logger.warning(
            "[SOS_PRIMARY_SSE_V65] event=%s child=%s primary_guardians=%s",
            event_id,
            user_id,
            primary_fast_guardian_ids,
        )

    except Exception as primary_fast_error:
        logger.warning(
            "[SOS_PRIMARY_SSE_V65] fallback event=%s error=%s",
            event_id,
            primary_fast_error,
        )

    # Persist after the first realtime interruption attempt. The independent
    # co-parent task continues concurrently while this DB flush runs.
    await session.flush()

    # Collect only co-parent IDs whose early broadcast completed successfully,
    # so the V6.4 compatibility resolver can still retry any missed recipient.
    early_coparent_ids: list[str] = []
    if early_coparent_task is not None:
        try:
            early_coparent_ids = await early_coparent_task
        except Exception as early_coparent_error:
            logger.warning(
                "[SOS_COPARENT_SSE_V65C] join fallback event=%s error=%s",
                event_id,
                early_coparent_error,
            )

    # Preserve the existing V6.4 resolver as the canonical compatibility
    # fallback for any guardian the early lanes did not reach.
    fast_guardian_ids: list[str] = list(
        dict.fromkeys(
            primary_fast_guardian_ids
            + early_coparent_ids
        )
    )

    try:
        resolved_guardian_ids, resolved_child_name = (
            await _resolve_fast_guardians_v64(
                session,
                user_id,
            )
        )

        if resolved_child_name:
            child_name_fast = resolved_child_name
            fast_payload["child_name"] = resolved_child_name
            fast_payload["message"] = (
                f"EMERGENCY: {resolved_child_name} triggered SOS!"
            )

        compatibility_targets = [
            guardian_id
            for guardian_id in resolved_guardian_ids
            if guardian_id not in fast_guardian_ids
        ]

        if compatibility_targets:
            await asyncio.gather(
                *(
                    broadcaster.broadcast_to_user(
                        guardian_id,
                        "emergency_triggered",
                        fast_payload,
                    )
                    for guardian_id in compatibility_targets
                ),
                return_exceptions=True,
            )

        fast_guardian_ids = list(
            dict.fromkeys(
                fast_guardian_ids
                + list(resolved_guardian_ids)
            )
        )

        logger.warning(
            "[SOS_FAST_SSE_V64] event=%s child=%s guardians=%s",
            event_id,
            user_id,
            fast_guardian_ids,
        )

    except Exception as fast_sse_error:
        logger.warning(
            "[SOS_FAST_SSE_V64] fallback event=%s error=%s",
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

    # V6.4: operator audit + compatibility guardian graph are background-only.
    _spawn_sos_background(
        broadcaster.broadcast_to_operators("emergency_triggered", sse_payload),
        label=f"operator-trigger:{event_id}",
    )
    _spawn_sos_background(
        _guardian_realtime_after_response_v64(
            user_id=user_id,
            event_type="emergency_triggered",
            payload=sse_payload,
            already_sent=fast_guardian_ids,
        ),
        label=f"compat-trigger:{event_id}",
    )

    # Fast lane already sent to child + guardians. If guardian resolution failed
    # there, make one canonical fallback attempt here without touching push/SMS.
    if not _use_v2 and not fast_guardian_ids:
        try:
            fallback_guardian_ids, fallback_child_name = await _resolve_fast_guardians_v64(
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
                "[SOS_FAST_SSE_V64] compatibility fallback event=%s guardians=%s",
                event_id,
                fallback_guardian_ids,
            )
        except Exception as fallback_error:
            logger.warning(
                "[SOS_FAST_SSE_V64] compatibility fallback failed event=%s error=%s",
                event_id,
                fallback_error,
            )

    logger.info(
        "[SOS_REALTIME_V64] event=%s child=%s realtime_guardians=%s push_sms=background",
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

    # V6.4: protected-member cancellation state first; guardian sync follows.
    user_id = str(event.user_id)

    cancel_payload = {
        "event": "SOS_CANCELLED",
        "event_id": event_id,
        "child_id": user_id,
        "child_name": "Protected member",
        "user_id": user_id,
        "resolved_at": now.isoformat(),
    }

    await broadcaster.broadcast_to_user(
        user_id,
        "emergency_cancelled",
        cancel_payload,
    )

    cancel_fast_guardian_ids: list[str] = []
    try:
        cancel_fast_guardian_ids, cancel_child_name = await _resolve_fast_guardians_v64(
            session,
            user_id,
        )
        if cancel_child_name:
            cancel_payload["child_name"] = cancel_child_name
        if cancel_fast_guardian_ids:
            await asyncio.gather(
                *(
                    broadcaster.broadcast_to_user(
                        guardian_id,
                        "emergency_cancelled",
                        cancel_payload,
                    )
                    for guardian_id in cancel_fast_guardian_ids
                ),
                return_exceptions=True,
            )
        logger.info(
            "[SOS_CANCEL_FAST_GUARDIAN_V641] event=%s guardians=%s",
            event_id,
            cancel_fast_guardian_ids,
        )
    except Exception as fast_guardian_error:
        logger.warning(
            "[SOS_CANCEL_FAST_GUARDIAN_V641] failed event=%s error=%s",
            event_id,
            fast_guardian_error,
        )

    _spawn_sos_background(
        broadcaster.broadcast_to_operators("emergency_cancelled", cancel_payload),
        label=f"operator-cancel:{event_id}",
    )
    _spawn_sos_background(
        _guardian_realtime_after_response_v64(
            user_id=user_id,
            event_type="emergency_cancelled",
            payload=cancel_payload,
            already_sent=cancel_fast_guardian_ids,
        ),
        label=f"compat-cancel:{event_id}",
    )
    _spawn_sos_background(
        _notify_guardians_all_clear_background(user_id, event_id, "cancelled"),
        label=f"cancel:{event_id}",
    )

    logger.info(
        "[SOS_CANCEL_V64] event=%s child_realtime=1 "
        "guardian_sync=background transport=background",
        event_id,
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

    # V6.4: guardian response -> protected member is the first network action.
    user_id = str(event.user_id)

    resolve_payload = {
        "event": "SOS_RESOLVED",
        "event_id": event_id,
        "child_id": user_id,
        "child_name": "Protected member",
        "user_id": user_id,
        "resolved_at": now.isoformat(),
    }

    await broadcaster.broadcast_to_user(
        user_id,
        "emergency_resolved",
        resolve_payload,
    )

    resolve_fast_guardian_ids: list[str] = []
    try:
        resolve_fast_guardian_ids, resolve_child_name = await _resolve_fast_guardians_v64(
            session,
            user_id,
        )
        if resolve_child_name:
            resolve_payload["child_name"] = resolve_child_name
        if resolve_fast_guardian_ids:
            await asyncio.gather(
                *(
                    broadcaster.broadcast_to_user(
                        guardian_id,
                        "emergency_resolved",
                        resolve_payload,
                    )
                    for guardian_id in resolve_fast_guardian_ids
                ),
                return_exceptions=True,
            )
        logger.info(
            "[SOS_RESOLVE_FAST_GUARDIAN_V641] event=%s guardians=%s",
            event_id,
            resolve_fast_guardian_ids,
        )
    except Exception as fast_guardian_error:
        logger.warning(
            "[SOS_RESOLVE_FAST_GUARDIAN_V641] failed event=%s error=%s",
            event_id,
            fast_guardian_error,
        )

    _spawn_sos_background(
        broadcaster.broadcast_to_operators("emergency_resolved", resolve_payload),
        label=f"operator-resolve:{event_id}",
    )
    _spawn_sos_background(
        _guardian_realtime_after_response_v64(
            user_id=user_id,
            event_type="emergency_resolved",
            payload=resolve_payload,
            already_sent=resolve_fast_guardian_ids,
        ),
        label=f"compat-resolve:{event_id}",
    )

    if notify_guardians:
        _spawn_sos_background(
            _notify_guardians_all_clear_background(user_id, event_id, "resolved"),
            label=f"resolve:{event_id}",
        )

    logger.info(
        "[SOS_RESOLVE_V64] event=%s child_realtime=1 "
        "guardian_sync=background transport=%s",
        event_id,
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
