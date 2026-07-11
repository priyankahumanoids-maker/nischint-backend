"""NISCH-006 — Integration tests for the safety_incident_engine wiring.

Covers:
  * `_safe_sla_snapshot` chaos-safety
  * `open_incident_for_alert` persistence + extra backfill
  * `acknowledge_incident_for_alert` non-fatal contract
  * `sweep_lifecycle` end-to-end transitions on real model
  * Full DETECTED → ARCHIVED chain through the state machine

Uses sqlite-in-memory bound to the production `SafetyIncident` ORM
(UUID(as_uuid=True) + JSONB degrade gracefully under sqlite). The
sweep is portable because `with_for_update` is gated behind a
dialect probe.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

from app.db.base import Base  # noqa: F401  (registers all mappers)
from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.services.incident_state_machine import IncidentState, transition


@pytest_asyncio.fixture
async def session():
    # JSONB doesn't compile on sqlite — register a fallback impl.
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
    if not hasattr(SQLiteTypeCompiler, "_jsonb_patched"):
        SQLiteTypeCompiler.visit_JSONB = lambda self, t, **kw: "JSON"  # type: ignore
        SQLiteTypeCompiler._jsonb_patched = True
    # UUID(as_uuid=True) → store as CHAR(32) on sqlite (default behaviour).

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
        confidence=1.0,
        sla_degraded_at_dispatch=False,
        created_at=now, updated_at=now,
        escalation_level=0,
    )
    base.update(kw)
    return SafetyIncident(**base)


# ── 1. SLA snapshot is non-blocking ────────────────────────────────
def test_sla_snapshot_default_safe(monkeypatch):
    """A failing SLA monitor must NOT raise — return (None, False).

    Simulate a corrupted module: the helper imports succeed but
    reading `_last_status` raises. The wrapper catches and returns
    a safe default.
    """
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor

    class _Boom:
        def __getattr__(self, _):
            raise RuntimeError("redis down")
    monkeypatch.setattr(sla_monitor, "_last_status",
                        property(lambda self: (_ for _ in ()).throw(RuntimeError("redis down"))),
                        raising=False)
    # Easier: just have `_last_status` be an object that raises on .lower().
    class _Bad:
        def __or__(self, *a, **kw): raise RuntimeError("boom")
        def lower(self): raise RuntimeError("boom")
    monkeypatch.setattr(sla_monitor, "_last_status", _Bad())
    sla_id, degraded = sie._safe_sla_snapshot()
    assert sla_id is None
    assert degraded is False


def test_sla_snapshot_amber_yields_degraded(monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "amber")
    sla_id, degraded = sie._safe_sla_snapshot()
    assert sla_id is None
    assert degraded is True


def test_sla_snapshot_red_yields_degraded(monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "red")
    _, degraded = sie._safe_sla_snapshot()
    assert degraded is True


def test_sla_snapshot_green(monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "green")
    _, degraded = sie._safe_sla_snapshot()
    assert degraded is False


# ── 2. Full lifecycle chain via state machine ───────────────────────
@pytest.mark.asyncio
async def test_full_lifecycle_chain(session: AsyncSession):
    inc = _mk_inc()
    session.add(inc)
    await session.flush()

    chain = [
        IncidentState.VALIDATING,
        IncidentState.ESCALATED,
        IncidentState.ACKNOWLEDGED,
        IncidentState.RESOLVED,
        IncidentState.ARCHIVED,
    ]
    for nxt in chain:
        await transition(session, inc, nxt)
    assert inc.state == IncidentState.ARCHIVED.value
    assert inc.resolved_at is not None
    assert inc.archived_at is not None


# ── 3. find_by_alert_id round-trip + ack linkage ───────────────────
@pytest.mark.asyncio
async def test_find_by_alert_id_round_trip(session: AsyncSession):
    """SQLite 3.38+ supports `->>'alert_id'`. The helper must find the
    incident by its stored alert_id linkage — round-trip works."""
    from app.services.safety_incident_engine import find_by_alert_id
    inc = _mk_inc(extra={"alert_id": "aid-fake"})
    session.add(inc)
    await session.flush()
    out = await find_by_alert_id(session, "aid-fake")
    assert out is not None
    assert out.id == inc.id


@pytest.mark.asyncio
async def test_find_by_alert_id_missing_returns_none(session: AsyncSession):
    from app.services.safety_incident_engine import find_by_alert_id
    out = await find_by_alert_id(session, "nope")
    assert out is None


@pytest.mark.asyncio
async def test_ack_linked_incident_transitions(session: AsyncSession):
    """When an alert ack lands and the linked incident is ESCALATED,
    the helper must transition it to ACKNOWLEDGED + stamp acker."""
    from app.services.safety_incident_engine import (
        acknowledge_incident_for_alert,
    )
    inc = _mk_inc(state=IncidentState.ESCALATED.value,
                  extra={"alert_id": "aid-ack"})
    session.add(inc); await session.flush()
    actor = uuid.uuid4()
    out = await acknowledge_incident_for_alert(
        session, alert_id="aid-ack", actor_id=actor,
    )
    assert out is not None
    assert out.id == inc.id
    assert inc.state == IncidentState.ACKNOWLEDGED.value
    assert inc.acknowledged_by == actor
    assert inc.acknowledged_at is not None


# ── 4. acknowledge_incident_for_alert is non-fatal when unlinked ────
@pytest.mark.asyncio
async def test_ack_for_unlinked_alert_returns_none(session: AsyncSession):
    from app.services.safety_incident_engine import acknowledge_incident_for_alert
    out = await acknowledge_incident_for_alert(
        session, alert_id=uuid.uuid4(), actor_id=uuid.uuid4(),
    )
    assert out is None


# ── 5. Lifecycle sweep transitions ─────────────────────────────────
@pytest.mark.asyncio
async def test_sweep_resolves_idle_incidents(session: AsyncSession):
    from app.services.safety_incident_engine import sweep_lifecycle

    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(minutes=120)
    fresh    = now - timedelta(minutes=2)

    inc1 = _mk_inc(state=IncidentState.ACKNOWLEDGED.value, updated_at=long_ago)  # → RESOLVED
    inc2 = _mk_inc(state=IncidentState.ACKNOWLEDGED.value, updated_at=fresh)     # stays
    inc3 = _mk_inc(state=IncidentState.ESCALATED.value,    updated_at=long_ago)  # → RESOLVED
    inc4 = _mk_inc(state=IncidentState.RESOLVED.value,     updated_at=long_ago)  # → ARCHIVED
    inc5 = _mk_inc(state=IncidentState.RESOLVED.value,     updated_at=fresh)     # stays

    session.add_all([inc1, inc2, inc3, inc4, inc5])
    await session.flush()

    counts = await sweep_lifecycle(
        session,
        escalated_resolve_minutes=30,
        acknowledged_resolve_minutes=30,
        resolved_archive_minutes=30,
        now=now,
    )
    assert counts["resolved_from_ack"]       == 1
    assert counts["resolved_from_escalated"] == 1
    assert counts["archived"]                == 1
    assert inc1.state == IncidentState.RESOLVED.value
    assert inc2.state == IncidentState.ACKNOWLEDGED.value
    assert inc3.state == IncidentState.RESOLVED.value
    assert inc4.state == IncidentState.ARCHIVED.value
    assert inc5.state == IncidentState.RESOLVED.value


@pytest.mark.asyncio
async def test_sweep_is_idempotent(session: AsyncSession):
    from app.services.safety_incident_engine import sweep_lifecycle

    now = datetime.now(timezone.utc)
    long_ago = now - timedelta(minutes=120)
    inc = _mk_inc(state=IncidentState.ACKNOWLEDGED.value, updated_at=long_ago)
    session.add(inc); await session.flush()

    c1 = await sweep_lifecycle(
        session, escalated_resolve_minutes=30,
        acknowledged_resolve_minutes=30, resolved_archive_minutes=99999,
        now=now,
    )
    c2 = await sweep_lifecycle(
        session, escalated_resolve_minutes=30,
        acknowledged_resolve_minutes=30, resolved_archive_minutes=99999,
        now=now,
    )
    assert c1["resolved_from_ack"] == 1
    assert c2["resolved_from_ack"] == 0
    assert inc.state == IncidentState.RESOLVED.value


# ── 6. open_incident_for_alert ─────────────────────────────────────
@pytest.mark.asyncio
async def test_open_incident_persists_with_alert_id(session: AsyncSession, monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "green")

    cu = uuid.uuid4()
    inc = await sie.open_incident_for_alert(
        session, child_id=str(cu), kind="sos", severity="critical",
        alert_id="aid-123",
    )
    assert inc is not None
    assert inc.state == IncidentState.DETECTED.value
    assert inc.incident_type == "sos"
    assert inc.severity == "critical"
    assert (inc.extra or {}).get("alert_id") == "aid-123"
    assert inc.sla_degraded_at_dispatch is False


@pytest.mark.asyncio
async def test_open_incident_amber_sla_stamps_degraded(session: AsyncSession, monkeypatch):
    from app.services import safety_incident_engine as sie
    from app.services import sla_monitor
    monkeypatch.setattr(sla_monitor, "_last_status", "amber")

    inc = await sie.open_incident_for_alert(
        session, child_id=str(uuid.uuid4()), kind="sos", severity="critical",
    )
    assert inc is not None
    assert inc.sla_degraded_at_dispatch is True


@pytest.mark.asyncio
async def test_open_incident_invalid_child_id_returns_none(session: AsyncSession):
    from app.services.safety_incident_engine import open_incident_for_alert
    out = await open_incident_for_alert(
        session, child_id="not-a-uuid", kind="sos", severity="critical",
    )
    assert out is None


# ── 7. advance helpers are non-fatal ────────────────────────────────
@pytest.mark.asyncio
async def test_advance_helpers_are_non_fatal(session: AsyncSession):
    from app.services.safety_incident_engine import (
        advance_to_validating, advance_to_escalated,
    )
    # None — must NOT raise.
    await advance_to_validating(session, None)
    await advance_to_escalated(session, None)
    # Already terminal — silent no-op.
    inc = _mk_inc(state=IncidentState.ARCHIVED.value)
    session.add(inc); await session.flush()
    await advance_to_validating(session, inc)
    await advance_to_escalated(session, inc)
    assert inc.state == IncidentState.ARCHIVED.value
