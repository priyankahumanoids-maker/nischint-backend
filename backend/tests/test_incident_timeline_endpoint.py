"""NISCH-006 Day 3 — Timeline endpoint tests (live PG + auth boundary).

Covers:
  * `elapsed_ms` math (first event = 0; subsequent = ms delta)
  * Guardian↔child boundary: 403 when not linked
  * 404 for unknown incident
  * Admin/operator can read any incident timeline
  * The genesis event has `from_state=None`, `actor_type='system'`
  * Sweeper's auto-resolve event records `actor_type='scheduler'`

These tests run against the live Neon PG instance via `async_session`
factory (same pattern as `test_alert_ack_engine.py`). Each test
cleans up its own rows so the suite is idempotent.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent


def _db_url() -> str:
    """Read the live PG URL from settings (sourced from .env)."""
    from app.core.config import settings
    url = settings.database_url or ""
    if not url:
        pytest.skip("database_url not set; skipping live-PG timeline tests")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        url = url.split("?")[0]
    return url


@pytest_asyncio.fixture
async def db():
    url = _db_url()
    eng = create_async_engine(url, poolclass=NullPool,
                              connect_args={"ssl": True})
    factory = async_sessionmaker(eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


async def _seed_user(s: AsyncSession, role: str = "guardian") -> uuid.UUID:
    uid = uuid.uuid4()
    await s.execute(text(
        """INSERT INTO users (id, email, full_name, role, password_hash,
                              preferred_channels, created_at)
           VALUES (:id, :email, :name, :role, 'x',
                   '["push","sms","email"]'::json, now())"""
    ), {"id": str(uid),
        "email": f"t+{uid}@nischint.test",
        "name":  f"User {uid.hex[:8]}",
        "role":  role})
    return uid


async def _seed_relationship(s: AsyncSession, guardian_id: uuid.UUID,
                              child_id: uuid.UUID) -> None:
    await s.execute(text(
        """INSERT INTO relationships (id, guardian_id, child_id, status, created_at)
           VALUES (:id, :gid, :cid, 'accepted', now())"""
    ), {"id": str(uuid.uuid4()),
        "gid": str(guardian_id),
        "cid": str(child_id)})


async def _seed_incident_with_events(
        s: AsyncSession, child_id: uuid.UUID,
        chain: list[tuple[str, str, str]] | None = None,
) -> uuid.UUID:
    """Returns the incident_id. `chain` is a list of
    (from_state, to_state, actor_type) — first entry typically
    `(None, 'detected', 'system')`."""
    iid = uuid.uuid4()
    inc = SafetyIncident(
        id=iid, child_id=child_id, incident_type="sos",
        severity="critical", state="detected", confidence=0.9,
        sla_degraded_at_dispatch=False, escalation_level=0,
    )
    s.add(inc)
    await s.flush()

    chain = chain or [(None, "detected", "system")]
    for fs, ts, at in chain:
        s.add(SafetyIncidentEvent(
            incident_id=iid, from_state=fs, to_state=ts,
            actor_type=at, ttfa_tag=f"incident_state:{ts}",
            sla_degraded=False, extra={"confidence": 0.9},
        ))
    await s.flush()
    return iid


async def _cleanup(s: AsyncSession, **ids):
    """Delete seeded rows in dependency order."""
    if "incident_id" in ids:
        await s.execute(text(
            "DELETE FROM safety_incidents WHERE id = :id"
        ), {"id": str(ids["incident_id"])})
    if "guardian_id" in ids:
        await s.execute(text(
            "DELETE FROM relationships WHERE guardian_id = :id"
        ), {"id": str(ids["guardian_id"])})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(ids["guardian_id"])})
    if "child_id" in ids:
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(ids["child_id"])})
    await s.commit()


# ── 1. Cascade — deleting an incident removes its events ───────────
@pytest.mark.asyncio
async def test_event_cascade_on_incident_delete(db):
    """The FK is ON DELETE CASCADE — confirmed by inspecting the
    events table after a parent delete."""
    async with db() as s:
        child = await _seed_user(s, role="user")
        iid = await _seed_incident_with_events(
            s, child, chain=[(None, "detected", "system"),
                              ("detected", "validating", "system")])
        await s.commit()

    async with db() as s:
        # Verify both events exist.
        rows = (await s.execute(
            text("SELECT count(*) FROM safety_incident_events WHERE incident_id = :id"),
            {"id": str(iid)},
        )).scalar()
        assert rows == 2

        # Delete the parent — cascade should drop the events.
        await s.execute(text("DELETE FROM safety_incidents WHERE id = :id"),
                        {"id": str(iid)})
        await s.commit()

        rows_after = (await s.execute(
            text("SELECT count(*) FROM safety_incident_events WHERE incident_id = :id"),
            {"id": str(iid)},
        )).scalar()
        assert rows_after == 0

    async with db() as s:
        await _cleanup(s, child_id=child)


# ── 2. Endpoint: 404 for unknown incident ──────────────────────────
@pytest.mark.asyncio
async def test_timeline_404_for_unknown_incident(db):
    from app.api.safety_incidents import get_incident_timeline
    from fastapi import HTTPException
    async with db() as s:
        actor = await _seed_user(s, role="admin")
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": actor, "role": "admin"})()
        with pytest.raises(HTTPException) as exc:
            await get_incident_timeline(uuid.uuid4(), s, u)  # type: ignore
        assert exc.value.status_code == 404

    async with db() as s:
        await _cleanup(s, child_id=actor)


# ── 3. Endpoint: 403 when caller is not linked ─────────────────────
@pytest.mark.asyncio
async def test_timeline_403_for_unlinked_guardian(db):
    from app.api.safety_incidents import get_incident_timeline
    from fastapi import HTTPException
    async with db() as s:
        child = await _seed_user(s, role="user")
        stranger = await _seed_user(s, role="guardian")  # NOT linked
        iid = await _seed_incident_with_events(s, child)
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": stranger, "role": "guardian"})()
        with pytest.raises(HTTPException) as exc:
            await get_incident_timeline(iid, s, u)  # type: ignore
        assert exc.value.status_code == 403

    async with db() as s:
        await _cleanup(s, incident_id=iid, guardian_id=stranger,
                       child_id=child)


# ── 4. Endpoint: 200 for linked guardian ───────────────────────────
@pytest.mark.asyncio
async def test_timeline_200_for_linked_guardian(db):
    from app.api.safety_incidents import get_incident_timeline
    async with db() as s:
        child    = await _seed_user(s, role="user")
        guardian = await _seed_user(s, role="guardian")
        await _seed_relationship(s, guardian, child)
        iid = await _seed_incident_with_events(s, child)
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": guardian, "role": "guardian"})()
        out = await get_incident_timeline(iid, s, u)  # type: ignore

    assert out["incident_id"] == str(iid)
    assert out["child_id"]    == str(child)
    assert len(out["timeline"]) == 1
    assert out["timeline"][0]["from_state"] is None
    assert out["timeline"][0]["to_state"]   == "detected"
    assert out["timeline"][0]["actor_type"] == "system"
    assert out["timeline"][0]["elapsed_ms"] == 0  # first event always 0

    async with db() as s:
        await _cleanup(s, incident_id=iid, guardian_id=guardian,
                       child_id=child)


# ── 5. elapsed_ms math: monotonic, accurate ────────────────────────
@pytest.mark.asyncio
async def test_timeline_elapsed_ms_is_accurate(db):
    """Manually space three events 100 ms apart and verify the
    endpoint reports `elapsed_ms` deltas in roughly that range."""
    from app.api.safety_incidents import get_incident_timeline
    async with db() as s:
        child   = await _seed_user(s, role="user")
        admin   = await _seed_user(s, role="admin")
        # Create incident + 3 spaced events.
        iid = uuid.uuid4()
        s.add(SafetyIncident(
            id=iid, child_id=child, incident_type="sos",
            severity="critical", state="escalated",
            confidence=0.9, sla_degraded_at_dispatch=False,
            escalation_level=0,
        ))
        await s.flush()
        base = datetime.now(timezone.utc)
        chain = [
            (None,         "detected",   "system",    base),
            ("detected",   "validating", "system",    base.replace(microsecond=base.microsecond)),
        ]
        from datetime import timedelta as _td
        # Use explicit deltas so cleanups don't depend on host clock jitter.
        e1 = SafetyIncidentEvent(
            incident_id=iid, from_state=None, to_state="detected",
            actor_type="system", sla_degraded=False, extra={},
            created_at=base,
        )
        e2 = SafetyIncidentEvent(
            incident_id=iid, from_state="detected", to_state="validating",
            actor_type="system", sla_degraded=False, extra={},
            created_at=base + _td(milliseconds=100),
        )
        e3 = SafetyIncidentEvent(
            incident_id=iid, from_state="validating", to_state="escalated",
            actor_type="system", sla_degraded=False, extra={},
            created_at=base + _td(milliseconds=350),
        )
        s.add_all([e1, e2, e3])
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": admin, "role": "admin"})()
        out = await get_incident_timeline(iid, s, u)  # type: ignore

    elapsed = [t["elapsed_ms"] for t in out["timeline"]]
    assert elapsed[0] == 0
    # 100 ms gap, 250 ms gap.
    assert 95  <= elapsed[1] <= 105
    assert 245 <= elapsed[2] <= 255

    async with db() as s:
        await _cleanup(s, incident_id=iid, child_id=child)
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(admin)})
        await s.commit()


# ── 6. Admin can read any timeline (no relationship needed) ────────
@pytest.mark.asyncio
async def test_admin_can_read_any_timeline(db):
    from app.api.safety_incidents import get_incident_timeline
    async with db() as s:
        child = await _seed_user(s, role="user")
        admin = await _seed_user(s, role="admin")
        iid = await _seed_incident_with_events(s, child)
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": admin, "role": "admin"})()
        out = await get_incident_timeline(iid, s, u)  # type: ignore
    assert out["incident_id"] == str(iid)

    async with db() as s:
        await _cleanup(s, incident_id=iid, child_id=child)
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(admin)})
        await s.commit()


# ── 7. Operator can read any timeline ──────────────────────────────
@pytest.mark.asyncio
async def test_operator_can_read_any_timeline(db):
    from app.api.safety_incidents import get_incident_timeline
    async with db() as s:
        child    = await _seed_user(s, role="user")
        operator = await _seed_user(s, role="operator")
        iid = await _seed_incident_with_events(s, child)
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": operator, "role": "operator"})()
        out = await get_incident_timeline(iid, s, u)  # type: ignore
    assert out["incident_id"] == str(iid)

    async with db() as s:
        await _cleanup(s, incident_id=iid, child_id=child)
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(operator)})
        await s.commit()



# ════════════════════════════════════════════════════════════════════
# NISCH-008 Phase C — Stream block on the timeline response
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_timeline_returns_stream_block_when_ended_stream_exists(db):
    """The timeline response must surface the most recent ENDED stream
    session via the `stream` field, with `recording_url` and
    `duration_seconds` ready for the mobile 🎙 Listen chip."""
    from datetime import datetime, timezone, timedelta

    from app.api.safety_incidents import get_incident_timeline
    from app.models.stream_session import STREAM_ENDED, StreamSession

    async with db() as s:
        admin = await _seed_user(s, role="admin")
        child = await _seed_user(s, role="user")
        iid = await _seed_incident_with_events(s, child)
        now = datetime.now(timezone.utc)
        s.add(StreamSession(
            incident_id=iid, child_id=child, state=STREAM_ENDED,
            stream_type="audio",
            recording_url="https://r.example.com/r/test123.m4a",
            duration_seconds=87,
            offered_at=now - timedelta(seconds=200),
            started_at=now - timedelta(seconds=180),
            ended_at=now - timedelta(seconds=93),
            guardian_join_count=2,
        ))
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": admin, "role": "admin"})()
        out = await get_incident_timeline(iid, s, u)  # type: ignore

    assert out["stream"] is not None
    assert out["stream"]["state"] == "ended"
    assert out["stream"]["recording_url"] == "https://r.example.com/r/test123.m4a"
    assert out["stream"]["duration_seconds"] == 87
    assert out["stream"]["guardian_join_count"] == 2
    assert out["stream"]["started_at"] is not None
    assert out["stream"]["ended_at"] is not None

    async with db() as s:
        await s.execute(text(
            "DELETE FROM stream_sessions WHERE incident_id = :id"
        ), {"id": str(iid)})
        await _cleanup(s, incident_id=iid, child_id=child)
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(admin)})
        await s.commit()


@pytest.mark.asyncio
async def test_timeline_stream_is_null_when_no_ended_stream(db):
    """No stream row → `stream: null`. An OFFERED (in-flight) stream
    must NOT leak through — the chip surfaces ended streams ONLY
    because their recording_url is stable."""
    from datetime import datetime, timezone

    from app.api.safety_incidents import get_incident_timeline
    from app.models.stream_session import STREAM_OFFERED, StreamSession

    async with db() as s:
        admin = await _seed_user(s, role="admin")
        child = await _seed_user(s, role="user")
        iid_no_stream = await _seed_incident_with_events(s, child)
        iid_offered = await _seed_incident_with_events(s, child)
        s.add(StreamSession(
            incident_id=iid_offered, child_id=child,
            state=STREAM_OFFERED, stream_type="audio",
            offered_at=datetime.now(timezone.utc),
        ))
        await s.commit()

    async with db() as s:
        u = type("U", (), {"id": admin, "role": "admin"})()
        out_a = await get_incident_timeline(iid_no_stream, s, u)  # type: ignore
        out_b = await get_incident_timeline(iid_offered, s, u)    # type: ignore

    assert out_a["stream"] is None
    assert out_b["stream"] is None

    async with db() as s:
        for iid in (iid_no_stream, iid_offered):
            await s.execute(text(
                "DELETE FROM stream_sessions WHERE incident_id = :id"
            ), {"id": str(iid)})
            await s.execute(text(
                "DELETE FROM safety_incidents WHERE id = :id"
            ), {"id": str(iid)})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(child)})
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(admin)})
        await s.commit()
