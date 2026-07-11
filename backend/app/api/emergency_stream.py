"""NISCH-008 — Emergency stream recording API.

Six endpoints:
    POST /api/emergency-stream/sessions                       (child / system)
    POST /api/emergency-stream/sessions/{id}/chunks/presign   (child)
    POST /api/emergency-stream/sessions/{id}/chunks/{cid}/complete (child)
    POST /api/emergency-stream/sessions/{id}/finalize         (child / system)
    GET  /api/emergency-stream/sessions/{id}                  (op / guard / admin)
    GET  /api/emergency-stream/sessions/{id}/chunks/{cid}/playback (op/guard/admin)

Plus stub-mode local-storage helpers (active when NISCH008_MOCK_S3=true):
    PUT  /api/emergency-stream/_mock_s3
    GET  /api/emergency-stream/_mock_s3

The stub endpoints implement the same security model as real S3
pre-signed URLs — HMAC-signed `(key, expires_at, op)` query params —
so the wire contract is identical between stub and real modes. Mobile
client code doesn't change when we flip `NISCH008_MOCK_S3=false`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import (APIRouter, Depends, HTTPException, Query, Request, Response,
                     status)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services import emergency_stream_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emergency-stream", tags=["emergency-stream"])


# ── Schemas ──────────────────────────────────────────────────────────
class StartSessionRequest(BaseModel):
    incident_id: uuid.UUID
    trigger:     str   = Field("safety_brain_alert", max_length=64)
    risk_score:  float | None = None


class StartSessionResponse(BaseModel):
    session_id: uuid.UUID
    state:      str
    started_at: str | None


class PresignPutRequest(BaseModel):
    sequence:     int
    media_type:   str    # "audio_chunk" | "video_thumbnail"
    content_type: str    # "audio/webm" | "image/jpeg" | …
    size_bytes:   int


class PresignPutResponse(BaseModel):
    chunk_id:     uuid.UUID
    upload_url:   str
    s3_key:       str
    content_type: str
    expires_at:   int
    expires_in:   int
    mock_s3:      bool


class CompleteChunkRequest(BaseModel):
    size_bytes:     int | None = None
    content_sha256: str | None = Field(default=None, max_length=64)


class ChunkSummary(BaseModel):
    chunk_id:      uuid.UUID
    sequence:      int
    media_type:    str
    content_type:  str
    size_bytes:    int
    upload_status: str
    uploaded_at:   str | None
    expires_at:    str


class SessionSummary(BaseModel):
    session_id:  uuid.UUID
    incident_id: uuid.UUID
    child_id:    uuid.UUID
    state:       str
    stream_type: str
    started_at:  str | None
    ended_at:    str | None
    duration_seconds: int | None
    chunks:      list[ChunkSummary]


class PresignGetResponse(BaseModel):
    download_url: str
    s3_key:       str
    content_type: str
    size_bytes:   int
    expires_at:   int
    expires_in:   int
    mock_s3:      bool


# ── Helpers ──────────────────────────────────────────────────────────
def _ip_for(req: Request) -> str | None:
    fwd = req.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.client.host if req.client else None


# ── Endpoints ────────────────────────────────────────────────────────
@router.post("/sessions", response_model=StartSessionResponse)
async def start_session(
    body: StartSessionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Open (or reuse) a recording session for an incident.

    Auto-called from `safety_brain_service.compute_risk_score` on
    `alert_fired=True`; also callable by the child themselves to
    manually start recording (e.g. SOS button on the dashboard).
    """
    sess = await svc.start_recording_session(
        db,
        child_id=current_user.id,
        incident_id=body.incident_id,
        trigger=body.trigger,
        risk_score=body.risk_score,
    )
    await db.commit()
    return StartSessionResponse(
        session_id=sess.id,
        state=sess.state,
        started_at=sess.started_at.isoformat() if sess.started_at else None,
    )


@router.post("/sessions/{session_id}/chunks/presign",
             response_model=PresignPutResponse)
