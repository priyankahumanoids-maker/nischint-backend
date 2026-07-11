"""Regression: alert_trigger — unified front door for guardian alerts.

Locked contract:
- One function. Single entry point. Always:
    1. Resolves guardian_ids (Guardian + Relationship tables, deduped).
    2. Applies dedup gate (Redis-first, in-memory fallback).
    3. Persists GuardianAlert with non-NULL user_id.
    4. Broadcasts SSE to every linked guardian.
    5. Hands off to guardian_notification_dispatcher for push + SMS.
    6. Stamps `[ALERT_TTFA]` log line with ttfa_ms.

These tests cover the front door in isolation — production migration of
the 13 legacy callsites lands in subsequent PRs.
"""
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import alert_trigger
from app.services.alert_trigger import (
    trigger_alert,
    reset_dedup_state,
    _dedup_should_skip,
)


# ── Pure dedup logic ──────────────────────────────────────────────────
class TestDedupGate:
    def setup_method(self):
        reset_dedup_state()

    def test_no_idempotency_key_never_dedups(self, monkeypatch):
        monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: False)
        for _ in range(5):
            assert _dedup_should_skip("voice", "u1", None, 30) is False

    def test_first_call_passes(self, monkeypatch):
        monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: False)
        assert _dedup_should_skip("voice", "u1", "ev-1", 30) is False

    def test_second_call_within_cooldown_skipped(self, monkeypatch):
        monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: False)
        _dedup_should_skip("voice", "u1", "ev-1", 30)  # warm
        assert _dedup_should_skip("voice", "u1", "ev-1", 30) is True

    def test_different_keys_independent(self, monkeypatch):
        monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: False)
        _dedup_should_skip("voice", "u1", "ev-A", 30)
        # Different idem key under same kind/user — must not be skipped
        assert _dedup_should_skip("voice", "u1", "ev-B", 30) is False
        # Different user — must not be skipped
        assert _dedup_should_skip("voice", "u2", "ev-A", 30) is False
        # Different kind — must not be skipped
        assert _dedup_should_skip("fall", "u1", "ev-A", 30) is False

    def test_zero_cooldown_disables_dedup(self, monkeypatch):
        monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: False)
        _dedup_should_skip("voice", "u1", "ev-1", 0)
        assert _dedup_should_skip("voice", "u1", "ev-1", 0) is False

    def test_redis_path_uses_set_nx(self, monkeypatch):
        """When Redis is up, dedup is via atomic SET NX EX — not LRU."""
        fake = MagicMock()
        fake.set = MagicMock(return_value=True)  # 1st call: SET succeeds → not a dup
        monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: True)
        monkeypatch.setattr(alert_trigger.redis_service, "_get_client", lambda: fake)
        assert _dedup_should_skip("voice", "u1", "ev-1", 30) is False
        fake.set.assert_called_once()
        # Verify NX + EX flags passed correctly
        kwargs = fake.set.call_args.kwargs
        assert kwargs.get("nx") is True
        assert kwargs.get("ex") == 30

        # 2nd call: SET NX returns False (key exists) → dup
        fake.set = MagicMock(return_value=False)
        assert _dedup_should_skip("voice", "u1", "ev-1", 30) is True


