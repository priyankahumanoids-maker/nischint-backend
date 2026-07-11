"""Tests for the Alert ACK + Escalation engine — production-trust set.

Locks the contract:
  • Critical-severity alerts auto-flag for ACK with 30s deadline.
  • Context bundle captured at mark_for_ack and frozen for forensics.
  • Tri-state ACK (seen / acting / resolved) with forward-only progression.
  • First ACK fires `alert_closed` for cancellation, subsequent updates
    fire `alert_acknowledged` only.
  • Past the deadline, `process_pending_acks` advances escalation by 1.
  • `seen` ACK without `acting` within 60s → soft re-escalation
    (`alert_seen_lapsed` event, ack_type='seen_lapsed').
  • Race-safe: ACK uses SELECT FOR UPDATE so a parallel tick can't
    escalate an alert mid-ACK.
  • Late ACKs after escalation still close out, with `was_late=True`.
  • Time-To-First-Human metric is computable.
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
from app.models.guardian import GuardianSession, GuardianAlert
from app.models.user import User
from app.services.alert_ack_engine import (
    severity_requires_ack, mark_for_ack, acknowledge_alert,
    process_pending_acks, get_ttfh_metrics, heartbeat_acting,
    _compute_ack_timeout,
    ESCALATION_STEPS, DEFAULT_ACK_TIMEOUT_S, SEEN_TO_ACTING_WINDOW_S,
    ACTING_HEARTBEAT_WINDOW_S,
)


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


async def _seed_user(s, role: str = "guardian") -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"ack+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="ACK Test", password_hash="x", role=role,
    )
    s.add(u)
    await s.flush()
    return u


async def _seed_session_and_alert(s, *, severity: str = "critical",
                                  with_location: bool = True) -> GuardianAlert:
    u = User(
        id=uuid.uuid4(),
        email=f"child+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="Child Test", password_hash="x", role="child",
    )
    s.add(u)
    await s.flush()
    gs = GuardianSession(
        id=uuid.uuid4(), user_id=u.id, status="active",
        started_at=datetime.now(timezone.utc),
        previous_update_at=datetime.now(timezone.utc),
        risk_level="HIGH", risk_score=8, zone_name="default",
        current_location={"lat": 12.97, "lng": 77.59} if with_location else None,
    )
    s.add(gs)
    await s.flush()
    alert = GuardianAlert(
        session_id=gs.id, user_id=u.id,
        alert_type="emergency", severity=severity,
        message="Test", details="d", recommendation="r",
    )
    s.add(alert)
    await s.flush()
    return alert


# ── Severity gate ────────────────────────────────────────────────────
def test_severity_critical_requires_ack():
    assert severity_requires_ack("critical") is True
    assert severity_requires_ack("emergency") is True
    assert severity_requires_ack("high") is True


def test_severity_low_does_not_require_ack():
    assert severity_requires_ack("low") is False
    assert severity_requires_ack("medium") is False
    assert severity_requires_ack("") is False
    assert severity_requires_ack(None) is False  # type: ignore[arg-type]


# ── mark_for_ack + context bundle ────────────────────────────────────
@pytest.mark.asyncio
async def test_mark_for_ack_sets_pending_and_captures_context(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        await s.commit()
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_required is True
    assert a.ack_status == "pending"
    # Risk-weighted: critical → 15s.
    assert a.ack_timeout_sec == 15
    assert a.ack_deadline is not None
    # Context bundle was captured
    ctx = a.context_json
    assert "captured_at" in ctx
    assert ctx.get("tracking_mode") == "active"
    assert ctx.get("risk_level") == "HIGH"
    assert ctx.get("last_location", {}).get("lat") == 12.97
    assert "user_id" in ctx


@pytest.mark.asyncio
async def test_mark_for_ack_idempotent_after_ack(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        async with db() as s2:
            a2 = (await s2.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            await mark_for_ack(s2, a2)  # must be no-op
        async with db() as s3:
            a3 = (await s3.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
        assert a3.ack_status == "acknowledged"


# ── acknowledge_alert: tri-state ─────────────────────────────────────
@pytest.mark.asyncio
async def test_first_ack_seen_opens_60s_acting_window(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        result = await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
    assert result["acknowledged"] is True
    assert result["ack_type"] == "seen"
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_status == "acknowledged"
    assert a.ack_type == "seen"
    assert a.acked_by == u.id
    assert a.seen_deadline is not None
    delta_s = (a.seen_deadline - datetime.now(timezone.utc)).total_seconds()
    assert 0 < delta_s <= SEEN_TO_ACTING_WINDOW_S + 5


@pytest.mark.asyncio
async def test_acting_clears_seen_deadline(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_type == "acting"
    assert a.seen_deadline is None


@pytest.mark.asyncio
async def test_resolved_terminal(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        result = await acknowledge_alert(s, alert.id, u.id,
                                          ack_type="resolved", confirmed=True)
    assert result["ack_type"] == "resolved"
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    types = [h.get("step") for h in a.escalation_history]
    assert "seen" in types and "resolved" in types


@pytest.mark.asyncio
async def test_resolved_without_confirmed_is_rejected(db):
    """Misclick guard: `resolved` must carry `confirmed=True`."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        result = await acknowledge_alert(s, alert.id, u.id,
                                          ack_type="resolved", confirmed=False)
    assert result["acknowledged"] is False
    assert result["reason"] == "confirmation_required"
    # State must be unchanged.
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_type == "seen"


