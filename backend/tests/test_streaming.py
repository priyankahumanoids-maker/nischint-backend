"""NISCH-008 — Live stream tests.

Live-PG. Each test self-cleans. Patterns mirror
`test_incident_feedback.py`. WebSocket signalling is exercised via
FastAPI's TestClient.websocket_connect.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.api.streaming import (
    AcceptBody, EndBody, FinalizeBody, InitiateBody, PresignBody,
    accept_stream, end_stream, finalize_recording, get_stream,
    initiate_stream, join_stream, presign_recording_upload,
)
from app.models.safety_incident import SafetyIncident
from app.models.stream_session import (
    STREAM_CONNECTING, STREAM_DECLINED, STREAM_ENDED, STREAM_LIVE,
    STREAM_OFFERED, StreamSession,
)
from app.services.incident_state_machine import (
    IncidentState, transition,
)
from app.services.stream_initiator import (
    NTS_TOKEN_TTL_S, OFFER_TIMEOUT_S, _FALLBACK_ICE_SERVERS,
    auto_decline_stale_offers, get_ice_servers,
    is_valid_stream_transition, offer_stream_for_incident,
)


def _db_url() -> str:
    from app.core.config import settings
    url = settings.database_url or ""
    if not url:
        pytest.skip("database_url not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        url = url.split("?")[0]
    return url


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine(_db_url(), poolclass=NullPool,
                              connect_args={"ssl": True})
    factory = async_sessionmaker(eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


# ── Seed helpers ────────────────────────────────────────────────────
async def _seed_user(s: AsyncSession, role: str = "guardian") -> uuid.UUID:
    uid = uuid.uuid4()
    await s.execute(text("""
        INSERT INTO users (id, email, full_name, role, password_hash,
                           preferred_channels, created_at)
        VALUES (:id, :email, :name, :role, 'x',
                '["push"]'::json, now())
    """), {"id": str(uid),
           "email": f"st+{uid}@nischint.test",
           "name": f"User {uid.hex[:8]}",
           "role": role})
    return uid


async def _seed_relationship(s, gid, cid):
    await s.execute(text("""
        INSERT INTO relationships (id, guardian_id, child_id, status, created_at)
        VALUES (:id, :gid, :cid, 'accepted', now())
    """), {"id": str(uuid.uuid4()),
           "gid": str(gid), "cid": str(cid)})


async def _seed_incident(s, child_id,
                          *, state="escalated") -> uuid.UUID:
    iid = uuid.uuid4()
    s.add(SafetyIncident(
        id=iid, child_id=child_id,
        incident_type="voice_distress", severity="high",
        state=state, confidence=0.85,
        sla_degraded_at_dispatch=False, escalation_level=1,
    ))
    await s.flush()
    return iid


async def _cleanup(s, **ids):
    for iid in ids.get("incident_ids", []):
        await s.execute(text(
            "DELETE FROM stream_sessions WHERE incident_id = :id"
        ), {"id": str(iid)})
        await s.execute(text(
            "DELETE FROM safety_incident_events WHERE incident_id = :id"
        ), {"id": str(iid)})
        await s.execute(text(
            "DELETE FROM safety_incidents WHERE id = :id"
        ), {"id": str(iid)})
    for uid in ids.get("user_ids", []):
        await s.execute(text(
            "DELETE FROM relationships WHERE guardian_id = :id OR child_id = :id"
        ), {"id": str(uid)})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(uid)})
    await s.commit()


def _u(uid, role):
    return type("U", (), {"id": uid, "role": role})()


# ════════════════════════════════════════════════════════════════════
# Pure-unit tests (no DB)
# ════════════════════════════════════════════════════════════════════

def test_state_transitions_allowed():
    """Locked transition contract."""
    assert is_valid_stream_transition(STREAM_OFFERED, STREAM_CONNECTING)
    assert is_valid_stream_transition(STREAM_OFFERED, STREAM_DECLINED)
    assert is_valid_stream_transition(STREAM_OFFERED, STREAM_ENDED)
    assert is_valid_stream_transition(STREAM_CONNECTING, STREAM_LIVE)
    assert is_valid_stream_transition(STREAM_LIVE, STREAM_ENDED)


def test_state_transitions_rejected():
    """Terminal + nonsense transitions all rejected."""
    assert not is_valid_stream_transition(STREAM_ENDED, STREAM_LIVE)
    assert not is_valid_stream_transition(STREAM_DECLINED, STREAM_OFFERED)
    assert not is_valid_stream_transition(STREAM_LIVE, STREAM_OFFERED)
    assert not is_valid_stream_transition(STREAM_OFFERED, STREAM_LIVE)


def test_get_ice_servers_falls_back_when_twilio_unreachable():
    """Hard failure mode: if Twilio raises, we MUST get STUN-only
    fallback so the signalling layer never blocks an emergency."""
    with patch("app.services.stream_initiator.os.environ.get") as mock_env:
        # Force missing creds path
        mock_env.return_value = ""
        servers = get_ice_servers()
    assert servers == _FALLBACK_ICE_SERVERS
    assert all("stun:" in s["urls"] for s in servers)


def test_constants_locked():
    assert NTS_TOKEN_TTL_S == 30
    assert OFFER_TIMEOUT_S == 30


# ════════════════════════════════════════════════════════════════════
# Auto-offer integration (the keystone)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_offer_stream_for_incident_creates_session(db):
    """Calling offer_stream_for_incident on an escalated incident
    creates a fresh OFFERED stream with ICE servers populated."""
    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()

    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()

    assert stream is not None
    assert stream.state == STREAM_OFFERED
    assert stream.stream_type == "audio"
    assert stream.child_id == child
    assert stream.ice_servers is not None
    assert "servers" in stream.ice_servers

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_offer_is_idempotent_per_active_stream(db):
    """A second offer for an incident with an already-active stream
    must REUSE the existing stream, not spawn a duplicate."""
    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        s1 = await offer_stream_for_incident(s, inc)
        await s.commit()

    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        s2 = await offer_stream_for_incident(s, inc)
        await s.commit()

    assert s1 is not None and s2 is not None
    assert s1.id == s2.id

    # Confirm only one row at the DB level too.
    async with db() as s:
        rows = (await s.execute(
            select(StreamSession).where(StreamSession.incident_id == iid)
        )).scalars().all()
    assert len(rows) == 1

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_escalated_state_machine_auto_offers(db):
    """End-to-end: when an incident transitions to ESCALATED via the
    state machine, a fresh OFFERED stream materialises automatically."""
    async with db() as s:
        child = await _seed_user(s, "user")
        # Seed in DETECTED so we can transition normally.
        iid = await _seed_incident(s, child, state="detected")
        await s.commit()

    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        await transition(s, inc, IncidentState.VALIDATING)
        await transition(s, inc, IncidentState.ESCALATED)
        await s.commit()

    async with db() as s:
        rows = (await s.execute(
            select(StreamSession).where(StreamSession.incident_id == iid)
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].state == STREAM_OFFERED
    assert rows[0].child_id == child

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


# ════════════════════════════════════════════════════════════════════
# REST endpoint auth + behaviour
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_initiate_blocks_unrelated_user(db):
    """/initiate is restricted to the incident's child + admin/operator."""
    async with db() as s:
        child = await _seed_user(s, "user")
        stranger = await _seed_user(s, "guardian")
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await initiate_stream(
                body=InitiateBody(incident_id=iid, stream_type="audio"),
                session=s, user=_u(stranger, "guardian"),
            )
        assert exc.value.status_code == 403

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child, stranger])