# ── Integration: trigger_alert end-to-end ────────────────────────────
@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Force in-memory dedup + reset between tests."""
    monkeypatch.setattr(alert_trigger.redis_service, "is_available", lambda: False)
    reset_dedup_state()
    yield
    reset_dedup_state()


def _stub_session(guardian_ids: list[str], child_name: str = "TestKid"):
    """Build a session mock that returns the given guardian_ids when
    `_resolve_guardian_ids` runs against it."""
    session = MagicMock()
    # _resolve_guardian_ids walks: User lookup → Guardian rows → Relationship rows.
    user_obj = MagicMock(); user_obj.full_name = child_name
    user_lookup = MagicMock(); user_lookup.scalar_one_or_none.return_value = user_obj
    guardian_rows = MagicMock(); guardian_rows.scalars.return_value.all.return_value = []
    rel_rows = MagicMock()
    fake_rels = []
    for gid in guardian_ids:
        r = MagicMock()
        r.guardian_id = uuid.UUID(gid) if isinstance(gid, str) and "-" in gid else gid
        fake_rels.append(r)
    rel_rows.scalars.return_value.all.return_value = fake_rels
    session.execute = AsyncMock(side_effect=[user_lookup, guardian_rows, rel_rows])
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_dispatches_to_all_guardians_with_alert_row():
    g1 = str(uuid.uuid4()); g2 = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    session = _stub_session([g1, g2], child_name="Kid")
    captured = []

    async def fake_b2u(uid, etype, payload): captured.append((uid, etype, payload))
    async def fake_dispatch(*a, **kw): return {"dispatched": True}

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        result = await trigger_alert(
            session,
            kind="voice_distress",
            user_id=child_id,
            severity="critical",
            message="Test alert",
            location={"lat": 1.0, "lng": 2.0},
        )

    assert result.dispatched is True
    assert result.guardians_notified == 2
    assert result.dedup_skipped is False
    assert isinstance(result.ttfa_ms, int)
    # Both guardians got the SSE event
    assert {uid for uid, _, _ in captured} == {g1, g2}
    # Event type defaults to "safety_alert"
    assert all(et == "safety_alert" for _, et, _ in captured)
    # SSE body shape
    body = captured[0][2]
    assert body["child_id"] == child_id
    assert body["child_name"] == "Kid"
    assert body["severity"] == "critical"
    assert body["type"] == "VOICE_DISTRESS"
    # GuardianAlert + SafetyIncident + 3 SafetyIncidentEvent rows
    # (DETECTED creation, DETECTED→VALIDATING, VALIDATING→ESCALATED).
    # Total: 5 session.add calls.
    assert session.add.call_count == 5
    added = [c.args[0] for c in session.add.call_args_list]
    alert_arg = next(a for a in added if a.__class__.__name__ == "GuardianAlert")
    assert str(alert_arg.user_id) == child_id
    assert alert_arg.alert_type == "voice_distress"
    assert alert_arg.severity == "critical"
    incident_arg = next(a for a in added if a.__class__.__name__ == "SafetyIncident")
    assert incident_arg.incident_type == "voice_distress"
    event_args = [a for a in added if a.__class__.__name__ == "SafetyIncidentEvent"]
    assert len(event_args) == 3
    # Creation event has from_state=None.
    assert any(e.from_state is None and e.to_state == "detected" for e in event_args)
    assert any(e.from_state == "detected" and e.to_state == "validating" for e in event_args)
    assert any(e.from_state == "validating" and e.to_state == "escalated" for e in event_args)


@pytest.mark.asyncio
async def test_dedup_suppresses_within_cooldown():
    child_id = str(uuid.uuid4())
    g1 = str(uuid.uuid4())

    # Fresh session for each call (the stub is single-use).
    captured = []
    async def fake_b2u(uid, etype, payload): captured.append(uid)
    async def fake_dispatch(*a, **kw): return {}

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        r1 = await trigger_alert(
            _stub_session([g1]),
            kind="voice_distress", user_id=child_id, severity="critical",
            message="dupe-test",
            idempotency_key=f"event-{child_id}", cooldown_s=60,
        )
        r2 = await trigger_alert(
            _stub_session([g1]),
            kind="voice_distress", user_id=child_id, severity="critical",
            message="dupe-test",
            idempotency_key=f"event-{child_id}", cooldown_s=60,
        )

    assert r1.dispatched is True and r1.dedup_skipped is False
    assert r2.dispatched is False and r2.dedup_skipped is True
    assert r2.reason == "dedup_cooldown"
    # Only the first call broadcast — second call short-circuited.
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_persist_alert_false_skips_db_write():
    g1 = str(uuid.uuid4()); child_id = str(uuid.uuid4())
    session = _stub_session([g1])

    async def fake_b2u(*a, **kw): return None

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u):
        result = await trigger_alert(
            session,
            kind="arrived", user_id=child_id, severity="info",
            message="Child arrived safely",
            persist_alert=False,
        )

    assert result.dispatched is True
    assert result.alert_id is None
    # NISCH-006: persist_alert=False → no SafetyIncident either; both
    # transient and lifecycle paths are skipped together.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_no_guardians_still_returns_clean_result():
    """A child with zero linked guardians must NOT crash. Returns
    `dispatched=True, guardians_notified=0` so the caller can decide
    what to do (e.g. log, fallback to operators)."""
    child_id = str(uuid.uuid4())
    session = _stub_session([])  # zero guardians

    async def fake_b2u(*a, **kw): return None
    async def fake_dispatch(*a, **kw): return {}

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        result = await trigger_alert(
            session,
            kind="voice_distress", user_id=child_id, severity="critical",
            message="No-guardians edge case",
        )

    assert result.dispatched is True
    assert result.guardians_notified == 0
    # Audit trail still created when no one is notified.
    # NISCH-006: SafetyIncident + alert + 3 transition events = 5 adds.
    assert session.add.call_count == 5


@pytest.mark.asyncio
async def test_invalid_user_id_does_not_crash():
    """Non-UUID user_id must not propagate as a 500. _resolve_guardian_ids
    swallows the parse error and returns an empty list."""
    session = _stub_session([])  # placeholder; first execute will short-circuit

    # Override the session so _resolve_guardian_ids tries uuid.UUID() first.
    s = MagicMock()
    s.execute = AsyncMock(side_effect=ValueError("nope"))
    s.add = MagicMock(); s.flush = AsyncMock()

    async def fake_b2u(*a, **kw): return None
    async def fake_dispatch(*a, **kw): return {}

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        result = await trigger_alert(
            s,
            kind="voice_distress", user_id="not-a-uuid", severity="critical",
            message="invalid id test",
        )

    # We don't crash. Resolver returns empty list → no fan-out, but the
    # function returns cleanly.
    assert result.guardians_notified == 0


@pytest.mark.asyncio
async def test_ttfa_log_line_emitted(caplog):
    child_id = str(uuid.uuid4())
    g1 = str(uuid.uuid4())
    session = _stub_session([g1])

    async def fake_b2u(*a, **kw): return None
    async def fake_dispatch(*a, **kw): return {}

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        import logging
        caplog.set_level(logging.INFO, logger="app.services.alert_trigger")
        result = await trigger_alert(
            session,
            kind="voice_distress", user_id=child_id, severity="critical",
            message="ttfa test",
        )

    assert any("[ALERT_TTFA]" in rec.message for rec in caplog.records)
    assert result.ttfa_ms >= 0



# ── NISCH-002B: co-location suppression wired into trigger_alert ───
@pytest.mark.asyncio
async def test_co_location_suppresses_geofence_breach_for_nearby_guardian():
    """Geofence breach + guardian standing right next to child → that
    guardian gets filtered out of the SSE fan-out. Critical kinds are
    untouched by this filter."""
    from datetime import datetime, timezone
    g_near = str(uuid.uuid4())
    g_far  = str(uuid.uuid4())
    child_id = str(uuid.uuid4())

    # Build a session stub that mimics the 4 execute() calls the
    # suppressible path performs:
    #   1. child User lookup    (in _resolve_guardian_ids)
    #   2. Guardian rows        (none)
    #   3. Relationship rows    (two)
    #   4. User.in_(guardian_ids) lookup for proximity
    session = MagicMock()

    child_user = MagicMock(); child_user.full_name = "Kid"
    user_lookup = MagicMock(); user_lookup.scalar_one_or_none.return_value = child_user

    g_rows = MagicMock(); g_rows.scalars.return_value.all.return_value = []

    rel_rows = MagicMock()
    r1 = MagicMock(); r1.guardian_id = uuid.UUID(g_near)
    r2 = MagicMock(); r2.guardian_id = uuid.UUID(g_far)
    rel_rows.scalars.return_value.all.return_value = [r1, r2]

    now = datetime.now(timezone.utc)
    near_user = MagicMock(); near_user.id = uuid.UUID(g_near)
    near_user.last_known_lat = 12.97; near_user.last_known_lng = 77.59
    near_user.last_known_at = now
    far_user = MagicMock(); far_user.id = uuid.UUID(g_far)
    far_user.last_known_lat = 13.08; far_user.last_known_lng = 80.27  # Chennai
    far_user.last_known_at = now
    proximity_lookup = MagicMock()
    proximity_lookup.scalars.return_value.all.return_value = [near_user, far_user]

    session.execute = AsyncMock(side_effect=[
        user_lookup, g_rows, rel_rows,
        # NISCH-011 wiring: assess_and_record loads baseline via a
        # 4th session.execute inside open_incident_for_alert (BEFORE
        # the proximity check). Cold-start returns no row → detector
        # returns `cold_start` → no dispatch influence. The mock
        # mirrors that contract.
        MagicMock(first=MagicMock(return_value=None)),
        proximity_lookup,
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    captured: list[str] = []
    async def fake_b2u(uid, etype, payload):
        captured.append(uid)
    async def fake_dispatch(*a, **kw): return None

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        result = await trigger_alert(
            session,
            kind="geofence_breach",
            user_id=child_id,
            severity="warning",
            message="Child left safe zone",
            location={"lat": 12.97, "lng": 77.59},
        )

    assert g_far in captured
    assert g_near not in captured
    assert result.guardians_notified == 1


@pytest.mark.asyncio
async def test_co_location_does_NOT_suppress_critical_kinds():
    """A guardian standing next to child during an SOS still gets the
    push — life-safety kinds bypass proximity filter entirely."""
    g_near = str(uuid.uuid4())
    child_id = str(uuid.uuid4())

    # voice_distress is NOT suppressible, so the proximity DB lookup
    # never runs — only the 3 execute() calls _resolve_guardian_ids does.
    session = _stub_session([g_near])

    captured: list[str] = []
    async def fake_b2u(uid, etype, payload):
        captured.append(uid)
    async def fake_dispatch(*a, **kw): return None

    with patch("app.services.event_broadcaster.broadcaster.broadcast_to_user", new=fake_b2u), \
         patch("app.services.guardian_notification_dispatcher.dispatch_guardian_alert", new=fake_dispatch):
        result = await trigger_alert(
            session,
            kind="voice_distress",
            user_id=child_id,
            severity="critical",
            message="DISTRESS",
            location={"lat": 12.97, "lng": 77.59},
        )

    assert g_near in captured
    assert result.guardians_notified == 1
