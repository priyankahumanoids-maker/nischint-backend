"""Tests for the Louder Push action plug-in.

Locks the contract:
  • Escalation to step `louder_push` triggers `_trigger_louder_push`.
  • Cooldown blocks repeat within 15 s.
  • Already-acked alerts skip dispatch (race-window safety).
  • Dispatcher is called with `louder=True`.
  • FCM payload carries the critical-channel profile.
  • Tick failure path is swallowed (best-effort dispatch).
"""
import pytest
import pytest_asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.guardian import GuardianSession, GuardianAlert
from app.models.user import User
from app.services.alert_ack_engine import (
    mark_for_ack, process_pending_acks, _trigger_louder_push,
    LOUDER_PUSH_COOLDOWN_S,
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


async def _seed_alert(s, *, severity: str = "critical") -> GuardianAlert:
    u = User(
        id=uuid.uuid4(),
        email=f"loud+{uuid.uuid4().hex[:8]}@nischint.test",
        full_name="Loud Test", password_hash="x", role="child",
    )
    s.add(u)
    await s.flush()
    gs = GuardianSession(
        id=uuid.uuid4(), user_id=u.id, status="active",
        started_at=datetime.now(timezone.utc),
        previous_update_at=datetime.now(timezone.utc),
        risk_level="HIGH", risk_score=8, zone_name="default",
        current_location={"lat": 12.97, "lng": 77.59},
    )
    s.add(gs)
    await s.flush()
    a = GuardianAlert(
        session_id=gs.id, user_id=u.id,
        alert_type="emergency", severity=severity,
        message="Test", details="d", recommendation="r",
    )
    s.add(a)
    await s.flush()
    return a


# ── 1. Escalation triggers louder_push dispatch ─────────────────────
@pytest.mark.asyncio
async def test_escalation_to_louder_push_calls_dispatcher(db):
    """When the tick advances an alert to step 1 (louder_push), the
    dispatcher must be called with `louder=True`."""
    async with db() as s:
        alert = await _seed_alert(s)
        await mark_for_ack(s, alert)
        # Force the deadline into the past so the next tick escalates.
        alert.ack_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        await s.commit()
    fake_dispatch = AsyncMock(return_value={"dispatched": True,
                                              "guardians_count": 0,
                                              "push_sent": 0,
                                              "sms_sent": 0,
                                              "errors": []})
    with patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert",
                fake_dispatch):
        async with db() as s:
            await process_pending_acks(s)
    # Dispatcher was called exactly once with louder=True.
    assert fake_dispatch.await_count == 1, \
        f"dispatch called {fake_dispatch.await_count} times, expected 1"
    _args, kwargs = fake_dispatch.await_args
    assert kwargs.get("louder") is True
    # last_louder_push_at was stamped.
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.last_louder_push_at is not None
    assert a.escalation_step == 1


# ── 2. Cooldown blocks repeat within 15s ─────────────────────────────
@pytest.mark.asyncio
async def test_cooldown_blocks_repeat_within_window(db):
    """A second call to _trigger_louder_push within 15s must skip."""
    async with db() as s:
        alert = await _seed_alert(s)
        await mark_for_ack(s, alert)
        await s.commit()
    fake_dispatch = AsyncMock(return_value={"dispatched": True,
                                              "guardians_count": 0,
                                              "push_sent": 0,
                                              "errors": []})
    now = datetime.now(timezone.utc)
    with patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert",
                fake_dispatch):
        async with db() as s:
            a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            await _trigger_louder_push(s, a, now)
            await s.commit()
            # Refresh + immediate second call within cooldown.
            a2 = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            await _trigger_louder_push(s, a2, now + timedelta(seconds=10))
    # Dispatcher fired exactly once across both calls.
    assert fake_dispatch.await_count == 1, \
        f"cooldown failed, dispatch called {fake_dispatch.await_count}x"


# ── 3. After cooldown elapses, second call fires ────────────────────
@pytest.mark.asyncio
async def test_cooldown_releases_after_window(db):
    """A second call past the 15s window fires again."""
    async with db() as s:
        alert = await _seed_alert(s)
        await mark_for_ack(s, alert)
        await s.commit()
    fake_dispatch = AsyncMock(return_value={"dispatched": True,
                                              "guardians_count": 0,
                                              "push_sent": 0,
                                              "errors": []})
    base = datetime.now(timezone.utc)
    with patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert",
                fake_dispatch):
        async with db() as s:
            a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            await _trigger_louder_push(s, a, base)
            await s.commit()
            a2 = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            # Past the cooldown.
            await _trigger_louder_push(s, a2, base + timedelta(seconds=LOUDER_PUSH_COOLDOWN_S + 1))
    assert fake_dispatch.await_count == 2


