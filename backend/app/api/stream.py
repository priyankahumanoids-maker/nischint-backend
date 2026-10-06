# SSE Stream Router — Scoped by user_id + role
import asyncio
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import settings
from app.core.security import verify_token
from app.models.user import User
from app.services import user_service
from app.services.event_broadcaster import broadcaster

logger = logging.getLogger(__name__)

SSE_PING_INTERVAL = settings.sse_ping_interval

router = APIRouter(prefix="/stream", tags=["stream"])

_disclosure_tasks: set[asyncio.Task] = set()


async def _write_emergency_view(viewer_id, target_id):
    # Independent short transaction; emergency delivery never waits for DB I/O.
    from app.db.session import async_session
    from app.services.family_circle_audit_service import record_location_disclosure
    try:
        async with async_session() as audit_session:
            await record_location_disclosure(
                audit_session, subject_user_id=target_id, viewer_user_id=viewer_id,
                viewer_kind="emergency", view_kind="live",
            )
            await audit_session.commit()
    except Exception:
        logger.exception("Emergency location disclosure audit failed")


def _encode_event(viewer: User, event: dict) -> str:
    from app.services.family_location_disclosure import has_coordinates
    data = event.get("data") or {}
    target = data.get("child_id") or data.get("user_id") if isinstance(data, dict) else None
    if (event.get("type") in {"emergency_triggered", "emergency_location_update"}
            and target and str(target) != str(viewer.id) and has_coordinates(data)):
        if len(_disclosure_tasks) < 128:
            async def bounded_audit():
                try:
                    await asyncio.wait_for(_write_emergency_view(viewer.id, target), timeout=3)
                except Exception:
                    logger.warning("Emergency location disclosure audit timed out or failed")
            task = asyncio.create_task(bounded_audit())
            _disclosure_tasks.add(task)
            task.add_done_callback(_disclosure_tasks.discard)
        else:
            logger.error("Emergency disclosure audit backlog full; delivery preserved")
    return f"id: {event.get('id', '')}\nevent: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n"


async def _family_event_allowed(session: AsyncSession, viewer: User, event: dict) -> bool:
    """Re-authorize ordinary location-bearing SSE events at delivery time.

    Emergency SOS delivery is deliberately independent of normal sharing. The
    canonical check prevents queued/replayed ordinary location from surviving a
    pause, consent withdrawal, entitlement expiry, leave or removal.
    """
    event_type = str(event.get("type") or "")
    if event_type in {"emergency_triggered", "emergency_location_update"}:
        return True
    if event_type not in {"location_update", "risk_update"}:
        return True
    data = event.get("data")
    if not isinstance(data, dict):
        return True
    target = data.get("child_id") or data.get("user_id")
    if not target or str(target) == str(viewer.id):
        return True
    from app.core.family_circle_permissions import (
        ACTION_VIEW_LOCATION, ACTION_VIEW_AI_PROFILE, ACTION_VIEW_ACTIVITY, ACTION_VIEW_LOCATION_HISTORY,
    )
    from app.services.family_location_disclosure import has_coordinates
    from app.services.family_circle_runtime_authority import runtime_decision
    decision = await runtime_decision(
        session, actor_user_id=viewer.id, target_user_id=target,
        action=ACTION_VIEW_LOCATION, record_disclosure=False,
    )
    if decision.canonical:
        if decision.allowed:
            # risk_update has a distinct purpose, never an implicit location grant.
            if event_type == "risk_update":
                ai = await runtime_decision(session, actor_user_id=viewer.id,
                    target_user_id=target, action=ACTION_VIEW_AI_PROFILE)
                if not ai.allowed:
                    await session.rollback()
                    return False
            else:
                # Per-recipient copy: never redact the shared broadcaster event.
                filtered = dict(data)
                purpose_fields = (
                    (ACTION_VIEW_AI_PROFILE, {"risk", "risk_level", "risk_score", "behavior_pattern", "recommendation", "factors"}),
                    (ACTION_VIEW_ACTIVITY, {"session", "session_id", "eta_minutes", "speed", "speed_mps", "distance_m", "route_deviated"}),
                    (ACTION_VIEW_LOCATION_HISTORY, {"trail", "route_points", "location_history"}),
                )
                for action, fields in purpose_fields:
                    if fields.intersection(filtered):
                        field_decision = await runtime_decision(session, actor_user_id=viewer.id,
                            target_user_id=target, action=action)
                        if not field_decision.allowed:
                            filtered = {key: value for key, value in filtered.items() if key not in fields}
                event["data"] = filtered
            # Log only the fields actually surviving per-recipient filtering.
            # Recheck the purpose at disclosure time; permission probes and
            # redacted historical coordinates must not create a live view.
            disclosed = event.get("data") or {}
            history_fields = {"trail", "route_points", "location_history"}
            for action, coordinates in (
                (ACTION_VIEW_LOCATION, {k: v for k, v in disclosed.items() if k not in history_fields}),
                (ACTION_VIEW_LOCATION_HISTORY, {k: v for k, v in disclosed.items() if k in history_fields}),
            ):
                if has_coordinates(coordinates):
                    logged = await runtime_decision(session, actor_user_id=viewer.id,
                        target_user_id=target, action=action, record_disclosure=True)
                    if not logged.allowed:
                        await session.rollback()
                        return False
            await session.commit()
            return True
        await session.rollback()
        return False
    return True


