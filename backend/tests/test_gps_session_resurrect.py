"""Regression tests for safety-critical GPS-on-expired-session behavior.

These tests lock the contract that, in a safety system, a fresh GPS
ping MUST resurrect an auto-expired session. The only states that
permanently reject a ping are user-intent terminal states
(`ended`, `completed`).
"""
import asyncio
import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.guardian import GuardianSession
from app.models.user import User
from app.services.guardian_mode_engine import update_location


# Each test gets its own engine on NullPool so asyncpg connections
# don't leak across pytest's per-test event loops.
def _new_session_factory():
    url = settings.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        url = url.split("?")[0]
    eng = create_async_engine(url, poolclass=NullPool, connect_args={"ssl": True})
    return eng, async_sessionmaker(eng, expire_on_commit=False)


@pytest_asyncio.fixture
async def db():
    engine, factory = _new_session_factory()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_user(s) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"gpsresurrect+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="GPS Resurrect Test",
        password_hash="x",
        role="child",
    )
    s.add(u)
    await s.flush()
    return u


async def _seed_session(s, user_id, status: str) -> GuardianSession:
    now = datetime.now(timezone.utc)
    gs = GuardianSession(
        id=uuid.uuid4(),
        user_id=user_id,
        status=status,
        started_at=now - timedelta(minutes=30),
        previous_update_at=now - timedelta(minutes=15),
        risk_level="LOW",
        risk_score=0,
        zone_name="default",
        current_location={"lat": 12.97, "lng": 77.59},
        ended_at=now if status in ("expired", "ended", "completed") else None,
    )
    s.add(gs)
    await s.flush()
    return gs


@pytest.mark.asyncio
async def test_expired_session_resurrects_on_ping(db):
    """`expired` is an auto-marker — the next ping must resurrect."""
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, "expired")
        sid = str(gs.id)
        await s.commit()

    async with db() as s:
        result = await update_location(s, sid, 12.971, 77.591)
        await s.commit()
    assert "error" not in result, f"GPS ping was rejected on `expired`: {result}"

    async with db() as s:
        gs = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
        )).scalar_one()
    assert gs.status == "active", f"Expected resurrected to active, got {gs.status}"
    age = (datetime.now(timezone.utc) - gs.previous_update_at).total_seconds()
    assert age < 30.0, f"previous_update_at not renewed (age={age}s)"
    assert gs.ended_at is None, "ended_at must be cleared on resurrection"


@pytest.mark.asyncio
async def test_stale_session_resurrects_on_ping(db):
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, "stale")
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.971, 77.591)
        await s.commit()
    assert "error" not in result, f"Ping rejected on `stale`: {result}"
    async with db() as s:
        gs = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
        )).scalar_one()
    assert gs.status == "active"


@pytest.mark.asyncio
async def test_ended_session_still_rejects(db):
    """`ended` is user-intent terminal — resurrection would be wrong."""
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, "ended")
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.971, 77.591)
    assert "error" in result, "User-ended sessions must NOT auto-resurrect"
    assert "ended" in result["error"]


@pytest.mark.asyncio
async def test_completed_session_still_rejects(db):
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, "completed")
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.971, 77.591)
    assert "error" in result, "Completed sessions must NOT auto-resurrect"
    assert "completed" in result["error"]


@pytest.mark.asyncio
async def test_active_session_extends_ttl_on_ping(db):
    """Each accepted ping bumps `previous_update_at` so the sweeper
    can't re-expire the session within the next window."""
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, "active")
        gs.previous_update_at = datetime.now(timezone.utc) - timedelta(minutes=4, seconds=30)
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        await update_location(s, sid, 12.971, 77.591)
        await s.commit()
    async with db() as s:
        gs = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
        )).scalar_one()
    age = (datetime.now(timezone.utc) - gs.previous_update_at).total_seconds()
    assert age < 30.0, f"TTL not renewed on active ping (age={age}s)"
    assert gs.status == "active"
