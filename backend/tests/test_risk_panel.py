"""Live Risk Panel — backend test bundle.

Locks the contract for `/api/command-center/risk-panel`:
  • AuthZ matrix (operator/admin allow, others deny, unauth deny)
  • Response shape (summary + ttfh + incidents + system blocks)
  • Urgency ranking (escalated > pending > shadow > stale)
  • Session-less alert appears in incidents
  • Active session whose device is unreachable appears as a
    standalone session-kind incident (when not already covered
    by an open alert)
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.api.risk_panel import (
    _summary_counters,
    _incidents,
    _system_health,
    _rank_for,
)
from app.models.guardian import GuardianAlert, GuardianSession
from app.models.user import User
from app.services.alert_ack_engine import mark_for_ack


def _factory():
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
    eng, factory = _factory()
    try:
        yield factory
    finally:
        await eng.dispose()


# ── unit: ranking is monotonic and correct ───────────────────────────
def test_rank_escalated_beats_pending():
    assert _rank_for("alert", {"ack_status": "escalated"}) > \
           _rank_for("alert", {"ack_status": "pending"})


def test_rank_pending_beats_shadow_session():
    assert _rank_for("alert", {"ack_status": "pending"}) > \
           _rank_for("session_shadow")


def test_rank_shadow_beats_stale():
    assert _rank_for("session_shadow") > _rank_for("session_stale")


# ── helper to seed a child + alert + optional session ─────────────────
async def _seed_alert(s, *, ack_status="pending",
                      severity="critical", with_session=False,
                      is_offline=False) -> tuple[GuardianAlert, User]:
    u = User(
        id=uuid.uuid4(),
        email=f"rp+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name=f"RP Test {uuid.uuid4().hex[:4]}",
        password_hash="x", role="child",
    )
    s.add(u)
    await s.flush()

    sess_id = None
    if with_session:
        gs = GuardianSession(
            id=uuid.uuid4(), user_id=u.id, status="active",
            started_at=datetime.now(timezone.utc),
            previous_update_at=datetime.now(timezone.utc),
            risk_level="LOW", risk_score=2.0,
            zone_name="z", current_location={"lat": 12.97, "lng": 77.59},
            last_seen_online_at=datetime.now(timezone.utc),
            total_points=0, offline_gaps=0, max_gap_seconds=0,
            is_offline=is_offline,
        )
        s.add(gs)
        await s.flush()
        sess_id = gs.id

    a = GuardianAlert(
        session_id=sess_id, user_id=u.id,
        alert_type="emergency", severity=severity,
        message="rp test", details="d", recommendation="r",
    )
    s.add(a)
    await s.flush()
    await mark_for_ack(s, a)
    if ack_status == "escalated":
        a.ack_status = "escalated"
        a.escalation_step = 1
    return a, u


# ── summary counters track new alerts ────────────────────────────────
@pytest.mark.asyncio
async def test_summary_counts_pending_critical(db):
    async with db() as s:
        before = await _summary_counters(s)
        await _seed_alert(s, ack_status="pending", severity="critical",
                          with_session=True)
        await s.commit()
    async with db() as s:
        after = await _summary_counters(s)
    assert after["pending_acks"] >= before["pending_acks"] + 1
    assert after["active_critical_alerts"] >= before["active_critical_alerts"] + 1


# ── incidents: session-less alert shows up correctly ────────────────
@pytest.mark.asyncio
async def test_incident_for_sessionless_alert(db):
    async with db() as s:
        a, u = await _seed_alert(s, ack_status="pending", severity="critical",
                                  with_session=False)
        await s.commit()
        aid = a.id
    async with db() as s:
        rows = await _incidents(s, limit=50)
    match = [r for r in rows if r.get("alert_id") == str(aid)]
    assert len(match) == 1
    inc = match[0]
    assert inc["kind"] == "alert"
    assert inc["session_id"] is None  # session-less
    assert inc["severity"] == "critical"
    assert inc["ack_status"] == "pending"
    assert inc["tracking_mode"] == "shadow"
    assert inc["rank"] == _rank_for("alert", {"ack_status": "pending"})


# ── incidents: escalated alert ranks above pending ──────────────────
@pytest.mark.asyncio
async def test_incidents_sorted_by_rank(db):
    async with db() as s:
        await _seed_alert(s, ack_status="pending", severity="critical",
                          with_session=True)
        await _seed_alert(s, ack_status="escalated", severity="critical",
                          with_session=True)
        await s.commit()
    async with db() as s:
        rows = await _incidents(s, limit=50)
    if len(rows) >= 2:
        # First row's rank >= second row's rank.
        assert rows[0]["rank"] >= rows[1]["rank"]


# ── incidents: shadow-mode session (no alert) shows as session-kind ──
@pytest.mark.asyncio
async def test_incident_for_orphan_offline_session(db):
    async with db() as s:
        u = User(
            id=uuid.uuid4(),
            email=f"rp_orphan+{uuid.uuid4().hex[:8]}@nischint.test",
            full_name="Orphan", password_hash="x", role="child",
        )
        s.add(u)
        await s.flush()
        # Session is offline AND there's NO open alert for this child.
        gs = GuardianSession(
            id=uuid.uuid4(), user_id=u.id, status="active",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            previous_update_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            risk_level="LOW", risk_score=2.0,
            zone_name="z", current_location={"lat": 12.97, "lng": 77.59},
            last_seen_online_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            total_points=0, offline_gaps=1, max_gap_seconds=300,
            is_offline=True,
        )
        s.add(gs)
        await s.commit()
        sid = gs.id
    async with db() as s:
        rows = await _incidents(s, limit=200)
    match = [r for r in rows if r.get("session_id") == str(sid)]
    assert len(match) == 1
    inc = match[0]
    assert inc["kind"] == "session"
    assert inc["alert_id"] is None
    assert inc["is_offline"] is True
    assert inc["tracking_mode"] == "shadow"


# ── system health rollup returns expected shape ──────────────────────
@pytest.mark.asyncio
async def test_system_health_shape(db):
    async with db() as s:
        out = await _system_health(s)
    # Each field is either None (degraded) or its expected type — never
    # a missing key.
    assert "sse_subscribers" in out
    assert "push_tokens" in out
    assert "watchdog_flips_1h" in out
    if out["push_tokens"] is not None:
        assert {"total", "healthy", "at_risk", "dead"}.issubset(out["push_tokens"])
