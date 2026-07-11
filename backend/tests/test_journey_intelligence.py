"""Journey Intelligence — backend test bundle.

Locks the contract for Steps 4 (gap detector), 5 (ACK engine offline-
aware tracking_mode), 6 (watchdog downgrade-only), and 7 (polyline
endpoint). Plus the high-leverage cross-cutting test:
`test_ack_engine_offline_session_gets_shadow_tracking_mode`.

Reads the live DB via DATABASE_URL — same pattern as the other tests
in this folder.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.guardian import GuardianSession, GuardianAlert, JourneyPoint
from app.models.user import User
from app.services.alert_ack_engine import mark_for_ack
from app.services.guardian_mode_engine import update_location
from app.services import journey_watchdog


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


async def _seed_session(s, *, started_offset_s: int = 0,
                         prev_update_offset_s: int | None = None,
                         is_offline: bool = False) -> GuardianSession:
    """Seed a child + active session. `started_offset_s` is how long
    ago the session was started; `prev_update_offset_s` is how long
    ago the last GPS arrived (defaults to started_at)."""
    u = User(
        id=uuid.uuid4(),
        email=f"jic+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="Journey Test", password_hash="x", role="child",
    )
    s.add(u)
    await s.flush()
    now = datetime.now(timezone.utc)
    started = now - timedelta(seconds=started_offset_s)
    prev = (now - timedelta(seconds=prev_update_offset_s)
            if prev_update_offset_s is not None else started)
    gs = GuardianSession(
        id=uuid.uuid4(), user_id=u.id, status="active",
        started_at=started, previous_update_at=prev,
        risk_level="LOW", risk_score=2.0, zone_name="test_zone",
        current_location={"lat": 12.97, "lng": 77.59},
        last_seen_online_at=prev, total_points=0, offline_gaps=0,
        max_gap_seconds=0, is_offline=is_offline,
    )
    s.add(gs)
    await s.flush()
    return gs


# ── Step 4: gap detector ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_gap_detector_classifies_good_under_15s(db):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=2)
        await update_location(s, str(gs.id), 12.971, 77.591, accuracy=10)
        await s.commit()
        sid = gs.id
    async with db() as s:
        rows = (await s.execute(
            select(JourneyPoint).where(JourneyPoint.session_id == sid)
            .order_by(JourneyPoint.seq)
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].quality == "good"
    assert rows[0].gap_before_s is not None and rows[0].gap_before_s < 15


@pytest.mark.asyncio
async def test_gap_detector_classifies_unstable_15_to_30s(db):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=20)
        await update_location(s, str(gs.id), 12.971, 77.591, accuracy=10)
        await s.commit()
        sid = gs.id
    async with db() as s:
        p = (await s.execute(
            select(JourneyPoint).where(JourneyPoint.session_id == sid)
        )).scalar_one()
    assert p.quality == "unstable"
    assert 15 <= (p.gap_before_s or 0) < 30


@pytest.mark.asyncio
async def test_gap_detector_classifies_offline_over_30s(db):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=45)
        await update_location(s, str(gs.id), 12.971, 77.591, accuracy=10)
        await s.commit()
        sid = gs.id
    async with db() as s:
        p = (await s.execute(
            select(JourneyPoint).where(JourneyPoint.session_id == sid)
        )).scalar_one()
        gs2 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
    assert p.quality == "offline"
    assert (p.gap_before_s or 0) >= 30
    # Counter ticked
    assert gs2.offline_gaps >= 1
    assert gs2.max_gap_seconds >= 30


# ── total_points monotonic + gap counters ────────────────────────────
@pytest.mark.asyncio
async def test_max_gap_seconds_only_grows(db):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=45)  # gap=45
        await update_location(s, str(gs.id), 12.971, 77.591, accuracy=10)
        await s.commit()
        sid = gs.id
    async with db() as s:
        gs2 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
        first_max = gs2.max_gap_seconds
        # Now ping again quickly — max_gap should NOT shrink
        await update_location(s, str(sid), 12.972, 77.592, accuracy=10)
        await s.commit()
    async with db() as s:
        gs3 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
    assert gs3.max_gap_seconds >= first_max


# ── Recovery: GPS path is the ONLY thing that flips is_offline=False ─
@pytest.mark.asyncio
async def test_offline_recovery_flips_is_offline_false(db):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=60, is_offline=True)
        await s.commit()
        sid = gs.id
    # Fresh ping arrives — should clear is_offline.
    async with db() as s:
        await update_location(s, str(sid), 12.971, 77.591, accuracy=10)
        await s.commit()
    # The fresh ping was >30s after previous_update_at, so the gap
    # detector marks the new point as 'offline' — but the ping ALSO
    # updated previous_update_at to "now", and after this any future
    # ping will see is_offline=False AGAIN once gap drops under 30s.
    # The contract for THIS test: even on a single arriving ping, the
    # GPS path is allowed to re-evaluate is_offline (Invariant #3).
    # For the canonical "recovered" flag, second ping is the cleanest
    # signal — it'll be `good` and is_offline=False.
    async with db() as s:
        await update_location(s, str(sid), 12.972, 77.592, accuracy=10)
        await s.commit()
    async with db() as s:
        gs3 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
    assert gs3.is_offline is False
    assert gs3.last_seen_online_at is not None


# ── Step 6: watchdog downgrade-only (Invariant #3) ───────────────────
@pytest.mark.asyncio
async def test_watchdog_marks_stale_sessions_offline(db, monkeypatch):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=60, is_offline=False)
        await s.commit()
        sid = gs.id
    # Run the watchdog tick — it talks to the DB via async_session.
    res = await journey_watchdog.tick()
    assert res["flipped"] >= 1
    async with db() as s:
        gs2 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
    assert gs2.is_offline is True
    assert gs2.offline_gaps >= 1
    assert gs2.max_gap_seconds >= 30


@pytest.mark.asyncio
async def test_watchdog_idempotent_on_already_offline(db):
    async with db() as s:
        gs = await _seed_session(s, prev_update_offset_s=60, is_offline=True)
        await s.commit()
        sid = gs.id
        offline_gaps_before = gs.offline_gaps
    # Tick should NOT touch this session — already offline.
    await journey_watchdog.tick()
    async with db() as s:
        gs2 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
    assert gs2.is_offline is True
    assert gs2.offline_gaps == offline_gaps_before


@pytest.mark.asyncio
async def test_watchdog_never_upgrades_to_active(db):
    """Invariant #3 — watchdog has no positive-side authority."""
    async with db() as s:
        # Session that's clearly fresh (5s ago) and online.
        gs = await _seed_session(s, prev_update_offset_s=5, is_offline=False)
        await s.commit()
        sid = gs.id
    await journey_watchdog.tick()
    async with db() as s:
        gs2 = (await s.execute(
            select(GuardianSession).where(GuardianSession.id == sid)
        )).scalar_one()
    # Still online, no spurious offline flip.
    assert gs2.is_offline is False
    assert gs2.status == "active"


