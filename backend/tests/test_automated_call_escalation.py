"""Twilio automated_call escalation step — contract tests.

Locks the critical invariants:
  1. `ack_type IS NULL` gate — a call is NEVER placed once any
     human has acknowledged (even `seen`). Wrong automation = worst
     automation in this domain.
  2. Cooldown: a parked `escalated` alert can't place a call more
     than once per AUTOMATED_CALL_COOLDOWN_S (60s).
  3. No guardians with E.164 phones → graceful skip, no crash.
  4. History log captures each attempt (redacted phone, ok flag) so
     the operator drill-down can see what we actually tried.
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.guardian import GuardianAlert
from app.models.user import User
from app.services import alert_ack_engine as engine
from app.services.alert_ack_engine import (
    _trigger_automated_call,
    mark_for_ack,
    AUTOMATED_CALL_COOLDOWN_S,
)


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


async def _seed_child_with_alert(s, *, with_phone=True):
    u = User(
        id=uuid.uuid4(),
        email=f"call+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="Call Test", password_hash="x", role="child",
    )
    s.add(u)
    await s.flush()
    if with_phone:
        await s.execute(text(
            "INSERT INTO guardians (id, user_id, name, phone, email, "
            "relationship, notification_pref, is_active, created_at) "
            "VALUES (:g, :u, 'Mom', '+15555551234', 'mom@x', 'parent', "
            ":np, TRUE, NOW())"
        ), {"g": str(uuid.uuid4()), "u": str(u.id), "np": json.dumps({"push": True})})
    a = GuardianAlert(
        session_id=None, user_id=u.id,
        alert_type="emergency", severity="critical",
        message="t", details="d", recommendation="r",
    )
    s.add(a)
    await s.flush()
    await mark_for_ack(s, a)
    return a, u


@pytest.mark.asyncio
async def test_call_fires_when_pending_and_phone_present(db):
    with patch("app.services.sms_service.make_voice_call", return_value=True) as mk:
        async with db() as s:
            a, _u = await _seed_child_with_alert(s, with_phone=True)
            await s.commit()
            aid = a.id
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
            await _trigger_automated_call(s, alert, datetime.now(timezone.utc))
            await s.commit()
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
    assert mk.call_count == 1
    kwargs = mk.call_args.kwargs
    assert kwargs["to"] == "+15555551234"
    assert kwargs["event_id"] == str(aid)
    assert alert.last_automated_call_at is not None
    last = (alert.escalation_history or [])[-1]
    assert last["step"] == "automated_call_attempt"
    assert last["placed"] == 1
    # Phone is redacted in the audit log.
    assert last["attempts"][0]["phone"].endswith("1234")
    assert last["attempts"][0]["phone"].startswith("*")


@pytest.mark.asyncio
async def test_call_blocked_when_ack_type_is_set(db):
    """The core safety invariant: once a human has even `seen` the
    alert, physical escalation MUST stop. Otherwise we'd phone a
    guardian who's already on it."""
    with patch("app.services.sms_service.make_voice_call", return_value=True) as mk:
        async with db() as s:
            a, _u = await _seed_child_with_alert(s, with_phone=True)
            a.ack_type = "seen"  # human has responded
            await s.commit()
            aid = a.id
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
            await _trigger_automated_call(s, alert, datetime.now(timezone.utc))
            await s.commit()
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
    assert mk.call_count == 0
    assert alert.last_automated_call_at is None


@pytest.mark.asyncio
async def test_call_skips_if_cooldown_active(db):
    """Parked-at-escalated alerts can't dial every tick — that would
    be automation abuse."""
    with patch("app.services.sms_service.make_voice_call", return_value=True) as mk:
        async with db() as s:
            a, _u = await _seed_child_with_alert(s, with_phone=True)
            # Pretend we just called it 10s ago — cooldown is 60s.
            a.last_automated_call_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            await s.commit()
            aid = a.id
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
            await _trigger_automated_call(s, alert, datetime.now(timezone.utc))
            await s.commit()
    assert mk.call_count == 0


@pytest.mark.asyncio
async def test_call_skips_gracefully_when_no_phone(db):
    with patch("app.services.sms_service.make_voice_call", return_value=True) as mk:
        async with db() as s:
            a, _u = await _seed_child_with_alert(s, with_phone=False)
            await s.commit()
            aid = a.id
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
            await _trigger_automated_call(s, alert, datetime.now(timezone.utc))
            await s.commit()
        async with db() as s:
            alert = (await s.execute(
                select(GuardianAlert).where(GuardianAlert.id == aid)
            )).scalar_one()
    assert mk.call_count == 0
    # No crash, no call, no stamp.
    assert alert.last_automated_call_at is None


@pytest.mark.asyncio
async def test_cooldown_constant_matches_doc():
    """The cooldown is a safety + cost constant. A regression that
    shrinks it could spam a guardian and burn Twilio credit."""
    assert AUTOMATED_CALL_COOLDOWN_S >= 30


def test_ack_engine_still_schedules_automated_call_step():
    """Escalation list order is a state-machine invariant; the
    drilling-down panel and operator runbook depend on it."""
    assert engine.ESCALATION_STEPS == [
        "louder_push",
        "automated_call",
        "authority_api",
        "ops_terminal",
    ]