@pytest.mark.asyncio
async def test_initiate_invalid_stream_type_400(db):
    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await initiate_stream(
                body=InitiateBody(incident_id=iid, stream_type="hologram"),
                session=s, user=_u(child, "user"),
            )
        assert exc.value.status_code == 400
    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_join_unrelated_guardian_403(db):
    """A guardian with no Relationship row cannot join — even if
    they know the stream UUID."""
    async with db() as s:
        child = await _seed_user(s, "user")
        stranger = await _seed_user(s, "guardian")
        iid = await _seed_incident(s, child)
        await s.commit()

    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await join_stream(
                stream_id=sid, session=s, user=_u(stranger, "guardian"),
            )
        assert exc.value.status_code == 403

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child, stranger])


@pytest.mark.asyncio
async def test_join_linked_guardian_returns_fresh_ice(db):
    """A linked guardian gets fresh ICE servers + their join is tallied."""
    async with db() as s:
        child = await _seed_user(s, "user")
        guardian = await _seed_user(s, "guardian")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        out = await join_stream(
            stream_id=sid, session=s, user=_u(guardian, "guardian"),
        )
        await s.commit()

    assert out["stream_id"] == str(sid)
    assert out["ttl_seconds"] == NTS_TOKEN_TTL_S
    assert isinstance(out["ice_servers"], list)
    assert len(out["ice_servers"]) >= 1
    # Tally must have bumped to 1.
    async with db() as s:
        s_db = (await s.execute(
            select(StreamSession).where(StreamSession.id == sid)
        )).scalar_one()
    assert s_db.guardian_join_count == 1

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child, guardian])


