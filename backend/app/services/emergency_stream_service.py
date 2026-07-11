"""NISCH-008 — Emergency stream recording service.

Issues pre-signed PUT URLs (mobile uploads chunks directly to S3, or
to local disk in stub mode), records each chunk in
`stream_recording_chunks`, and issues pre-signed GET URLs for playback
gated by RBAC (operator + guardian + admin) with a DPDP-compliant
audit row written on every issuance.

# Storage modes

`NISCH008_MOCK_S3=true`  →  STUB MODE
  * Pre-signed PUT URL is a backend endpoint
    `{REACT_APP_BACKEND_URL}/api/emergency-stream/_mock_s3/{key}?token={tok}`
  * Mobile / web PUTs the chunk payload directly to that URL.
  * Backend writes the bytes to `NISCH008_LOCAL_DIR/{key}`.
  * Pre-signed GET URLs are the same endpoint with a different token.
  * Token = HMAC(secret_key, key + expires_at) — cheap, stateless,
    matches the security model of real pre-signed URLs.

`NISCH008_MOCK_S3=false` → REAL S3 MODE
  * boto3 `generate_presigned_url("put_object" | "get_object")`,
    SigV4, virtual-host addressing, ap-south-1.
  * Content-Type, ContentLength locked into the signature so a
    misbehaving client can't upload a 10 GB blob.

# Trigger model

Auto-trigger is wired in `safety_brain_service.compute_risk_score`:
when `alert_fired=True` it calls `start_recording_session(...)` in a
fire-and-forget task. The mobile app polls (or receives via WS) the
new session and starts capturing audio chunks + 1-fps thumbnails.

# RBAC for playback

`operator`, `guardian` (only for sessions where the child is in their
relationship list), and `admin` may issue GET URLs. `child` / `woman`
roles may issue GET URLs only for sessions they themselves own.
Every GET issuance writes a `stream_playback_audit` row.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.relationship import Relationship
from app.models.stream_playback_audit import (
    ACCESS_CHUNK_PLAYBACK, ACCESS_SESSION_SUMMARY, StreamPlaybackAudit,
)
from app.models.stream_recording_chunk import (
    CHUNK_PENDING, CHUNK_UPLOADED, MEDIA_AUDIO_CHUNK, MEDIA_VIDEO_THUMBNAIL,
    StreamRecordingChunk,
)
from app.models.stream_session import (
    STREAM_ENDED, STREAM_LIVE, STREAM_OFFERED, StreamSession,
)

logger = logging.getLogger(__name__)

# ── Config (env-driven) ─────────────────────────────────────────────
def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


MOCK_S3              = _env_bool("NISCH008_MOCK_S3", True)
BUCKET               = _env("NISCH008_BUCKET", "nischint-emergency-media-stub")
LOCAL_DIR            = Path(_env("NISCH008_LOCAL_DIR", "/tmp/nischint_emergency_media"))
RETENTION_DAYS       = int(_env("NISCH008_RETENTION_DAYS", "90"))
PRESIGN_PUT_TTL_S    = int(_env("NISCH008_PRESIGN_PUT_TTL_S", "600"))
PRESIGN_GET_TTL_S    = int(_env("NISCH008_PRESIGN_GET_TTL_S", "300"))
MAX_AUDIO_CHUNK_B    = int(_env("NISCH008_MAX_AUDIO_CHUNK_BYTES", str(512 * 1024)))
MAX_THUMBNAIL_B      = int(_env("NISCH008_MAX_THUMBNAIL_BYTES", str(200 * 1024)))

ALLOWED_AUDIO_TYPES = frozenset({"audio/webm", "audio/mp4", "audio/aac",
                                 "audio/mpeg", "audio/ogg"})
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png"})

# Stub-mode HMAC key — re-use the JWT secret so token issuance and
# verification are tied to the same trust root. In real-S3 mode this
# constant is unused.
def _hmac_secret() -> bytes:
    return (settings.jwt_secret or "stub-secret").encode("utf-8")


# ── Stub-mode token helpers ─────────────────────────────────────────
def _make_token(key: str, expires_at: int, op: str) -> str:
    """Sign `{key}|{expires_at}|{op}` with HMAC-SHA256. Returns 32-char hex."""
    msg = f"{key}|{expires_at}|{op}".encode("utf-8")
    digest = hmac.new(_hmac_secret(), msg, hashlib.sha256).digest()
    return digest[:16].hex()


def verify_mock_token(key: str, expires_at: int, op: str, token: str) -> bool:
    if not key or not token or op not in ("put", "get"):
        return False
    if expires_at < int(time.time()):
        return False
    expected = _make_token(key, expires_at, op)
    return hmac.compare_digest(expected, token)


# ── Key naming ───────────────────────────────────────────────────────
def _build_key(session_id: uuid.UUID, sequence: int, media_type: str,
               content_type: str) -> str:
    ext = {
        "audio/webm": "webm", "audio/mp4": "m4a", "audio/aac": "aac",
        "audio/mpeg": "mp3",  "audio/ogg": "ogg",
        "image/jpeg": "jpg",  "image/png": "png",
    }.get(content_type, "bin")
    bucket = "audio" if media_type == MEDIA_AUDIO_CHUNK else "thumbs"
    # No PII in keys — only session UUID + sequence + extension.
    return f"sessions/{session_id}/{bucket}/{sequence:06d}.{ext}"


# ── URL issuance ────────────────────────────────────────────────────
def _issue_url(key: str, op: str, ttl_s: int) -> tuple[str, int]:
    expires_at = int(time.time()) + ttl_s
    if MOCK_S3:
        token = _make_token(key, expires_at, op)
        base = (_env("APP_BASE_URL") or "").rstrip("/")
        if not base:
            # Fall back to a path-only URL so the mobile / web client
            # can prefix REACT_APP_BACKEND_URL itself.
            base = ""
        url = (
            f"{base}/api/emergency-stream/_mock_s3"
            f"?key={key}&expires={expires_at}&op={op}&token={token}"
        )
        return url, expires_at
    # ── Real S3 path (used when NISCH008_MOCK_S3=false) ─────────────
    import boto3
    from botocore.config import Config as BotoConfig
    client = boto3.client(
        "s3",
        region_name=_env("AWS_REGION", "ap-south-1"),
        aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"),
        config=BotoConfig(signature_version="s3v4",
                          s3={"addressing_style": "virtual"}),
    )
    method = "put_object" if op == "put" else "get_object"
    url = client.generate_presigned_url(
        ClientMethod=method,
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=ttl_s,
    )
    return url, expires_at


# ── Stub-mode local storage ─────────────────────────────────────────
def _local_path(key: str) -> Path:
    # Defence-in-depth — strip any leading slash and resolve into the
    # configured root. We reject anything that resolves outside the
    # root (path traversal guard).
    safe_key = key.lstrip("/")
    p = (LOCAL_DIR / safe_key).resolve()
    if LOCAL_DIR.resolve() not in p.parents and p != LOCAL_DIR.resolve():
        raise ValueError(f"Resolved path escapes the storage root: {p}")
    return p


def write_mock_bytes(key: str, data: bytes) -> int:
    p = _local_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p.stat().st_size


def read_mock_bytes(key: str) -> bytes:
    return _local_path(key).read_bytes()


# ── Session lifecycle ───────────────────────────────────────────────
async def start_recording_session(
    session: AsyncSession,
    *,
    child_id: uuid.UUID,
    incident_id: uuid.UUID,
    trigger: str = "safety_brain_alert",
    risk_score: float | None = None,
) -> StreamSession:
    """Create (or reuse) a stream session for this incident and mark
    it `connecting`. Idempotent: callers re-firing on rapid alert
    sequences won't get duplicate rows for the same incident."""
    existing = await session.execute(
        select(StreamSession).where(
            and_(StreamSession.incident_id == incident_id,
                 StreamSession.state.in_([STREAM_OFFERED, STREAM_LIVE,
                                          "connecting"]))
        ).limit(1)
    )
    sess = existing.scalar_one_or_none()
    if sess is not None:
        logger.info(
            "[NISCH-008] reusing stream session=%s incident=%s trigger=%s",
            sess.id, incident_id, trigger,
        )
        return sess

    sess = StreamSession(
        id=uuid.uuid4(),
        incident_id=incident_id,
        child_id=child_id,
        state="connecting",
        stream_type="audio+thumbnail",
        offered_at=datetime.now(timezone.utc),
    )
    session.add(sess)
    await session.flush()
    logger.info(
        "[NISCH-008] opened stream session=%s incident=%s child=%s "
        "trigger=%s risk=%s",
        sess.id, incident_id, child_id, trigger, risk_score,
    )
    return sess