async def presign_chunk(
    session_id: uuid.UUID,
    body: PresignPutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Issue a pre-signed PUT URL so the mobile client can upload one
    audio chunk or one 1-fps thumbnail directly. Only the child who
    owns the session can request URLs."""
    from app.models.stream_session import StreamSession
    sess = await db.get(StreamSession, session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")
    if sess.child_id != current_user.id:
        raise HTTPException(403, "Only the session owner can upload chunks")
    try:
        out = await svc.issue_presign_put(
            db,
            session_id=session_id,
            sequence=body.sequence,
            media_type=body.media_type,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return PresignPutResponse(**out)


@router.post("/sessions/{session_id}/chunks/{chunk_id}/complete")
async def complete_chunk(
    session_id: uuid.UUID,
    chunk_id: uuid.UUID,
    body: CompleteChunkRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Client tells the backend "I finished uploading this chunk".
    Optional — the stub-mode local-storage endpoint also marks
    chunks uploaded server-side. Idempotent."""
    from app.models.stream_session import StreamSession
    sess = await db.get(StreamSession, session_id)
    if sess is None or sess.child_id != current_user.id:
        raise HTTPException(403, "Not the session owner")
    row = await svc.mark_chunk_uploaded(
        db, chunk_id=chunk_id,
        size_bytes=body.size_bytes,
        content_sha256=body.content_sha256,
    )
    if row is None:
        raise HTTPException(404, "Chunk not found")
    await db.commit()
    return {"chunk_id": str(row.id), "upload_status": row.upload_status}


@router.post("/sessions/{session_id}/finalize")
async def finalize(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    from app.models.stream_session import StreamSession
    sess = await db.get(StreamSession, session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")
    if sess.child_id != current_user.id and current_user.role not in (
        "admin", "operator",
    ):
        raise HTTPException(403, "Not authorised")
    row = await svc.finalize_session(db, session_id=session_id)
    await db.commit()
    return {
        "session_id": str(row.id),
        "state":      row.state,
        "ended_at":   row.ended_at.isoformat() if row.ended_at else None,
        "duration_seconds": row.duration_seconds,
    }


@router.get("/sessions/{session_id}", response_model=SessionSummary)
async def get_session(
    session_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    from app.models.stream_session import StreamSession
    sess = await db.get(StreamSession, session_id)
    if sess is None:
        raise HTTPException(404, "Session not found")
    if not await svc._viewer_can_access(
        db, sess=sess,
        viewer_user_id=current_user.id, viewer_role=current_user.role or "guardian",
    ):
        raise HTTPException(403, "Not authorised for this session")

    chunks = await svc.list_chunks(db, session_id=session_id)
    await svc.audit_session_view(
        db,
        session_id=session_id,
        viewer_user_id=current_user.id,
        viewer_role=current_user.role or "guardian",
        ip_address=_ip_for(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return SessionSummary(
        session_id=sess.id,
        incident_id=sess.incident_id,
        child_id=sess.child_id,
        state=sess.state,
        stream_type=sess.stream_type,
        started_at=sess.started_at.isoformat() if sess.started_at else None,
        ended_at=sess.ended_at.isoformat() if sess.ended_at else None,
        duration_seconds=sess.duration_seconds,
        chunks=[
            ChunkSummary(
                chunk_id=c.id, sequence=c.sequence,
                media_type=c.media_type, content_type=c.content_type,
                size_bytes=c.size_bytes, upload_status=c.upload_status,
                uploaded_at=c.uploaded_at.isoformat() if c.uploaded_at else None,
                expires_at=c.expires_at.isoformat(),
            )
            for c in chunks
        ],
    )


@router.get("/sessions/{session_id}/chunks/{chunk_id}/playback",
            response_model=PresignGetResponse)
async def playback_url(
    session_id: uuid.UUID,
    chunk_id: uuid.UUID,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        out = await svc.issue_presign_get_for_chunk(
            db,
            chunk_id=chunk_id,
            viewer_user_id=current_user.id,
            viewer_role=current_user.role or "guardian",
            ip_address=_ip_for(request),
            user_agent=request.headers.get("user-agent"),
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    await db.commit()
    return PresignGetResponse(**out)


# ── Stub-mode local storage endpoints ─────────────────────────────────
@router.put("/_mock_s3", status_code=status.HTTP_200_OK)
async def mock_s3_put(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    key:     str = Query(...),
    expires: int = Query(...),
    op:      str = Query(...),
    token:   str = Query(...),
):
    if not svc.MOCK_S3:
        raise HTTPException(404, "Mock storage disabled")
    if op != "put" or not svc.verify_mock_token(key, expires, op, token):
        raise HTTPException(403, "Invalid or expired pre-signed PUT URL")

    body = await request.body()
    if not body:
        raise HTTPException(400, "Empty body")
    size = svc.write_mock_bytes(key, body)
    # Mark the matching chunk as uploaded.
    from sqlalchemy import select
    from app.models.stream_recording_chunk import StreamRecordingChunk
    row = (await db.execute(
        select(StreamRecordingChunk)
        .where(StreamRecordingChunk.s3_key == key)
        .limit(1)
    )).scalar_one_or_none()
    if row is not None:
        await svc.mark_chunk_uploaded(db, chunk_id=row.id, size_bytes=size)
        await db.commit()
    return {"ok": True, "key": key, "bytes": size}


@router.get("/_mock_s3")
async def mock_s3_get(
    key:     str = Query(...),
    expires: int = Query(...),
    op:      str = Query(...),
    token:   str = Query(...),
):
    if not svc.MOCK_S3:
        raise HTTPException(404, "Mock storage disabled")
    if op != "get" or not svc.verify_mock_token(key, expires, op, token):
        raise HTTPException(403, "Invalid or expired pre-signed GET URL")
    try:
        data = svc.read_mock_bytes(key)
    except FileNotFoundError:
        raise HTTPException(404, "Object not found")
    # Best-effort content-type from extension; not required for stub.
    ct_map = {".webm": "audio/webm", ".m4a": "audio/mp4",
              ".jpg": "image/jpeg", ".png": "image/png"}
    suffix = "." + key.rsplit(".", 1)[-1] if "." in key else ""
    return Response(content=data,
                    media_type=ct_map.get(suffix, "application/octet-stream"))
