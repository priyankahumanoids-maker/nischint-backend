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

    return StreamingResponse(
        _scoped_event_generator(channel, request, meta),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
