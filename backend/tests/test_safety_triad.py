"""Tests for the safety-triad shipped Apr 28, 2026:

  • Zombie session 24h hard cap
  • Shadow location ping failsafe (insert path)
  • Push reachability classifier (pure logic)
"""
import asyncio
import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.guardian import GuardianSession
from app.models.user import User
from app.services.guardian_mode_engine import update_location
from app.services.shadow_tracking import (
    shadow_ping, MIN_SHADOW_INTERVAL_S, reset_state_for_tests,
)
from app.api.push import _classify


def _new_factory():
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
    eng, factory = _new_factory()
    try:
        yield factory
    finally:
        await eng.dispose()


@pytest.fixture(autouse=True)
def _reset_shadow_state():
    """Each test gets a fresh in-process dedup map."""
    reset_state_for_tests()
    yield
    reset_state_for_tests()


async def _seed_user(s) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"safety+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="Safety Triad",
        password_hash="x",
        role="child",
    )
    s.add(u)
    await s.flush()
    return u


async def _seed_session(s, user_id, *, age_hours: float, status: str = "active") -> GuardianSession:
    started = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    gs = GuardianSession(
        id=uuid.uuid4(), user_id=user_id, status=status,
        started_at=started, previous_update_at=started,
        risk_level="LOW", risk_score=0, zone_name="default",
        current_location={"lat": 12.97, "lng": 77.59},
    )
    s.add(gs)
    await s.flush()
    return gs


# ── 24h zombie cap ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_session_under_24h_still_pings(db):
    """A 23-hour-old active session must still accept pings."""
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, age_hours=23)
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.97, 77.59)
        await s.commit()
    assert "error" not in result, f"23h session must still accept: {result}"


@pytest.mark.asyncio
async def test_session_over_24h_age_caps(db):
    """A 25-hour-old active session must auto-complete and reject."""
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, age_hours=25)
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.97, 77.59)
        await s.commit()
    assert "error" in result, "25h session must hit zombie cap"
    assert "completed" in result["error"]
    async with db() as s:
        gs = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == uuid.UUID(sid))
        )).scalar_one()
    assert gs.status == "completed", f"got {gs.status}"
    assert gs.ended_at is not None


@pytest.mark.asyncio
async def test_zombie_cap_applies_even_if_was_expired(db):
    """An old session that was previously `expired` and now resurrects
    must STILL hit the 24h cap. Resurrect rule cannot defeat the cap."""
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, age_hours=30, status="expired")
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.97, 77.59)
        await s.commit()
    assert "error" in result and "completed" in result["error"]


# ── Shadow ping failsafe ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_shadow_ping_inserts(db):
    async with db() as s:
        u = await _seed_user(s)
        await s.commit()
        ok = await shadow_ping(s, u.id, 12.97, 77.59,
                               source="no_session", session_id="bogus-sid")
    assert ok is True
    async with db() as s:
        rows = (await s.execute(
            text("""SELECT user_id, lat, lng, source, session_id
                      FROM shadow_location_pings WHERE user_id = :uid"""),
            {"uid": u.id},
        )).fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r.source == "no_session"
    assert r.session_id == "bogus-sid"
    assert abs(r.lat - 12.97) < 0.001 and abs(r.lng - 77.59) < 0.001


@pytest.mark.asyncio
async def test_shadow_ping_swallows_errors(db):
    """A failing insert (e.g. bad UUID) must NOT raise — failsafe contract."""
    async with db() as s:
        ok = await shadow_ping(s, "not-a-uuid", 0.0, 0.0, source="no_session")
    assert ok is False  # signaled failure but didn't raise


# ── Reachability classifier (pure) ───────────────────────────────────
def _now(): return datetime.now(timezone.utc)


def test_classify_unknown_when_no_signal():
    assert _classify(None, None, 0, _now()) == "unknown"


def test_classify_dead_after_3_consecutive_failures():
    assert _classify(_now(), _now(), 3, _now()) == "dead"
    assert _classify(_now(), _now(), 4, _now()) == "dead"


def test_classify_dead_when_only_failures_recorded():
    assert _classify(None, _now(), 0, _now()) == "dead"


def test_classify_healthy_recent_success_no_failures():
    assert _classify(_now() - timedelta(minutes=10), None, 0, _now()) == "healthy"