@pytest.mark.asyncio
async def test_accept_only_by_child(db):
    """Only the incident's child may accept the offered stream."""
    async with db() as s:
        child = await _seed_user(s, "user")
        guardian = await _seed_user(s, "guardian")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    # Guardian can't accept.
    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await accept_stream(
                stream_id=sid, session=s, user=_u(guardian, "guardian"),
            )
        assert exc.value.status_code == 403

    # Child can.
    async with db() as s:
        out = await accept_stream(
            stream_id=sid, session=s, user=_u(child, "user"),
        )
        await s.commit()
    assert out["state"] == STREAM_CONNECTING

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child, guardian])


@pytest.mark.asyncio
async def test_end_persists_recording_url(db):
    """End-stream persists `recording_url` into the session row, ready
    for the forensic-replay UI to consume."""
    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        out = await end_stream(
            stream_id=sid,
            body=EndBody(
                recording_url="https://r.example.com/r/abc.m4a",
                duration_seconds=42,
            ),
            session=s, user=_u(child, "user"),
        )
        await s.commit()

    assert out["state"] == STREAM_ENDED
    assert out["recording_url"] == "https://r.example.com/r/abc.m4a"
    assert out["duration_seconds"] == 42

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_end_idempotent_on_already_ended(db):
    """Re-calling /end on an ended stream is a no-op (200, no error)."""
    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        await end_stream(
            stream_id=sid, body=EndBody(),
            session=s, user=_u(child, "user"),
        )
        await s.commit()
    # Second call — must not raise.
    async with db() as s:
        out = await end_stream(
            stream_id=sid, body=EndBody(),
            session=s, user=_u(child, "user"),
        )
        await s.commit()
    assert out["state"] == STREAM_ENDED

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_get_stream_envelope_for_linked_guardian(db):
    """GET /{id} returns the snapshot the mobile listener cold-starts on."""
    async with db() as s:
        child = await _seed_user(s, "user")
        guardian = await _seed_user(s, "guardian")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        out = await get_stream(
            stream_id=sid, session=s, user=_u(guardian, "guardian"),
        )
    assert out["stream_id"] == str(sid)
    assert out["state"] == STREAM_OFFERED
    assert out["child_id"] == str(child)
    assert "recording_url" in out  # field present even when null

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child, guardian])


# ════════════════════════════════════════════════════════════════════
# Sweeper
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_auto_decline_sweeps_stale_offers(db):
    """A stream offered > OFFER_TIMEOUT_S ago is auto-declined."""
    from datetime import datetime, timedelta, timezone

    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        # Force offered_at to be old.
        stream.offered_at = datetime.now(timezone.utc) - timedelta(
            seconds=OFFER_TIMEOUT_S + 5
        )
        await s.commit()
        sid = stream.id

    async with db() as s:
        count = await auto_decline_stale_offers(s)
        await s.commit()
    assert count >= 1

    async with db() as s:
        s_db = (await s.execute(
            select(StreamSession).where(StreamSession.id == sid)
        )).scalar_one()
    assert s_db.state == STREAM_DECLINED

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_auto_decline_skips_fresh_offers(db):
    """Fresh offers (within OFFER_TIMEOUT_S) must NOT be swept."""
    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        count = await auto_decline_stale_offers(s)
        await s.commit()
    # Fresh offer → either 0 or sweeps unrelated rows; ours must remain.
    async with db() as s:
        s_db = (await s.execute(
            select(StreamSession).where(StreamSession.id == sid)
        )).scalar_one()
    assert s_db.state == STREAM_OFFERED

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


# ════════════════════════════════════════════════════════════════════
# Recording uploader (presign + finalize)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_presign_503_when_bucket_not_configured(db, monkeypatch):
    """Without STREAM_RECORDING_BUCKET set, the endpoint must 503
    cleanly — never silently 'succeed' with a broken URL."""
    from app.api import streaming as streaming_mod

    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    # Force-empty the module-level bucket constant.
    monkeypatch.setattr(streaming_mod, "RECORDING_BUCKET", "", raising=False)

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await presign_recording_upload(
                stream_id=sid, body=PresignBody(),
                session=s, user=_u(child, "user"),
            )
        assert exc.value.status_code == 503

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_presign_blocks_non_child(db, monkeypatch):
    """Only the incident's child (or admin) may upload recordings —
    guardians don't record, that's the recorder side."""
    from app.api import streaming as streaming_mod
    monkeypatch.setattr(streaming_mod, "RECORDING_BUCKET", "test-bucket", raising=False)

    async with db() as s:
        child = await _seed_user(s, "user")
        guardian = await _seed_user(s, "guardian")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await presign_recording_upload(
                stream_id=sid, body=PresignBody(),
                session=s, user=_u(guardian, "guardian"),
            )
        assert exc.value.status_code == 403

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child, guardian])


