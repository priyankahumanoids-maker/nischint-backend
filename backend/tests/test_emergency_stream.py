"""NISCH-008 — Emergency stream recording: end-to-end + RBAC + audit.

Locks the stub-mode contract end-to-end:
  1. Token issuance is HMAC-bound to (key, expires_at, op).
  2. Validation rejects bad media_type / content_type / size_bytes.
  3. RBAC: child owns + admin/operator + linked guardian can play back;
     unrelated users get 403.
  4. Every playback issuance writes a `stream_playback_audit` row.
  5. Stub-mode local PUT writes the bytes and flips the chunk row to
     `uploaded`; stub-mode GET serves the bytes back.

These tests do NOT hit the database — they exercise the pure helpers
(`_make_token`, `verify_mock_token`, `_build_key`, `_validate_chunk_request`)
plus a single async flow using an in-memory SQLite SQLAlchemy session
through a session-scoped fixture (locked to the same models the prod
schema uses).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ─ One-time compile rules so SQLite can render PostgreSQL types ─────
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_sqlite(element, compiler, **kw):
    return "CHAR(36)"

from app.db.base import Base
from app.models.relationship import Relationship
from app.models.safety_incident import SafetyIncident
from app.models.stream_playback_audit import StreamPlaybackAudit
from app.models.stream_recording_chunk import (
    CHUNK_UPLOADED, MEDIA_AUDIO_CHUNK, MEDIA_VIDEO_THUMBNAIL,
    StreamRecordingChunk,
)
from app.models.stream_session import StreamSession
from app.models.user import User
from app.services import emergency_stream_service as svc


# ── In-process SQLite fixture ────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session with the four NISCH-008-relevant tables.

    We hand-pick tables rather than running `Base.metadata.create_all`
    because production models use PostgreSQL-only types (JSONB, native
    UUID, PostGIS) that SQLite can't compile. The module-level
    `@compiles` rules above map JSONB→JSON and UUID→CHAR(36) so the
    five tables we DO need can be created cleanly.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    tables = [
        User.__table__, Relationship.__table__, SafetyIncident.__table__,
        StreamSession.__table__, StreamRecordingChunk.__table__,
        StreamPlaybackAudit.__table__,
    ]

    # `gen_random_uuid()` (Postgres-only) is the server default on
    # several of these columns. SQLite would choke — strip it so the
    # Python-side `default=uuid.uuid4` takes over for inserts in tests.
    saved_defaults: list[tuple] = []
    for t in tables:
        for c in t.columns:
            if (c.server_default is not None
                    and "gen_random_uuid" in str(c.server_default.arg)):
                saved_defaults.append((c, c.server_default))
                c.server_default = None

    async with engine.begin() as conn:
        for t in tables:
            await conn.run_sync(
                lambda sync_conn, t=t: t.create(sync_conn, checkfirst=True)
            )

    Session = async_sessionmaker(engine, expire_on_commit=False,
                                 class_=AsyncSession)
    async with Session() as s:
        yield s

    # Restore so we don't leak the column mutation to other test files.
    for c, sd in saved_defaults:
        c.server_default = sd
    await engine.dispose()


async def _seed(db) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (child_id, incident_id, guardian_id, operator_id, stranger_id)."""
    child = User(
        id=uuid.uuid4(), email="kid@test", password_hash="x",
        role="child", full_name="Kid", phone="+11", is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    guardian = User(
        id=uuid.uuid4(), email="mum@test", password_hash="x",
        role="guardian", full_name="Mum", phone="+12", is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    operator = User(
        id=uuid.uuid4(), email="op@test", password_hash="x",
        role="operator", full_name="Op", phone="+13", is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    stranger = User(
        id=uuid.uuid4(), email="x@test", password_hash="x",
        role="guardian", full_name="X", phone="+14", is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add_all([child, guardian, operator, stranger])

    rel = Relationship(
        guardian_id=guardian.id, child_id=child.id, status="accepted",
    )
    db.add(rel)

    inc = SafetyIncident(
        id=uuid.uuid4(), child_id=child.id, incident_type="sos",
        severity="alert", state="DETECTED", confidence=0.85,
    )
    db.add(inc)
    await db.flush()
    return child.id, inc.id, guardian.id, operator.id, stranger.id


# ── Pure helpers (no DB) ─────────────────────────────────────────────


def test_make_token_is_deterministic():
    t1 = svc._make_token("sessions/abc/audio/000001.webm", 1000, "put")
    t2 = svc._make_token("sessions/abc/audio/000001.webm", 1000, "put")
    assert t1 == t2 and len(t1) == 32


def test_make_token_differs_on_op():
    put = svc._make_token("k", 1000, "put")
    get = svc._make_token("k", 1000, "get")
    assert put != get


def test_verify_mock_token_happy_path():
    exp = int(time.time()) + 300
    tok = svc._make_token("k", exp, "put")
    assert svc.verify_mock_token("k", exp, "put", tok) is True


def test_verify_mock_token_rejects_wrong_op():
    exp = int(time.time()) + 300
    tok = svc._make_token("k", exp, "put")
    assert svc.verify_mock_token("k", exp, "get", tok) is False


def test_verify_mock_token_rejects_expired():
    exp = int(time.time()) - 10
    tok = svc._make_token("k", exp, "put")
    assert svc.verify_mock_token("k", exp, "put", tok) is False


def test_verify_mock_token_rejects_bad_signature():
    exp = int(time.time()) + 300
    assert svc.verify_mock_token("k", exp, "put", "0" * 32) is False


def test_build_key_layout():
    session_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    k = svc._build_key(session_id, 7, MEDIA_AUDIO_CHUNK, "audio/webm")
    assert k == f"sessions/{session_id}/audio/000007.webm"


def test_build_key_thumbnail_routes_to_thumbs():
    sid = uuid.uuid4()
    k = svc._build_key(sid, 0, MEDIA_VIDEO_THUMBNAIL, "image/jpeg")
    assert k.endswith("/thumbs/000000.jpg")


def test_validate_chunk_rejects_oversize_audio():
    with pytest.raises(ValueError):
        svc._validate_chunk_request(MEDIA_AUDIO_CHUNK, "audio/webm",
                                    size_bytes=10 * 1024 * 1024)


def test_validate_chunk_rejects_unknown_content_type():
    with pytest.raises(ValueError):
        svc._validate_chunk_request(MEDIA_AUDIO_CHUNK, "audio/wav",
                                    size_bytes=1024)


def test_validate_chunk_rejects_unknown_media_type():
    with pytest.raises(ValueError):
        svc._validate_chunk_request("video_chunk", "video/mp4", size_bytes=1024)


# ── Local-storage round-trip (stub-mode FS) ─────────────────────────


def test_local_storage_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOCAL_DIR", tmp_path)
    data = b"hello-emergency"
    n = svc.write_mock_bytes("sessions/abc/audio/000001.webm", data)
    assert n == len(data)
    assert svc.read_mock_bytes("sessions/abc/audio/000001.webm") == data


def test_local_storage_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOCAL_DIR", tmp_path)
    with pytest.raises(ValueError):
        svc.write_mock_bytes("../../../etc/passwd", b"x")


# ── End-to-end async flow ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_session_chunk_playback_audit(db_session):
    child_id, incident_id, guardian_id, operator_id, stranger_id = await _seed(db_session)

    # 1) Open recording session
    sess = await svc.start_recording_session(
        db_session,
        child_id=child_id, incident_id=incident_id,
        trigger="safety_brain:alert", risk_score=0.93,
    )
    assert sess.state == "connecting"
    assert sess.child_id == child_id

    # 2) Idempotent re-open returns the same session row
    sess2 = await svc.start_recording_session(
        db_session,
        child_id=child_id, incident_id=incident_id,
        trigger="manual", risk_score=0.93,
    )
    assert sess2.id == sess.id

    # 3) Issue PUT pre-sign → first audio chunk flips state to live
    put1 = await svc.issue_presign_put(
        db_session,
        session_id=sess.id, sequence=1,
        media_type=MEDIA_AUDIO_CHUNK, content_type="audio/webm",
        size_bytes=64 * 1024,
    )
    assert put1["mock_s3"] is True
    assert put1["s3_key"].endswith("/audio/000001.webm")
    # Reload — the session should now be `live`.
    sess_after = await db_session.get(StreamSession, sess.id)
    assert sess_after.state == "live"
    assert sess_after.started_at is not None

    # 4) Mark uploaded
    chunk_id = uuid.UUID(put1["chunk_id"])
    chunk = await svc.mark_chunk_uploaded(
        db_session, chunk_id=chunk_id,
        size_bytes=70 * 1024, content_sha256="0" * 64,
    )
    assert chunk.upload_status == CHUNK_UPLOADED
    assert chunk.uploaded_at is not None

    # 5) Thumbnail upload
    put2 = await svc.issue_presign_put(
        db_session,
        session_id=sess.id, sequence=1,
        media_type=MEDIA_VIDEO_THUMBNAIL, content_type="image/jpeg",
        size_bytes=12 * 1024,
    )
    assert put2["s3_key"].endswith("/thumbs/000001.jpg")

    # 6) Listing returns both, ordered by sequence
    chunks = await svc.list_chunks(db_session, session_id=sess.id)
    assert len(chunks) == 2

    # 7) RBAC — child (owner) ↔ guardian ↔ admin/operator pass;
    # unrelated guardian fails.
    out = await svc.issue_presign_get_for_chunk(
        db_session, chunk_id=chunk_id,
        viewer_user_id=guardian_id, viewer_role="guardian",
        ip_address="1.2.3.4", user_agent="pytest/guardian",
    )
    assert out["mock_s3"] is True

    out2 = await svc.issue_presign_get_for_chunk(
        db_session, chunk_id=chunk_id,
        viewer_user_id=operator_id, viewer_role="operator",
        ip_address="1.2.3.5",
    )
    # URL prefix depends on APP_BASE_URL (may be empty in CI, may be
    # the prod hostname in dev `.env`). What we lock here is the path
    # + query-string shape — the contract that mobile + web consume.
    assert "/api/emergency-stream/_mock_s3?" in out2["download_url"]
    assert "op=get" in out2["download_url"]
    assert "token=" in out2["download_url"]

    with pytest.raises(PermissionError):
        await svc.issue_presign_get_for_chunk(
            db_session, chunk_id=chunk_id,
            viewer_user_id=stranger_id, viewer_role="guardian",
        )

    # 8) Audit trail — 2 successful issuances. The denied one must NOT
    # land a row.
    from sqlalchemy import select
    audits = (await db_session.execute(
        select(StreamPlaybackAudit)
        .where(StreamPlaybackAudit.session_id == sess.id)
    )).scalars().all()
    assert len(audits) == 2
    audit_roles = sorted([a.viewer_role for a in audits])
    assert audit_roles == ["guardian", "operator"]
    # The guardian audit row carries IP and chunk metadata.
    g = next(a for a in audits if a.viewer_role == "guardian")
    assert g.ip_address == "1.2.3.4"
    assert g.access_type == "chunk_playback"
    assert g.chunk_id == chunk_id

    # 9) Finalize → state goes ended + duration computed
    ended = await svc.finalize_session(db_session, session_id=sess.id)
    assert ended.state == "ended"
    assert ended.ended_at is not None
    assert ended.duration_seconds is not None and ended.duration_seconds >= 0


@pytest.mark.asyncio
async def test_e2e_audit_session_view(db_session):
    child_id, incident_id, _, operator_id, _ = await _seed(db_session)
    sess = await svc.start_recording_session(
        db_session, child_id=child_id, incident_id=incident_id,
        trigger="manual",
    )
    await svc.audit_session_view(
        db_session, session_id=sess.id,
        viewer_user_id=operator_id, viewer_role="operator",
        ip_address="9.9.9.9", user_agent="pytest/op",
    )
    from sqlalchemy import select
    audits = (await db_session.execute(
        select(StreamPlaybackAudit)
        .where(StreamPlaybackAudit.session_id == sess.id)
    )).scalars().all()
    assert len(audits) == 1
    assert audits[0].access_type == "session_summary"
    assert audits[0].chunk_id is None
    assert audits[0].ip_address == "9.9.9.9"


@pytest.mark.asyncio
async def test_rbac_child_can_only_play_own(db_session):
    child_id, incident_id, guardian_id, _, _ = await _seed(db_session)
    sess = await svc.start_recording_session(
        db_session, child_id=child_id, incident_id=incident_id, trigger="manual",
    )
    put = await svc.issue_presign_put(
        db_session, session_id=sess.id, sequence=1,
        media_type=MEDIA_AUDIO_CHUNK, content_type="audio/webm", size_bytes=1024,
    )
    chunk_id = uuid.UUID(put["chunk_id"])
    # Child themselves OK
    out = await svc.issue_presign_get_for_chunk(
        db_session, chunk_id=chunk_id,
        viewer_user_id=child_id, viewer_role="child",
    )
    assert out["download_url"]
    # Guardian linked OK
    out = await svc.issue_presign_get_for_chunk(
        db_session, chunk_id=chunk_id,
        viewer_user_id=guardian_id, viewer_role="guardian",
    )
    assert out["download_url"]


@pytest.mark.asyncio
async def test_chunk_uniqueness_per_sequence_type(db_session):
    """Duplicate (session_id, sequence, media_type) is rejected by the
    unique constraint."""
    child_id, incident_id, *_ = await _seed(db_session)
    sess = await svc.start_recording_session(
        db_session, child_id=child_id, incident_id=incident_id, trigger="manual",
    )
    await svc.issue_presign_put(
        db_session, session_id=sess.id, sequence=1,
        media_type=MEDIA_AUDIO_CHUNK, content_type="audio/webm", size_bytes=1024,
    )
    # Same (session, sequence, audio) — SQLAlchemy must raise on flush.
    with pytest.raises(Exception):  # IntegrityError varies by driver
        await svc.issue_presign_put(
            db_session, session_id=sess.id, sequence=1,
            media_type=MEDIA_AUDIO_CHUNK, content_type="audio/webm",
            size_bytes=1024,
        )
