"""NISCH-008 Phase C — Scheduler integration tests.

Verifies the stream-stale-offer sweeper is registered + the underlying
`auto_decline_stale_offers` behaves correctly when run by the
scheduler tick wrapper.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.models.safety_incident import SafetyIncident
from app.models.stream_session import (
    STREAM_DECLINED, STREAM_OFFERED, StreamSession,
)
from app.services.safety_incident_scheduler import (
    _stream_offer_sweep_tick, start_safety_incident_scheduler,
    stop_safety_incident_scheduler,
)
from app.services.stream_initiator import OFFER_TIMEOUT_S


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


async def _seed_user(s: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    await s.execute(text("""
        INSERT INTO users (id, email, full_name, role, password_hash,
                           preferred_channels, created_at)
        VALUES (:id, :email, :name, 'user', 'x',
                '["push"]'::json, now())
    """), {"id": str(uid),
           "email": f"sw+{uid}@nischint.test",
           "name": f"User {uid.hex[:8]}"})
    return uid


async def _seed_incident(s: AsyncSession, child_id: uuid.UUID) -> uuid.UUID:
    iid = uuid.uuid4()
    s.add(SafetyIncident(
        id=iid, child_id=child_id,
        incident_type="voice_distress", severity="high",
        state="escalated", confidence=0.85,
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
        await s.execute(text("DELETE FROM users WHERE id = :id"),
                        {"id": str(uid)})
    await s.commit()


@pytest.mark.asyncio
async def test_scheduler_registers_stream_sweep_job():
    """The scheduler's startup must register a job with id
    `stream_stale_offer_sweep`. Locks the wiring contract.

    Async test because AsyncIOScheduler.start() requires a running
    event loop (which pytest-asyncio provides per-test)."""
    try:
        start_safety_incident_scheduler()
        from app.services.safety_incident_scheduler import _scheduler
        assert _scheduler is not None
        ids = {j.id for j in _scheduler.get_jobs()}
        assert "stream_stale_offer_sweep" in ids, (
            f"missing stream_stale_offer_sweep — registered: {ids}"
        )
        # Sanity: the other two safety jobs are also still there.
        assert "safety_incident_lifecycle" in ids
        assert "ttfa_threshold_check" in ids
    finally:
        stop_safety_incident_scheduler()


@pytest.mark.asyncio
async def test_stream_sweep_tick_declines_stale_offer(db):
    """The scheduler tick wrapper (full path: opens session, sweeps,
    commits) must flip a stale offered row to declined."""
    async with db() as s:
        child = await _seed_user(s)
        iid = await _seed_incident(s, child)
        sid = uuid.uuid4()
        s.add(StreamSession(
            id=sid, incident_id=iid, child_id=child,
            state=STREAM_OFFERED, stream_type="audio",
            offered_at=datetime.now(timezone.utc) - timedelta(
                seconds=OFFER_TIMEOUT_S + 5
            ),
        ))
        await s.commit()

    # Run the scheduler's tick wrapper directly — this is what
    # APScheduler will fire every 10s in production.
    await _stream_offer_sweep_tick()

    async with db() as s:
        s_db = (await s.execute(
            select(StreamSession).where(StreamSession.id == sid)
        )).scalar_one()
    assert s_db.state == STREAM_DECLINED
    assert s_db.ended_at is not None

    async with db() as s:
        await _cleanup(s, incident_ids=[iid], user_ids=[child])