@pytest.mark.asyncio
async def test_presign_invalid_content_type_400(db, monkeypatch):
    from app.api import streaming as streaming_mod
    monkeypatch.setattr(streaming_mod, "RECORDING_BUCKET", "test-bucket", raising=False)

    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await presign_recording_upload(
                stream_id=sid,
                body=PresignBody(content_type="image/png"),
                session=s, user=_u(child, "user"),
            )
        assert exc.value.status_code == 400

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_finalize_persists_recording_url(db, monkeypatch):
    """Successful finalize HEADs the object then writes a 24h
    pre-signed GET URL into stream_sessions.recording_url."""
    from app.api import streaming as streaming_mod
    monkeypatch.setattr(streaming_mod, "RECORDING_BUCKET", "test-bucket", raising=False)

    # Mock the S3 client so we don't actually hit AWS.
    class FakeClient:
        def head_object(self, Bucket, Key): return {"ContentLength": 1024}
        def generate_presigned_url(self, op, Params, ExpiresIn, HttpMethod):
            return f"https://s3.test/{Params['Bucket']}/{Params['Key']}?sig=fake&exp={ExpiresIn}"
    monkeypatch.setattr(streaming_mod, "_s3_client", lambda: FakeClient())

    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        out = await finalize_recording(
            stream_id=sid,
            body=FinalizeBody(
                bucket="test-bucket",
                key=f"streams/{iid}/{sid}.m4a",
                duration_seconds=42,
            ),
            session=s, user=_u(child, "user"),
        )
        await s.commit()

    assert out["recording_url"].startswith("https://s3.test/test-bucket/")
    assert out["duration_seconds"] == 42

    async with db() as s:
        s_db = (await s.execute(
            select(StreamSession).where(StreamSession.id == sid)
        )).scalar_one()
    assert s_db.recording_url == out["recording_url"]
    assert s_db.duration_seconds == 42

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_finalize_404_when_object_missing(db, monkeypatch):
    """If HEAD object fails (upload truly didn't land), finalize must
    404 — never write a recording_url that points to nothing."""
    from app.api import streaming as streaming_mod
    monkeypatch.setattr(streaming_mod, "RECORDING_BUCKET", "test-bucket", raising=False)

    class FakeClient:
        def head_object(self, **kw): raise Exception("404 Not Found")
        def generate_presigned_url(self, *a, **kw): return "x"
    monkeypatch.setattr(streaming_mod, "_s3_client", lambda: FakeClient())

    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await finalize_recording(
                stream_id=sid,
                body=FinalizeBody(
                    bucket="test-bucket",
                    key=f"streams/{iid}/{sid}.m4a",
                ),
                session=s, user=_u(child, "user"),
            )
        assert exc.value.status_code == 404

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])


@pytest.mark.asyncio
async def test_finalize_bucket_mismatch_400(db, monkeypatch):
    """A `bucket` in the request body that doesn't match
    STREAM_RECORDING_BUCKET → 400. Defends against a client uploading
    to an attacker-controlled bucket and tricking us into recording
    that URL into our forensic timeline."""
    from app.api import streaming as streaming_mod
    monkeypatch.setattr(streaming_mod, "RECORDING_BUCKET", "real-bucket", raising=False)

    async with db() as s:
        child = await _seed_user(s, "user")
        iid = await _seed_incident(s, child)
        await s.commit()
    async with db() as s:
        inc = (await s.execute(
            select(SafetyIncident).where(SafetyIncident.id == iid)
        )).scalar_one()
        stream = await offer_stream_for_incident(s, inc)
        await s.commit()
        sid = stream.id

    async with db() as s:
        with pytest.raises(HTTPException) as exc:
            await finalize_recording(
                stream_id=sid,
                body=FinalizeBody(
                    bucket="evil-bucket",   # not RECORDING_BUCKET
                    key=f"streams/{iid}/{sid}.m4a",
                ),
                session=s, user=_u(child, "user"),
            )
        assert exc.value.status_code == 400

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])