async def _emergency_recipient_allowed(session: AsyncSession, viewer: User, event: dict) -> bool:
    """Re-authorize the current emergency recipient at SSE delivery time.

    Emergency eligibility remains independent of ordinary sharing, pause, consent
    and Lifeline. This check only prevents stale/legacy channels from delivering
    another person's emergency event to a viewer who is no longer a current
    canonical emergency recipient. Genuine legacy-to-legacy delivery is retained.
    """
    event_type = str(event.get("type") or "")
    if event_type not in {"emergency_triggered", "emergency_location_update"}:
        return True
    data = event.get("data")
    if not isinstance(data, dict):
        return True
    target = data.get("child_id") or data.get("user_id")
    if not target or str(target) == str(viewer.id):
        return True
    from app.services.family_circle_runtime_authority import alert_recipient_ids
    canonical, recipients = await alert_recipient_ids(session, target)
    if not canonical:
        return True
    return str(viewer.id) in {str(uid) for uid in recipients}


async def get_user_from_token(
    token: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token required")

    user_id = verify_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user = await user_service.get_user_by_id(session, UUID(user_id))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def _scoped_event_generator(channel: str, request: Request, meta: dict, session: AsyncSession, viewer: User):
    """Generate SSE events for a specific channel with replay on reconnect."""
    queue = await broadcaster.subscribe(channel)

    try:
        yield f"event: connected\ndata: {json.dumps(meta)}\n\n"

        # Replay missed events (last 5 minutes) — covers disconnect gaps
        replay_events = await broadcaster.get_replay_events(channel)
        for evt in replay_events:
            evt = dict(evt)
            if not await _emergency_recipient_allowed(session, viewer, evt):
                continue
            if not await _family_event_allowed(session, viewer, evt):
                continue
            event_type = evt.get("type", "message")
            event_id = evt.get("id", "")
            yield _encode_event(viewer, evt)

        while True:
            if await request.is_disconnected():
                logger.info(f"Client disconnected from {channel}")
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=float(SSE_PING_INTERVAL))
                event = dict(event)
                if not await _emergency_recipient_allowed(session, viewer, event):
                    continue
                if not await _family_event_allowed(session, viewer, event):
                    continue
                event_type = event.get("type", "message")
                event_id = event.get("id", "")
                yield _encode_event(viewer, event)
            except asyncio.TimeoutError:
                yield f"event: ping\ndata: {json.dumps({'ts': asyncio.get_event_loop().time()})}\n\n"

    except asyncio.CancelledError:
        logger.info(f"SSE cancelled for {channel}")
    finally:
        await broadcaster.unsubscribe(channel, queue)


