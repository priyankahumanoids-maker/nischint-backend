"""NISCH-008 — Live emergency stream API.

REST + WebSocket signalling for child→guardian emergency streams.

Auth boundary (locked):
  * `/initiate` — child of the incident OR admin/operator (manual override)
  * `/{id}/join`  — guardian linked via Relationship.accepted to the
                    incident's child OR admin/operator
  * `/{id}/end`   — child OR a guardian linked via Relationship
  * `/signal`     — same auth as `/join` (peer in the relay)

Privacy/integrity:
  * Stream IDs are random UUIDs — not guessable, not sequential.
  * ICE servers issued at /join time so guardians get the freshest
    possible TTL window.
  * Operator role can read but is NOT included in the SSE fan-out
    (per spec — guardian-network only for sensitive media metadata).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter, Depends, HTTPException, Query, WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.core.security import verify_token
from app.db.session import async_session as async_session_factory
from app.models.relationship import Relationship
from app.models.safety_incident import SafetyIncident
from app.models.stream_session import (
    STREAM_CONNECTING, STREAM_ENDED, STREAM_LIVE, STREAM_OFFERED,
    StreamSession,
)
from app.models.user import User
from app.services import user_service
from app.services.stream_initiator import (
    NTS_TOKEN_TTL_S, get_ice_servers, offer_stream_for_incident,
    transition_stream,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stream", tags=["Live Stream"])


# ════════════════════════════════════════════════════════════════════
# Auth helpers
# ════════════════════════════════════════════════════════════════════

async def _is_guardian_of(
    session: AsyncSession, user_id: UUID, child_id: UUID,
) -> bool:
    """True if `user_id` has an accepted Relationship row with `child_id`."""
    rel = (await session.execute(
        select(Relationship).where(
            Relationship.guardian_id == user_id,
            Relationship.child_id == child_id,
            Relationship.status == "accepted",
        )
    )).scalar_one_or_none()
    return rel is not None


async def _can_read_stream(
    session: AsyncSession, user: User, stream: StreamSession,
) -> bool:
    """Closed-network rule: child of the incident OR linked guardian
    OR admin/operator."""
    role = (user.role or "").lower()
    if role in ("admin", "operator"):
        return True
    if user.id == stream.child_id:
        return True
    return await _is_guardian_of(session, user.id, stream.child_id)


async def _load_stream(
    session: AsyncSession, stream_id: UUID,
) -> StreamSession:
    s = (await session.execute(
        select(StreamSession).where(StreamSession.id == stream_id)
    )).scalar_one_or_none()
    if s is None:
        raise HTTPException(404, "stream not found")
    return s


# ════════════════════════════════════════════════════════════════════
# REST endpoints
# ════════════════════════════════════════════════════════════════════

class InitiateBody(BaseModel):
    incident_id: UUID
    stream_type: str = Field("audio", description="audio|video")


@router.post("/initiate")
async def initiate_stream(
    body: InitiateBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Manually initiate a stream for an incident.

    Auto-offer fires from the state machine when an incident hits
    ESCALATED — this endpoint is the *manual* fallback (e.g. child
    triggers from the SOS modal). Reuses any active StreamSession
    for the same incident rather than spawning duplicates.
    """
    if body.stream_type not in ("audio", "video"):
        raise HTTPException(400, "stream_type must be audio|video")

    inc = (await session.execute(
        select(SafetyIncident).where(SafetyIncident.id == body.incident_id)
    )).scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "incident not found")

    role = (user.role or "").lower()
    if role not in ("admin", "operator") and user.id != inc.child_id:
        raise HTTPException(403, "only the child or admin/operator may initiate")

    stream = await offer_stream_for_incident(
        session, inc, stream_type=body.stream_type,
    )
    if stream is None:
        raise HTTPException(500, "failed to create stream session")
    await session.flush()

    return {
        "stream_id":   str(stream.id),
        "incident_id": str(stream.incident_id),
        "state":       stream.state,
        "stream_type": stream.stream_type,
        "ice_servers": (stream.ice_servers or {}).get("servers", []),
        "ttl_seconds": NTS_TOKEN_TTL_S,
        "ws_url":      f"/api/stream/{stream.id}/signal",
    }