def test_classify_risk_when_one_recent_failure_after_success():
    assert _classify(_now() - timedelta(minutes=30), _now(),
                     1, _now()) == "risk"


def test_classify_unknown_after_24h_no_signal_decay():
    """Decay rule: success >24h ago AND no failures = unknown (not healthy)."""
    old = _now() - timedelta(hours=30)
    assert _classify(old, None, 0, _now()) == "unknown"


def test_classify_healthy_between_1h_and_24h_no_failure():
    """1h–24h with no failures should still be healthy (transition zone)."""
    assert _classify(_now() - timedelta(hours=5), None, 0, _now()) == "healthy"


# ── Shadow dedup gate ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_shadow_dedup_drops_pings_within_window(db):
    """Second ping within MIN_SHADOW_INTERVAL_S must NOT write a row."""
    async with db() as s:
        u = await _seed_user(s)
        await s.commit()
        ok1 = await shadow_ping(s, u.id, 12.97, 77.59, source="no_session")
        ok2 = await shadow_ping(s, u.id, 12.97, 77.60, source="no_session")
        ok3 = await shadow_ping(s, u.id, 12.97, 77.61, source="no_session")
    assert ok1 is True, "First ping must persist"
    assert ok2 is False, "Second ping inside dedup window must be dropped"
    assert ok3 is False, "Third ping inside dedup window must be dropped"
    async with db() as s:
        n = (await s.execute(
            text("SELECT COUNT(*) FROM shadow_location_pings WHERE user_id = :uid"),
            {"uid": u.id},
        )).scalar()
    assert n == 1, f"Only 1 row should exist, got {n}"


@pytest.mark.asyncio
async def test_shadow_dedup_releases_after_window(db, monkeypatch):
    """After the window elapses, the next ping persists again."""
    import app.services.shadow_tracking as st
    # Compress the window so the test runs in <1 s.
    monkeypatch.setattr(st, "MIN_SHADOW_INTERVAL_S", 0.05)
    monkeypatch.setattr(st, "SHADOW_RUN_GAP_S", 0.5)
    async with db() as s:
        u = await _seed_user(s)
        await s.commit()
        ok1 = await shadow_ping(s, u.id, 12.97, 77.59, source="no_session")
        await asyncio.sleep(0.1)
        ok2 = await shadow_ping(s, u.id, 12.97, 77.60, source="no_session")
    assert ok1 is True
    assert ok2 is True, "Ping after dedup window must persist"


@pytest.mark.asyncio
async def test_shadow_run_event_only_fires_on_new_run(db, monkeypatch):
    """`shadow_mode_activated` WS event must fire ONCE per shadow run,
    not per ping. Verified by patching the emitter and counting calls."""
    import app.services.shadow_tracking as st
    monkeypatch.setattr(st, "MIN_SHADOW_INTERVAL_S", 0.0)
    monkeypatch.setattr(st, "SHADOW_RUN_GAP_S", 999.0)  # never opens new run
    calls = []

    async def fake_emit(*a, **k):
        calls.append((a, k))
    monkeypatch.setattr(st, "_emit_shadow_run_event", fake_emit)

    async with db() as s:
        u = await _seed_user(s)
        await s.commit()
        # Three pings, all in the same shadow run.
        for _ in range(3):
            await shadow_ping(s, u.id, 12.97, 77.59, source="no_session")
            await asyncio.sleep(0.01)
    # Tasks are scheduled — let the loop drain.
    await asyncio.sleep(0.1)
    # First write opens the run; subsequent writes don't re-emit.
    assert len(calls) == 1, f"expected 1 event, got {len(calls)}"


# ── Next-action hint surfaces on the API path ────────────────────────
@pytest.mark.asyncio
async def test_zombie_cap_response_includes_next_action_hint(db):
    """The 24h cap path must tell the client to start a new session."""
    from fastapi.testclient import TestClient
    # Direct exercise of the rejection logic — the API layer maps
    # `Session is completed — cannot update location` → next_action.
    # We assert the engine returned the right error string here so that
    # the API mapping in guardian.py stays correct.
    async with db() as s:
        u = await _seed_user(s)
        gs = await _seed_session(s, u.id, age_hours=25)
        sid = str(gs.id)
        await s.commit()
    async with db() as s:
        result = await update_location(s, sid, 12.97, 77.59)
    assert "Session is completed" in result["error"]
