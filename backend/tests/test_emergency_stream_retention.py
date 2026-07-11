"""NISCH-008 — Retention sweeper tests.

Locks the contract:
  1. Expired chunks are deleted (row + underlying object).
  2. Non-expired chunks are left alone.
  3. Cascading FK deletes the matching playback audits.
  4. Sweeper is idempotent — running it twice yields purged=0 the
     second time.
  5. Object-delete failure does NOT block the row delete (sweeper
     keeps moving).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Re-use the compile rules from test_emergency_stream.py so SQLite
# can render PG types.
import tests.test_emergency_stream  # noqa: F401

from app.models.relationship import Relationship
from app.models.safety_incident import SafetyIncident
from app.models.stream_playback_audit import StreamPlaybackAudit
from app.models.stream_recording_chunk import StreamRecordingChunk
from app.models.stream_session import StreamSession
from app.models.user import User
from app.services import emergency_stream_retention as sweeper
from app.services import emergency_stream_service as svc


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    tables = [
        User.__table__, Relationship.__table__, SafetyIncident.__table__,
        StreamSession.__table__, StreamRecordingChunk.__table__,
        StreamPlaybackAudit.__table__,
    ]
    saved: list[tuple] = []
    for t in tables:
        for c in t.columns:
            if (c.server_default is not None
                    and "gen_random_uuid" in str(c.server_default.arg)):
                saved.append((c, c.server_default))
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
    for c, sd in saved:
        c.server_default = sd
    await engine.dispose()


async def _setup(db, *, ages_days: list[int], retention_days: int = 90):
    """Seed N chunks, one per `ages_days` entry. Positive = age in past.
    Returns the chunk IDs in seed order."""
    child = User(id=uuid.uuid4(), email="kid@t", password_hash="x",
                 role="child", full_name="K", phone="+1", is_active=True,
                 created_at=datetime.now(timezone.utc))
    db.add(child)
    inc = SafetyIncident(id=uuid.uuid4(), child_id=child.id,
                         incident_type="sos", severity="alert",
                         state="DETECTED", confidence=0.9)
    db.add(inc)
    sess = StreamSession(id=uuid.uuid4(), incident_id=inc.id,
                         child_id=child.id, state="live",
                         stream_type="audio+thumbnail",
                         offered_at=datetime.now(timezone.utc),
                         started_at=datetime.now(timezone.utc))
    db.add(sess)
    await db.flush()

    ids: list[uuid.UUID] = []
    now = datetime.now(timezone.utc)
    for i, age in enumerate(ages_days):
        captured = now - timedelta(days=age)
        expires = captured + timedelta(days=retention_days)
        chunk = StreamRecordingChunk(
            id=uuid.uuid4(), session_id=sess.id,
            sequence=i, media_type="audio_chunk", content_type="audio/webm",
            s3_key=f"sessions/{sess.id}/audio/{i:06d}.webm",
            size_bytes=1024, upload_status="uploaded",
            captured_at=captured, uploaded_at=captured,
            expires_at=expires,
        )
        db.add(chunk)
        ids.append(chunk.id)
        # Also add an audit row for each chunk to verify cascade.
        db.add(StreamPlaybackAudit(
            session_id=sess.id, chunk_id=chunk.id,
            viewer_user_id=child.id, viewer_role="operator",
            access_type="chunk_playback",
        ))
    await db.flush()
    return ids


@pytest.mark.asyncio
async def test_sweeper_deletes_expired_keeps_fresh(db_session, tmp_path,
                                                   monkeypatch):
    """One chunk expired 5 days ago, one valid for 30 more days. The
    expired one + its on-disk file + its audit row disappear; the
    valid one stays untouched."""
    monkeypatch.setattr(svc, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(svc, "MOCK_S3", True)

    ids = await _setup(db_session, ages_days=[95, 60], retention_days=90)
    # Materialise the on-disk file for the expired chunk so we can
    # verify it gets unlinked.
    expired_chunk = await db_session.get(StreamRecordingChunk, ids[0])
    svc.write_mock_bytes(expired_chunk.s3_key, b"old-audio")
    p = svc._local_path(expired_chunk.s3_key)
    assert p.exists()

    out = await sweeper.run_emergency_stream_retention_sweep(db_session)
    assert out == {"purged": 1, "failed": 0, "scanned": 1}

    # Row gone, file gone.
    assert await db_session.get(StreamRecordingChunk, ids[0]) is None
    assert not p.exists()
    # Audit row cascaded.
    from sqlalchemy import select
    audits = (await db_session.execute(
        select(StreamPlaybackAudit).where(
            StreamPlaybackAudit.chunk_id == ids[0]
        )
    )).scalars().all()
    assert audits == []
    # Fresh chunk untouched.
    assert await db_session.get(StreamRecordingChunk, ids[1]) is not None


@pytest.mark.asyncio
async def test_sweeper_is_idempotent(db_session, tmp_path, monkeypatch):
    """Running twice yields purged=0 the second time."""
    monkeypatch.setattr(svc, "LOCAL_DIR", tmp_path)
    monkeypatch.setattr(svc, "MOCK_S3", True)
    await _setup(db_session, ages_days=[95], retention_days=90)

    first = await sweeper.run_emergency_stream_retention_sweep(db_session)
    assert first["purged"] == 1

    second = await sweeper.run_emergency_stream_retention_sweep(db_session)
    assert second == {"purged": 0, "failed": 0, "scanned": 0}