@router.get("/{stream_id}/join")
async def join_stream(
    stream_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian-side join. Issues fresh ICE credentials at the moment
    the guardian asks (vs the moment the offer was made) so the TTL
    window is freshest.

    Also bumps `guardian_join_count` — a tally used for the operator
    timeline ("3 guardians listened to this stream")."""
    stream = await _load_stream(session, stream_id)
    if not await _can_read_stream(session, user, stream):
        raise HTTPException(403, "not authorized — closed network only")

    if stream.state in (STREAM_ENDED, "declined"):
        raise HTTPException(409, f"stream is {stream.state}")

    role = (user.role or "").lower()
    is_guardian = role not in ("admin", "operator") and user.id != stream.child_id
    if is_guardian:
        stream.guardian_join_count = int(stream.guardian_join_count or 0) + 1
        await session.flush()

    fresh_ice = get_ice_servers()
    return {
        "stream_id":   str(stream.id),
        "incident_id": str(stream.incident_id),
        "child_id":    str(stream.child_id),
        "state":       stream.state,
        "stream_type": stream.stream_type,
        "ice_servers": fresh_ice,
        "ttl_seconds": NTS_TOKEN_TTL_S,
        "ws_url":      f"/api/stream/{stream.id}/signal",
    }


class AcceptBody(BaseModel):
    pass


@router.post("/{stream_id}/accept")
async def accept_stream(
    stream_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Child-side accept of an offered stream. Transitions
    offered → connecting and unblocks guardians waiting on /join."""
    stream = await _load_stream(session, stream_id)
    if user.id != stream.child_id:
        raise HTTPException(403, "only the child may accept their stream")
    if stream.state != STREAM_OFFERED:
        raise HTTPException(409, f"stream is {stream.state}, not offered")

    await transition_stream(session, stream, STREAM_CONNECTING, actor_id=user.id)
    return {"stream_id": str(stream.id), "state": stream.state}


class EndBody(BaseModel):
    recording_url: Optional[str] = None
    duration_seconds: Optional[int] = None


@router.post("/{stream_id}/end")
async def end_stream(
    stream_id: UUID,
    body: EndBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """End a stream and persist the recording URL into the forensic
    timeline. Either party (child or any linked guardian/admin) may
    end. Idempotent — calling on an already-ended stream is a no-op."""
    stream = await _load_stream(session, stream_id)
    if not await _can_read_stream(session, user, stream):
        raise HTTPException(403, "not authorized — closed network only")

    if stream.state == STREAM_ENDED:
        return {"stream_id": str(stream.id), "state": stream.state,
                "duration_seconds": stream.duration_seconds,
                "recording_url": stream.recording_url}

    if body.recording_url:
        stream.recording_url = body.recording_url[:2048]  # crude guard
    if body.duration_seconds is not None:
        stream.duration_seconds = max(0, int(body.duration_seconds))

    # Force-allow ENDED from any non-terminal state by routing through
    # the correct prior. The state machine map already permits
    # offered/connecting/live → ended.
    await transition_stream(session, stream, STREAM_ENDED, actor_id=user.id)
    return {
        "stream_id":        str(stream.id),
        "state":            stream.state,
        "duration_seconds": stream.duration_seconds,
        "recording_url":    stream.recording_url,
    }


@router.get("/{stream_id}")
async def get_stream(
    stream_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Read a stream session envelope. Used by the mobile listener
    screen to recover state on cold start."""
    stream = await _load_stream(session, stream_id)
    if not await _can_read_stream(session, user, stream):
        raise HTTPException(403, "not authorized")
    return {
        "stream_id":        str(stream.id),
        "incident_id":      str(stream.incident_id),
        "child_id":         str(stream.child_id),
        "state":            stream.state,
        "stream_type":      stream.stream_type,
        "guardian_join_count": stream.guardian_join_count,
        "offered_at":       stream.offered_at.isoformat() if stream.offered_at else None,
        "started_at":       stream.started_at.isoformat() if stream.started_at else None,
        "ended_at":         stream.ended_at.isoformat() if stream.ended_at else None,
        "duration_seconds": stream.duration_seconds,
        "recording_url":    stream.recording_url,
    }


# ════════════════════════════════════════════════════════════════════
# Recording uploader (S3 presigned PUT)
# ════════════════════════════════════════════════════════════════════
#
# Two-step flow so the mobile uploader doesn't need AWS credentials:
#   1. POST /api/stream/{id}/recording/presign  → returns short-lived
#      PUT URL the client uploads the m4a/webm directly to.
#   2. POST /api/stream/{id}/recording/finalize → server fetches the
#      object's HEAD to verify it landed, then stores the URL on the
#      `stream_sessions` row so the forensic-replay chip can find it.
#
# Both endpoints fail-clean when `STREAM_RECORDING_BUCKET` env var
# isn't set — the WebRTC sprint can ship without S3 configured;
# recordings just won't be persisted. `recording_url` stays null.

import os
RECORDING_BUCKET = os.environ.get("STREAM_RECORDING_BUCKET", "").strip()
RECORDING_REGION = os.environ.get("AWS_REGION", "").strip() or "ap-south-1"
RECORDING_PRESIGN_TTL_S = 600   # 10 min — long enough for slow uploads
RECORDING_PUBLIC_TTL_S = 86_400 # 24h pre-signed GET on the persisted URL


def _s3_client():
    """Lazy-import boto3 so the route module doesn't crash if AWS
    creds / boto3 are missing in some downstream environment."""
    import boto3
    return boto3.client("s3", region_name=RECORDING_REGION)


class PresignBody(BaseModel):
    content_type: str = Field("audio/m4a")


@router.post("/{stream_id}/recording/presign")
async def presign_recording_upload(
    stream_id: UUID,
    body: PresignBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Mint a short-lived S3 PUT URL for the device-side recorder.

    Auth: the child of the incident only — guardians don't upload
    recordings, that's the recorder side. Admin can upload too (for
    debug fixtures)."""
    if not RECORDING_BUCKET:
        raise HTTPException(503, "recording bucket not configured")

    stream = await _load_stream(session, stream_id)
    role = (user.role or "").lower()
    if role != "admin" and user.id != stream.child_id:
        raise HTTPException(403, "only the child or admin may upload recordings")

    if body.content_type not in ("audio/m4a", "audio/webm", "audio/mp4", "audio/aac"):
        raise HTTPException(400, "unsupported content_type")

    # Deterministic key: incident_id + stream_id keeps it traceable
    # back without leaking child_id into the path (which a leaked
    # presigned URL would otherwise expose).
    key = f"streams/{stream.incident_id}/{stream.id}.m4a"
    try:
        client = _s3_client()
        put_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": RECORDING_BUCKET,
                "Key":    key,
                "ContentType": body.content_type,
            },
            ExpiresIn=RECORDING_PRESIGN_TTL_S,
            HttpMethod="PUT",
        )
    except Exception as e:
        logger.warning(f"[STREAM] presign failed: {e!r}")
        raise HTTPException(500, "presign failed")

    return {
        "stream_id":      str(stream.id),
        "bucket":         RECORDING_BUCKET,
        "key":            key,
        "put_url":        put_url,
        "content_type":   body.content_type,
        "expires_in_s":   RECORDING_PRESIGN_TTL_S,
    }


class FinalizeBody(BaseModel):
    bucket: str
    key: str
    duration_seconds: Optional[int] = None


@router.post("/{stream_id}/recording/finalize")
async def finalize_recording(
    stream_id: UUID,
    body: FinalizeBody,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Verify the upload landed, mint a 24h pre-signed GET URL, and
    persist it to `stream_sessions.recording_url` for the forensic
    chip. Idempotent — calling on an already-finalized row overwrites
    `recording_url` with a fresh pre-signed URL (useful when the prior
    URL has expired)."""
    if not RECORDING_BUCKET:
        raise HTTPException(503, "recording bucket not configured")

    if body.bucket != RECORDING_BUCKET:
        raise HTTPException(400, "bucket mismatch")

    stream = await _load_stream(session, stream_id)
    role = (user.role or "").lower()
    if role != "admin" and user.id != stream.child_id:
        raise HTTPException(403, "only the child or admin may finalize")

    # HEAD the object — proves it actually landed before we wire it
    # into the forensic timeline.
    try:
        client = _s3_client()
        client.head_object(Bucket=body.bucket, Key=body.key)
    except Exception as e:
        logger.warning(f"[STREAM] HEAD failed for {body.bucket}/{body.key}: {e!r}")
        raise HTTPException(404, "uploaded object not found")

    # Pre-sign a GET URL valid for 24h. Stored verbatim — the timeline
    # endpoint surfaces it without re-signing. When the URL expires
    # the chip falls back to "Recording unavailable" (UI-tested).
    try:
        get_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": body.bucket, "Key": body.key},
            ExpiresIn=RECORDING_PUBLIC_TTL_S,
            HttpMethod="GET",
        )
    except Exception as e:
        logger.warning(f"[STREAM] presign GET failed: {e!r}")
        raise HTTPException(500, "presign GET failed")

    stream.recording_url = get_url[:2048]
    if body.duration_seconds is not None:
        stream.duration_seconds = max(0, int(body.duration_seconds))
    await session.flush()

    return {
        "stream_id":        str(stream.id),
        "recording_url":    stream.recording_url,
        "duration_seconds": stream.duration_seconds,
        "expires_in_s":     RECORDING_PUBLIC_TTL_S,
    }


# ════════════════════════════════════════════════════════════════════
# WebSocket signalling relay
# ════════════════════════════════════════════════════════════════════
#
# Per-stream relay: every connected peer joins a room keyed on
# stream_id. Server forwards `offer`, `answer`, `ice_candidate`, and
# `end_stream` messages to the OTHER peers in the same room. We do
# NOT inspect the SDP/ICE payloads — server is a dumb router. This
# keeps the signalling layer thin and easy to swap if we move to a
# managed signalling provider later.
#
# Authorization is checked at WS accept time. Once accepted, peers
# can broadcast within their room without re-checking on every msg.

_stream_rooms: dict[str, set[WebSocket]] = defaultdict(set)
_stream_rooms_lock = asyncio.Lock()


async def _join_room(stream_id: str, ws: WebSocket) -> None:
    async with _stream_rooms_lock:
        _stream_rooms[stream_id].add(ws)


async def _leave_room(stream_id: str, ws: WebSocket) -> None:
    async with _stream_rooms_lock:
        peers = _stream_rooms.get(stream_id)
        if peers:
            peers.discard(ws)
            if not peers:
                _stream_rooms.pop(stream_id, None)


async def _broadcast_to_peers(
    stream_id: str, sender: WebSocket, message: dict,
) -> None:
    async with _stream_rooms_lock:
        peers = list(_stream_rooms.get(stream_id, set()))
    for peer in peers:
        if peer is sender:
            continue
        try:
            await peer.send_json(message)
        except Exception:
            # Peer is dead; reaper handles removal on disconnect.
            pass


@router.websocket("/{stream_id}/signal")
async def stream_signal(
    websocket: WebSocket,
    stream_id: str,
    token: Optional[str] = Query(None),
):
    """WebRTC signalling relay.

    Connect: `wss://host/api/stream/<id>/signal?token=<jwt>`

    Messages are passed through opaquely. Recognised types (used only
    for logging/metrics, not for routing decisions):
        offer | answer | ice_candidate | end_stream

    Any other JSON payload is forwarded as-is — keeps the layer
    forward-compatible with renegotiation rounds and bandwidth probes.
    """
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return
    user_id = verify_token(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return

    try:
        sid = UUID(stream_id)
    except (ValueError, TypeError):
        await websocket.close(code=4004, reason="Bad stream id")
        return

    # Auth + state validation in a fresh session — we don't share the
    # request-scoped session with a long-lived WS handler.
    async with async_session_factory() as session:
        try:
            user = await user_service.get_user_by_id(session, UUID(user_id))
        except (ValueError, Exception):
            await websocket.close(code=4001, reason="Invalid user")
            return
        if user is None:
            await websocket.close(code=4001, reason="User not found")
            return
        stream = (await session.execute(
            select(StreamSession).where(StreamSession.id == sid)
        )).scalar_one_or_none()
        if stream is None:
            await websocket.close(code=4004, reason="Stream not found")
            return
        if stream.state == STREAM_ENDED or stream.state == "declined":
            await websocket.close(code=4009, reason=f"Stream {stream.state}")
            return
        if not await _can_read_stream(session, user, stream):
            await websocket.close(code=4003, reason="Not authorized")
            return
        # Snapshot fields needed in the WS loop (stream may evolve).
        is_child = (user.id == stream.child_id)
        my_role = "child" if is_child else "guardian"

    await websocket.accept()
    await _join_room(stream_id, websocket)
    logger.info(
        f"[STREAM_WS] connected user={user_id} role={my_role} "
        f"stream={stream_id}"
    )

    try:
        await websocket.send_json({
            "type":     "connected",
            "stream_id": stream_id,
            "role":      my_role,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "reason": "bad_json"})
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")
            # Stamp the sender role so the peer can render UX cues.
            msg["_from_role"] = my_role
            msg.setdefault("stream_id", stream_id)

            if msg_type == "end_stream":
                # Persist transition, then broadcast end before we
                # close so peers can tear down gracefully.
                async with async_session_factory() as session:
                    s = (await session.execute(
                        select(StreamSession).where(StreamSession.id == sid)
                    )).scalar_one_or_none()
                    if s and s.state != STREAM_ENDED:
                        try:
                            await transition_stream(
                                session, s, STREAM_ENDED,
                                actor_id=UUID(user_id),
                            )
                            await session.commit()
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"[STREAM_WS] end transition failed: {e}")
                await _broadcast_to_peers(stream_id, websocket, msg)
                break

            if msg_type == "answer":
                # First answer → flip the stream LIVE if still connecting.
                async with async_session_factory() as session:
                    s = (await session.execute(
                        select(StreamSession).where(StreamSession.id == sid)
                    )).scalar_one_or_none()
                    if s and s.state == STREAM_CONNECTING:
                        try:
                            await transition_stream(
                                session, s, STREAM_LIVE,
                                actor_id=UUID(user_id),
                            )
                            await session.commit()
                        except Exception as e:  # noqa: BLE001
                            logger.debug(f"[STREAM_WS] live transition failed: {e}")

            await _broadcast_to_peers(stream_id, websocket, msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[STREAM_WS] loop crash user={user_id}: {e!r}")
    finally:
        await _leave_room(stream_id, websocket)
        logger.info(
            f"[STREAM_WS] disconnected user={user_id} stream={stream_id} "
            f"peers_remaining={len(_stream_rooms.get(stream_id, []))}"
        )


__all__ = ["router"]