# ── 4. Acked alerts skip dispatch (race-window safety) ──────────────
@pytest.mark.asyncio
async def test_acked_alert_skips_louder_push(db):
    """Even if the tick advances escalation_step, an already-acked
    alert must NOT re-broadcast."""
    async with db() as s:
        alert = await _seed_alert(s)
        await mark_for_ack(s, alert)
        # Pre-ACK by flipping status directly (simulate race).
        alert.ack_status = "acknowledged"
        alert.acked_at = datetime.now(timezone.utc)
        await s.commit()
    fake_dispatch = AsyncMock()
    with patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert",
                fake_dispatch):
        async with db() as s:
            a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            await _trigger_louder_push(s, a, datetime.now(timezone.utc))
    assert fake_dispatch.await_count == 0


# ── 5. Dispatcher failure does not crash the tick ───────────────────
@pytest.mark.asyncio
async def test_dispatcher_failure_swallowed(db):
    """A dispatch exception must be swallowed — the tick must keep
    running so other alerts get processed."""
    async with db() as s:
        alert = await _seed_alert(s)
        await mark_for_ack(s, alert)
        await s.commit()
    fake_dispatch = AsyncMock(side_effect=RuntimeError("FCM down"))
    with patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert",
                fake_dispatch):
        async with db() as s:
            a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
            # Must not raise.
            await _trigger_louder_push(s, a, datetime.now(timezone.utc))
    # The cooldown stamp is NOT set because dispatch failed before it.
    async with db() as s:
        a = (await s.execute(select(GuardianAlert).where(GuardianAlert.id == alert.id))).scalar_one()
    assert a.last_louder_push_at is None


# ── 6. Push payload carries louder_push=true (push_service unit) ─────
@pytest.mark.asyncio
async def test_send_push_to_tokens_louder_payload_shape():
    """The HTTP payload built by send_push_to_tokens must include the
    critical-channel profile when louder=True. We don't actually hit
    FCM — patch httpx and inspect the call."""
    from app.services import push_service
    fake_resp = type("R", (), {"status_code": 200, "text": "ok"})()

    captured = {}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return fake_resp

    with patch("app.services.push_service.httpx.AsyncClient", FakeClient), \
         patch("app.services.push_service._get_access_token", return_value="x"), \
         patch("app.services.push_service._record_token_success",
                AsyncMock()):
        sent = await push_service.send_push_to_tokens(
            ["token-12345678"], "T", "B",
            data={"alert_id": "a"},
            louder=True,
        )
    assert sent == 1
    payload = captured["payload"]["message"]
    assert payload["data"]["louder_push"] == "true"
    android = payload["android"]["notification"]
    assert android["channel_id"] == push_service.CRITICAL_SAFETY_CHANNEL_ID
    assert android["sound"] == "siren_loop"
    assert android["sticky"] is True
    assert android["default_vibrate_timings"] is False
    assert android["vibrate_timings"] == ["0s", "0.5s", "0.5s", "0.5s"]
    apns_aps = payload["apns"]["payload"]["aps"]
    assert apns_aps["sound"]["critical"] == 1
    assert apns_aps["interruption-level"] == "critical"


@pytest.mark.asyncio
async def test_send_push_to_tokens_normal_payload_shape():
    """Same call with louder=False must use the normal-channel profile."""
    from app.services import push_service
    fake_resp = type("R", (), {"status_code": 200, "text": "ok"})()
    captured = {}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return fake_resp

    with patch("app.services.push_service.httpx.AsyncClient", FakeClient), \
         patch("app.services.push_service._get_access_token", return_value="x"), \
         patch("app.services.push_service._record_token_success",
                AsyncMock()):
        await push_service.send_push_to_tokens(
            ["token-99999999"], "T", "B",
            data={"alert_id": "a"},
            channel_id="safety-alerts",
            louder=False,
        )
    payload = captured["payload"]["message"]
    assert "louder_push" not in payload["data"]
    android = payload["android"]["notification"]
    assert android["channel_id"] == push_service.GUARDIAN_ALERT_CHANNEL_ID
    assert android["sound"] == "default"
    apns_aps = payload["apns"]["payload"]["aps"]
    assert apns_aps["sound"] == "default"
    assert "interruption-level" not in apns_aps