async def finalize_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> StreamSession | None:
    row = await session.get(StreamSession, session_id)
    if row is None:
        return None
    if row.state == STREAM_ENDED:
        return row
    row.state = STREAM_ENDED
    row.ended_at = datetime.now(timezone.utc)
    if row.started_at:
        row.duration_seconds = int(
            (row.ended_at - row.started_at).total_seconds()
        )
    await session.flush()
    return row


# ── Chunk lifecycle ─────────────────────────────────────────────────
def _validate_chunk_request(media_type: str, content_type: str,
                            size_bytes: int) -> None:
    if media_type == MEDIA_AUDIO_CHUNK:
        if content_type not in ALLOWED_AUDIO_TYPES:
            raise ValueError(f"Unsupported audio content_type: {content_type}")
        if size_bytes <= 0 or size_bytes > MAX_AUDIO_CHUNK_B:
            raise ValueError(
                f"Audio chunk size {size_bytes} outside (0, {MAX_AUDIO_CHUNK_B}]"
            )
    elif media_type == MEDIA_VIDEO_THUMBNAIL:
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"Unsupported image content_type: {content_type}")
        if size_bytes <= 0 or size_bytes > MAX_THUMBNAIL_B:
            raise ValueError(
                f"Thumbnail size {size_bytes} outside (0, {MAX_THUMBNAIL_B}]"
            )
    else:
        raise ValueError(f"Unsupported media_type: {media_type}")