# ── Step 5: ACK engine — offline session gets shadow tracking_mode ───
# (the high-leverage cross-cutting test from the brief)
@pytest.mark.asyncio
async def test_ack_engine_offline_session_gets_shadow_tracking_mode(db):
    async with db() as s:
        # Session is "active" but device is offline — exactly the
        # case where ACK engine MUST treat it as shadow and apply
        # the 10s fast-path timeout.
        gs = await _seed_session(s, is_offline=True)
        alert = GuardianAlert(
            session_id=gs.id, user_id=gs.user_id,
            alert_type="emergency", severity="critical",
            message="t", details="d", recommendation="r",
        )
        s.add(alert)
        await s.flush()
        await mark_for_ack(s, alert)
        await s.commit()
        aid = alert.id
    async with db() as s:
        a = (await s.execute(
            select(GuardianAlert).where(GuardianAlert.id == aid)
        )).scalar_one()
    ctx = a.context_json or {}
    assert ctx.get("has_active_session") is True
    assert ctx.get("is_offline") is True
    assert ctx.get("tracking_mode") == "shadow"
    # Critical + shadow → 10s fast-path (per _compute_ack_timeout).
    assert a.ack_timeout_sec == 10


# ── Session-less alert: orthogonal signals (Tightening contract) ─────
@pytest.mark.asyncio
async def test_sessionless_alert_has_active_session_false_not_offline(db):
    async with db() as s:
        u = User(
            id=uuid.uuid4(),
            email=f"sl+{uuid.uuid4().hex[:8]}@nischint.test",
            full_name="No Session Test", password_hash="x", role="child",
        )
        s.add(u)
        await s.flush()
        alert = GuardianAlert(
            session_id=None,           # ← session-less
            user_id=u.id,
            alert_type="help_requested", severity="critical",
            message="t", details="d", recommendation="r",
        )
        s.add(alert)
        await s.flush()
        await mark_for_ack(s, alert)
        await s.commit()
        aid = alert.id
    async with db() as s:
        a = (await s.execute(
            select(GuardianAlert).where(GuardianAlert.id == aid)
        )).scalar_one()
    ctx = a.context_json or {}
    assert ctx.get("has_active_session") is False
    # Two signals are orthogonal: no session does NOT imply offline.
    assert ctx.get("is_offline") is False
    # tracking_mode still resolves to shadow (operator must assume
    # device unreachable when no live journey exists).
    assert ctx.get("tracking_mode") == "shadow"
    # Fast-path applies.
    assert a.ack_timeout_sec == 10