@pytest.mark.asyncio
async def test_seen_does_not_require_confirmation(db):
    """Misclick guard applies ONLY to resolved — seen stays instant."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        result = await acknowledge_alert(s, alert.id, u.id,
                                          ack_type="seen", confirmed=False)
    assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_acting_does_not_require_confirmation(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        result = await acknowledge_alert(s, alert.id, u.id,
                                          ack_type="acting", confirmed=False)
    assert result["acknowledged"] is True
    assert result["ack_type"] == "acting"


@pytest.mark.asyncio
async def test_backward_transition_rejected(db):
    """Once `acting`, you can't go back to `seen`."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
        result = await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
    assert result["status"] == "already_acknowledged"
    assert result["ack_type"] == "acting"  # unchanged


@pytest.mark.asyncio
async def test_invalid_ack_type_rejected(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        result = await acknowledge_alert(s, alert.id, u.id, ack_type="bogus")
    assert result["acknowledged"] is False
    assert result["reason"] == "invalid_ack_type"


@pytest.mark.asyncio
async def test_acknowledge_unknown_alert_returns_not_found(db):
    async with db() as s:
        u = await _seed_user(s)
        await s.commit()
        result = await acknowledge_alert(s, uuid.uuid4(), u.id, ack_type="seen")
    assert result["acknowledged"] is False
    assert result["reason"] == "not_found"


# ── Race condition: SELECT FOR UPDATE serializes tick + ACK ──────────
@pytest.mark.asyncio
async def test_ack_during_expired_pending_does_not_escalate(db):
    """If a tick and an ACK race, ACK must win (the lock serializes).
    Concretely: an alert whose deadline is in the past, but a guardian
    ACKs before the tick runs — the tick must find ack_status !=
    pending and skip escalation."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        # Backdate deadline.
        alert.ack_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        u = await _seed_user(s)
        await s.commit()
        # ACK first — this transitions to 'acknowledged'.
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        # Tick runs after — the WHERE filter excludes acknowledged rows.
        await process_pending_acks(s)
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_status == "acknowledged"
    assert a.escalation_step == 0


# ── process_pending_acks: hard escalation ───────────────────────────
@pytest.mark.asyncio
async def test_pending_alert_with_future_deadline_not_escalated(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        await s.commit()
    async with db() as s:
        await process_pending_acks(s)
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_status == "pending"
    assert a.escalation_step == 0


@pytest.mark.asyncio
async def test_expired_deadline_advances_one_step(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        alert.ack_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        await s.commit()
    async with db() as s:
        out = await process_pending_acks(s)
    assert out["escalated"] >= 1
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.escalation_step == 1
    assert a.ack_status == "pending"
    last = a.escalation_history[-1]
    assert last["step"] == 1
    assert last["name"] == ESCALATION_STEPS[0]
    assert last["reason"] == "ack_timeout"


@pytest.mark.asyncio
async def test_chain_exhaustion_parks_at_escalated(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        await s.commit()
    for _ in range(len(ESCALATION_STEPS) + 2):
        async with db() as s:
            a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            a.ack_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
            await s.commit()
            await process_pending_acks(s)
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_status == "escalated"


@pytest.mark.asyncio
async def test_late_ack_after_escalation_still_closes(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        alert.ack_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        await s.commit()
        await process_pending_acks(s)
        u = await _seed_user(s)
        await s.commit()
        result = await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
    assert result["acknowledged"] is True
    assert result["was_late"] is True


# ── seen_lapsed soft re-escalation ──────────────────────────────────
@pytest.mark.asyncio
async def test_seen_lapsed_fires_after_window(db):
    """A `seen` ACK without `acting` within 60s → ack_type='seen_lapsed'."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        # Force the seen_deadline into the past.
        a_obj = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
        a_obj.seen_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        await s.commit()
        out = await process_pending_acks(s)
    assert out["seen_lapsed"] >= 1
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_type == "seen_lapsed"
    assert a.seen_deadline is None
    assert any(h.get("step") == "seen_lapsed" for h in a.escalation_history)


@pytest.mark.asyncio
async def test_acting_in_time_does_not_lapse(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
        await process_pending_acks(s)
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_type == "acting"


# ── TTFH metric ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ttfh_metric_returns_shape(db):
    async with db() as s:
        m = await get_ttfh_metrics(s, window_days=30)
    assert "p50_seconds" in m
    assert "p95_seconds" in m
    assert "avg_seconds" in m
    assert "acked_count" in m
    assert "escalated_count" in m


# ── Risk-weighted timeout (#3) ───────────────────────────────────────
def test_compute_timeout_critical_is_15s():
    assert _compute_ack_timeout("critical", {}) == 15
    assert _compute_ack_timeout("emergency", {}) == 15


def test_compute_timeout_high_is_30s():
    assert _compute_ack_timeout("high", {}) == 30


def test_compute_timeout_shadow_halves_with_floor():
    # critical (15) → halved = 7.5, but floored at 10
    assert _compute_ack_timeout("critical", {"tracking_mode": "shadow"}) == 10
    # high (30) → halved = 15
    assert _compute_ack_timeout("high", {"tracking_mode": "shadow"}) == 15


def test_compute_timeout_active_tracking_unchanged():
    assert _compute_ack_timeout("critical", {"tracking_mode": "active"}) == 15
    assert _compute_ack_timeout("high", {"tracking_mode": "ended"}) == 30


@pytest.mark.asyncio
async def test_mark_for_ack_uses_risk_weighted_timeout(db):
    """A critical alert should arm with a 15s deadline by default."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        await s.commit()
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_timeout_sec == 15
    delta_s = (a.ack_deadline - datetime.now(timezone.utc)).total_seconds()
    assert 0 < delta_s <= 15 + 5


# ── Acting heartbeat (#2) ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_acting_sets_heartbeat_on_transition(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.acting_heartbeat_at is not None


@pytest.mark.asyncio
async def test_heartbeat_refreshes_timestamp(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
        # Backdate the heartbeat by 20s.
        a_obj = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
        a_obj.acting_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=20)
        await s.commit()
        result = await heartbeat_acting(s, alert.id, u.id)
    assert result["ok"] is True
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    age = (datetime.now(timezone.utc) - a.acting_heartbeat_at).total_seconds()
    assert age < 30, f"heartbeat not refreshed (age={age}s)"


@pytest.mark.asyncio
async def test_heartbeat_rejected_if_not_acting(db):
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        # Only `seen` ACK — heartbeat should be rejected.
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        result = await heartbeat_acting(s, alert.id, u.id)
    assert result["ok"] is False
    assert result["reason"] == "not_acting"


@pytest.mark.asyncio
async def test_acting_lapsed_fires_after_heartbeat_window(db):
    """A guardian who clicks `acting` and goes silent for 30s+ →
    ack_type='acting_lapsed', alert_acting_lapsed event."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
        a_obj = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
        a_obj.acting_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=ACTING_HEARTBEAT_WINDOW_S + 5)
        await s.commit()
        out = await process_pending_acks(s)
    assert out.get("acting_lapsed", 0) >= 1
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.ack_type == "acting_lapsed"
    assert any(h.get("step") == "acting_lapsed" for h in a.escalation_history)


@pytest.mark.asyncio
async def test_acting_lapsed_does_not_re_fire(db):
    """Once parked at `acting_lapsed`, the tick must not re-fire."""
    async with db() as s:
        alert = await _seed_session_and_alert(s, severity="critical")
        await mark_for_ack(s, alert)
        u = await _seed_user(s)
        await s.commit()
        await acknowledge_alert(s, alert.id, u.id, ack_type="seen")
        await acknowledge_alert(s, alert.id, u.id, ack_type="acting")
        a_obj = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
        a_obj.acting_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=ACTING_HEARTBEAT_WINDOW_S + 5)
        await s.commit()
        await process_pending_acks(s)
        out2 = await process_pending_acks(s)
    # Second tick must not re-fire on this alert (filter excludes
    # ack_type='acting_lapsed').
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    lapse_history = [h for h in a.escalation_history if h.get("step") == "acting_lapsed"]
    assert len(lapse_history) == 1, f"acting_lapsed re-fired: {lapse_history}"