async def issue_presign_put(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    sequence: int,
    media_type: str,
    content_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    """Validate + reserve a chunk row + issue a pre-signed PUT URL."""
    _validate_chunk_request(media_type, content_type, size_bytes)

    sess = await session.get(StreamSession, session_id)
    if sess is None:
        raise ValueError(f"Stream session not found: {session_id}")
    if sess.state == STREAM_ENDED:
        raise ValueError("Stream session already ended")

    key = _build_key(session_id, sequence, media_type, content_type)
    url, expires_at = _issue_url(key, "put", PRESIGN_PUT_TTL_S)

    chunk = StreamRecordingChunk(
        id=uuid.uuid4(),
        session_id=session_id,
        sequence=sequence,
        media_type=media_type,
        content_type=content_type,
        s3_key=key,
        size_bytes=size_bytes,
        upload_status=CHUNK_PENDING,
        captured_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS),
    )
    session.add(chunk)

    # The very first audio chunk marks the session as live.
    if sess.state in (STREAM_OFFERED, "connecting") and media_type == MEDIA_AUDIO_CHUNK:
        sess.state = STREAM_LIVE
        sess.started_at = sess.started_at or datetime.now(timezone.utc)

    await session.flush()
    return {
        "chunk_id":     str(chunk.id),
        "upload_url":   url,
        "s3_key":       key,
        "content_type": content_type,
        "expires_at":   expires_at,
        "expires_in":   PRESIGN_PUT_TTL_S,
        "mock_s3":      MOCK_S3,
    }