async def _coparent_event_generator(
    user_channel: str,
    primary_channel: str,
    request: Request,
    meta: dict,
    session: AsyncSession,
    viewer: User,
):
    """Co-parent SSE with zero-extra-publish SOS fast lane.

    The authenticated co-parent keeps their normal user channel and also
    listens to the already-existing primary guardian user channel. Only
    emergency_triggered events are forwarded from the primary channel; all
    other primary-only events remain private. The later canonical co-parent
    user-channel copy is suppressed by logical event type + event_id.
    """
    user_queue = await broadcaster.subscribe(user_channel)
    primary_queue = await broadcaster.subscribe(primary_channel)
    merged_queue: asyncio.Queue = asyncio.Queue()
    pumps: list[asyncio.Task] = []
    seen: set[str] = set()
    seen_order: list[str] = []

    def logical_key(event: dict) -> str | None:
        event_type = str(event.get("type") or "")
        data = event.get("data")
        if not event_type or not isinstance(data, dict):
            return None
        logical_id = data.get("event_id")
        if not logical_id:
            return None
        return f"{event_type}:{logical_id}"

    def duplicate(event: dict) -> bool:
        key = logical_key(event)
        if key is None:
            return False
        if key in seen:
            return True
        if len(seen_order) >= 256:
            seen.discard(seen_order.pop(0))
        seen_order.append(key)
        seen.add(key)
        return False

    def primary_fast_allowed(event: dict) -> bool:
        return str(event.get("type") or "") == "emergency_triggered"

    async def pump(source: str, queue: asyncio.Queue) -> None:
        while True:
            event = await queue.get()
            await merged_queue.put((source, event))

    try:
        pumps = [
            asyncio.create_task(pump("user", user_queue)),
            asyncio.create_task(pump("primary", primary_queue)),
        ]

        yield f"event: connected\ndata: {json.dumps(meta)}\n\n"

        # Keep the canonical co-parent replay unchanged. Primary-channel replay
        # contributes only SOS-trigger events and is logically deduplicated.
        for event in await broadcaster.get_replay_events(user_channel):
            event = dict(event)
            if not await _emergency_recipient_allowed(session, viewer, event):
                continue
            if not await _family_event_allowed(session, viewer, event):
                continue
            if duplicate(event):
                continue
            event_type = event.get("type", "message")
            event_id = event.get("id", "")
            yield _encode_event(viewer, event)

        for event in await broadcaster.get_replay_events(primary_channel):
            if not primary_fast_allowed(event):
                continue
            event = dict(event)
            if not await _emergency_recipient_allowed(session, viewer, event):
                continue
            if duplicate(event):
                continue
            event_type = event.get("type", "message")
            event_id = event.get("id", "")
            yield _encode_event(viewer, event)

        while True:
            if await request.is_disconnected():
                logger.info(f"Client disconnected from {user_channel}")
                break

            try:
                source, event = await asyncio.wait_for(
                    merged_queue.get(),
                    timeout=float(SSE_PING_INTERVAL),
                )
                event = dict(event)
                if source == "primary" and not primary_fast_allowed(event):
                    continue
                if not await _emergency_recipient_allowed(session, viewer, event):
                    continue
                if source == "user" and not await _family_event_allowed(session, viewer, event):
                    continue
                if duplicate(event):
                    continue
                event_type = event.get("type", "message")
                event_id = event.get("id", "")
                yield _encode_event(viewer, event)
            except asyncio.TimeoutError:
                yield f"event: ping\ndata: {json.dumps({'ts': asyncio.get_event_loop().time()})}\n\n"

    except asyncio.CancelledError:
        logger.info(f"SSE cancelled for {user_channel}")
    finally:
        for task in pumps:
            task.cancel()
        if pumps:
            await asyncio.gather(*pumps, return_exceptions=True)
        await broadcaster.unsubscribe(user_channel, user_queue)
        await broadcaster.unsubscribe(primary_channel, primary_queue)


@router.get("")
async def stream_events(
    request: Request,
    current_user: User = Depends(get_user_from_token),
    session: AsyncSession = Depends(get_db_session),
):
    """
    SSE endpoint scoped by user role:
      - guardian: subscribes to user:{user_id} — only their seniors' events
      - operator/admin: subscribes to role:operator — all facility events
    """
    user_id = str(current_user.id)

    if current_user.role in ("operator", "admin"):
        channel = broadcaster.operator_channel()
        meta = {"channel": channel, "role": current_user.role}
    else:
        channel = broadcaster.user_channel(user_id)
        meta = {"channel": channel, "user_id": user_id}

    if current_user.role == "co_parent" and current_user.guardian_id:
        primary_channel = broadcaster.user_channel(str(current_user.guardian_id))
        meta["primary_sos_channel"] = primary_channel
        generator = _coparent_event_generator(
            channel,
            primary_channel,
            request,
            meta,
            session,
            current_user,
        )
    else:
        generator = _scoped_event_generator(channel, request, meta, session, current_user)

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
