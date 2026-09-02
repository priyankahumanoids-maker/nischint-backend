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


async def _scoped_event_generator(channel: str, request: Request, meta: dict):
    """Generate SSE events for a specific channel with replay on reconnect."""
    queue = await broadcaster.subscribe(channel)

    try:
        yield f"event: connected\ndata: {json.dumps(meta)}\n\n"

        # Replay missed events (last 5 minutes) — covers disconnect gaps
        replay_events = await broadcaster.get_replay_events(channel)
        for evt in replay_events:
            event_type = evt.get("type", "message")
            event_id = evt.get("id", "")
            yield f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(evt)}\n\n"

        while True:
            if await request.is_disconnected():
                logger.info(f"Client disconnected from {channel}")
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=float(SSE_PING_INTERVAL))
                event_type = event.get("type", "message")
                event_id = event.get("id", "")
                yield f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(event)}\n\n"
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
            if duplicate(event):
                continue
            event_type = event.get("type", "message")
            event_id = event.get("id", "")
            yield f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(event)}\n\n"

        for event in await broadcaster.get_replay_events(primary_channel):
            if not primary_fast_allowed(event) or duplicate(event):
                continue
            event_type = event.get("type", "message")
            event_id = event.get("id", "")
            yield f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(event)}\n\n"

        while True:
            if await request.is_disconnected():
                logger.info(f"Client disconnected from {user_channel}")
                break

            try:
                source, event = await asyncio.wait_for(
                    merged_queue.get(),
                    timeout=float(SSE_PING_INTERVAL),
                )
                if source == "primary" and not primary_fast_allowed(event):
                    continue
                if duplicate(event):
                    continue
                event_type = event.get("type", "message")
                event_id = event.get("id", "")
                yield f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(event)}\n\n"
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
        )
    else:
        generator = _scoped_event_generator(channel, request, meta)

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
