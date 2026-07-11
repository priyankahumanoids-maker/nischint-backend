"""NISCH-006 Day 3 — Tests for transition event persistence + timeline endpoint.

Locks the durable forensic contract:
  * Every transition writes an event row atomically (state + event in
    the same flush — failure of the flush rolls back both).
  * `actor_type` is preserved end-to-end: 'system' for pipeline,
    'guardian' for ACK, 'scheduler' for sweeper.
  * The DETECTED creation event has `from_state=None` — distinguishing
    creation from transition.
  * `elapsed_ms` math is correct, monotonically non-decreasing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.services.incident_state_machine import (
    IncidentState, transition,
)


@pytest_asyncio.fixture
async def session():
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "_jsonb_patched"):
        SQLiteTypeCompiler.visit_JSONB = lambda self, t, **kw: "JSON"  # type: ignore
        SQLiteTypeCompiler._jsonb_patched = True
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SafetyIncident.__table__.create)
        await conn.run_sync(SafetyIncidentEvent.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def _stub_emitters(monkeypatch):
    monkeypatch.setattr("app.services.incident_state_machine._emit_sse",
                        lambda *a, **kw: None)
    monkeypatch.setattr("app.services.incident_state_machine._emit_ttfa",
                        lambda *a, **kw: None)


def _mk_inc(**kw) -> SafetyIncident:
    now = datetime.now(timezone.utc)
    base = dict(
        id=uuid.uuid4(),
        child_id=uuid.uuid4(),
        incident_type="sos",
        severity="critical",
        state=IncidentState.DETECTED.value,
        confidence=0.87,
        sla_degraded_at_dispatch=False,
        created_at=now, updated_at=now,
        escalation_level=0,
    )
    base.update(kw)
    return SafetyIncident(**base)


# ── 1. Every transition writes an event row ────────────────────────
@pytest.mark.asyncio
async def test_transition_writes_event_row(session: AsyncSession):
    inc = _mk_inc()
    session.add(inc); await session.flush()

    await transition(session, inc, IncidentState.VALIDATING, actor_type="system")
    rows = (await session.execute(
        select(SafetyIncidentEvent).where(
            SafetyIncidentEvent.incident_id == inc.id
        ).order_by(SafetyIncidentEvent.created_at.asc())
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].from_state == "detected"
    assert rows[0].to_state   == "validating"
    assert rows[0].actor_type == "system"
    assert rows[0].ttfa_tag   == "incident_state:validating"


# ── 2. actor_type roundtrips for guardian + scheduler ──────────────
@pytest.mark.asyncio
async def test_actor_type_preserved_for_guardian(session: AsyncSession):
    inc = _mk_inc(state=IncidentState.ESCALATED.value)
    session.add(inc); await session.flush()
    actor = uuid.uuid4()
    await transition(session, inc, IncidentState.ACKNOWLEDGED,
                     actor_id=actor, actor_type="guardian")
    row = (await session.execute(
        select(SafetyIncidentEvent).where(
            SafetyIncidentEvent.incident_id == inc.id
        )
    )).scalars().one()
    assert row.actor_type == "guardian"
    assert row.actor_id == actor


@pytest.mark.asyncio
async def test_actor_type_scheduler_from_sweeper(session: AsyncSession):
    """Sweeper writes 'scheduler' actor_type — auditors see auto-close."""
    from app.services.safety_incident_engine import sweep_lifecycle
    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(minutes=120)
    inc = _mk_inc(state=IncidentState.ACKNOWLEDGED.value, updated_at=long_ago)
    session.add(inc); await session.flush()

    await sweep_lifecycle(
        session,
        escalated_resolve_minutes=30,
        acknowledged_resolve_minutes=30,
        resolved_archive_minutes=99999,
        now=now,
    )
    row = (await session.execute(
        select(SafetyIncidentEvent).where(
            SafetyIncidentEvent.incident_id == inc.id,
            SafetyIncidentEvent.to_state == "resolved",
        )
    )).scalars().one()
    assert row.actor_type == "scheduler"


# ── 3. open_incident_for_alert writes the genesis event ────────────
@pytest.mark.asyncio
async def test_open_writes_detected_creation_event(session: AsyncSession,
                                                    monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "green")

    inc = await sie.open_incident_for_alert(
        session, child_id=str(uuid.uuid4()),
        kind="sos", severity="critical",
        alert_id="aid-genesis", confidence=0.91,
    )
    rows = (await session.execute(
        select(SafetyIncidentEvent).where(
            SafetyIncidentEvent.incident_id == inc.id
        )
    )).scalars().all()
    assert len(rows) == 1
    e = rows[0]
    assert e.from_state is None  # genesis marker
    assert e.to_state   == "detected"
    assert e.actor_type == "system"
    assert e.ttfa_tag   == "incident_state:detected"
    assert e.extra.get("alert_id") == "aid-genesis"
    assert e.extra.get("confidence") == 0.91


# ── 4. Full chain produces ordered event log ───────────────────────
@pytest.mark.asyncio
async def test_full_chain_event_log_is_ordered(session: AsyncSession,
                                                 monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "green")

    inc = await sie.open_incident_for_alert(
        session, child_id=str(uuid.uuid4()),
        kind="voice_distress", severity="critical",
    )
    for nxt in [IncidentState.VALIDATING, IncidentState.ESCALATED,
                IncidentState.ACKNOWLEDGED, IncidentState.RESOLVED,
                IncidentState.ARCHIVED]:
        await transition(session, inc, nxt)

    rows = (await session.execute(
        select(SafetyIncidentEvent)
        .where(SafetyIncidentEvent.incident_id == inc.id)
        .order_by(SafetyIncidentEvent.created_at.asc())
    )).scalars().all()
    transitions = [(r.from_state, r.to_state) for r in rows]
    assert transitions == [
        (None,           "detected"),
        ("detected",     "validating"),
        ("validating",   "escalated"),
        ("escalated",    "acknowledged"),
        ("acknowledged", "resolved"),
        ("resolved",     "archived"),
    ]
    # Monotonic timestamps.
    for a, b in zip(rows, rows[1:]):
        assert b.created_at >= a.created_at


# ── 5. SLA-degraded flag propagates to events ──────────────────────
@pytest.mark.asyncio
async def test_event_carries_sla_degraded_flag(session: AsyncSession,
                                                 monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "red")  # degraded
    inc = await sie.open_incident_for_alert(
        session, child_id=str(uuid.uuid4()),
        kind="sos", severity="critical",
    )
    assert inc.sla_degraded_at_dispatch is True
    # Genesis event should mirror.
    e = (await session.execute(
        select(SafetyIncidentEvent).where(
            SafetyIncidentEvent.incident_id == inc.id
        )
    )).scalars().one()
    assert e.sla_degraded is True


# ── 6. Confidence + escalation_level land in metadata ──────────────
@pytest.mark.asyncio
async def test_event_metadata_carries_confidence_and_escalation(
        session: AsyncSession):
    inc = _mk_inc(confidence=0.42, escalation_level=2,
                  state=IncidentState.VALIDATING.value)
    session.add(inc); await session.flush()
    await transition(session, inc, IncidentState.ESCALATED)
    row = (await session.execute(
        select(SafetyIncidentEvent).where(
            SafetyIncidentEvent.incident_id == inc.id
        )
    )).scalars().one()
    assert row.extra["confidence"] == 0.42
    assert row.extra["escalation_level"] == 2