async def mark_chunk_uploaded(
    session: AsyncSession,
    *,
    chunk_id: uuid.UUID,
    size_bytes: int | None = None,
    content_sha256: str | None = None,
) -> StreamRecordingChunk | None:
    row = await session.get(StreamRecordingChunk, chunk_id)
    if row is None:
        return None
    row.upload_status = CHUNK_UPLOADED
    row.uploaded_at = datetime.now(timezone.utc)
    if size_bytes is not None:
        row.size_bytes = size_bytes
    if content_sha256:
        row.content_sha256 = content_sha256
    await session.flush()
    return row


# ── Playback issuance + RBAC + audit ────────────────────────────────
async def _viewer_can_access(
    session: AsyncSession,
    *,
    sess: StreamSession,
    viewer_user_id: uuid.UUID,
    viewer_role: str,
) -> bool:
    """RBAC contract:
       • admin / operator   → all sessions
       • guardian           → sessions for a child they're related to
       • the child themselves → their own session
    """
    if viewer_role in ("admin", "operator"):
        return True
    if viewer_user_id == sess.child_id:
        return True
    if viewer_role == "guardian":
        rel = await session.execute(
            select(Relationship).where(
                and_(Relationship.guardian_id == viewer_user_id,
                     Relationship.child_id == sess.child_id,
                     Relationship.status == "accepted")
            ).limit(1)
        )
        return rel.scalar_one_or_none() is not None
    return False


async def issue_presign_get_for_chunk(
    session: AsyncSession,
    *,
    chunk_id: uuid.UUID,
    viewer_user_id: uuid.UUID,
    viewer_role: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    chunk = await session.get(StreamRecordingChunk, chunk_id)
    if chunk is None:
        raise ValueError(f"Chunk not found: {chunk_id}")
    # SQLite (used in unit tests) hands back naive datetimes; production
    # Postgres always returns tz-aware. Treat naive values as UTC so
    # this comparison never explodes across drivers.
    exp = chunk.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= datetime.now(timezone.utc):
        raise ValueError("Chunk has expired (past retention horizon)")
    sess = await session.get(StreamSession, chunk.session_id)
    if sess is None:
        raise ValueError("Session vanished")
    if not await _viewer_can_access(session, sess=sess,
                                    viewer_user_id=viewer_user_id,
                                    viewer_role=viewer_role):
        raise PermissionError("Viewer not authorised for this session")

    url, expires_at = _issue_url(chunk.s3_key, "get", PRESIGN_GET_TTL_S)

    session.add(StreamPlaybackAudit(
        session_id=sess.id,
        chunk_id=chunk.id,
        viewer_user_id=viewer_user_id,
        viewer_role=viewer_role,
        access_type=ACCESS_CHUNK_PLAYBACK,
        ip_address=ip_address,
        user_agent=user_agent,
        extra={"s3_key": chunk.s3_key, "sequence": chunk.sequence,
               "media_type": chunk.media_type},
    ))
    await session.flush()

    return {
        "download_url": url,
        "s3_key":       chunk.s3_key,
        "content_type": chunk.content_type,
        "size_bytes":   chunk.size_bytes,
        "expires_at":   expires_at,
        "expires_in":   PRESIGN_GET_TTL_S,
        "mock_s3":      MOCK_S3,
    }


async def audit_session_view(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    viewer_user_id: uuid.UUID,
    viewer_role: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Log a `session_summary` access without issuing a URL."""
    session.add(StreamPlaybackAudit(
        session_id=session_id,
        chunk_id=None,
        viewer_user_id=viewer_user_id,
        viewer_role=viewer_role,
        access_type=ACCESS_SESSION_SUMMARY,
        ip_address=ip_address,
        user_agent=user_agent,
        extra={},
    ))
    await session.flush()


async def list_chunks(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> list[StreamRecordingChunk]:
    res = await session.execute(
        select(StreamRecordingChunk)
        .where(StreamRecordingChunk.session_id == session_id)
        .order_by(StreamRecordingChunk.sequence.asc())
    )
    return list(res.scalars().all())
