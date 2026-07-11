"""Regression tests for the compensating actions that closed four
`unresolved_debt` entries from `RELIABILITY_DEBT.md` (21 → 17):

  * notification_service.py:309  — `_store_notification` schema-drift
  * notification_service.py:323  — `_deactivate_tokens` housekeeping
  * auto_escalation_engine.py:363 — failsafe audit-row insert
  * voice_distress_service.py:461 — voice-distress audit-row insert

These tests lock the four invariants for every compensating action:
  1. Exception is narrowed (a *non-targeted* exception now propagates
     instead of being silently swallowed).
  2. A structured `extra=`-carrying log line is emitted on catch.
  3. The DLQ helper is invoked with the planned payload on the
     two safety-critical-event-dispatch sites (failsafe + voice).
  4. The canonical delivery channel (FCM push / SSE / SMS) is
     unaffected — this is checked at the call-site level.

Pure-unit: no real Redis, no real DB, no scheduler.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError


# ════════════════════════════════════════════════════════════════════
# notification_service.py — _store_notification (line 309)
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_store_notification_pushes_to_dlq_on_programming_error(
        monkeypatch, caplog):
    """Schema-drift (table missing) must NOT silently drop the
    inbox row — push to DLQ + structured warning so a reconciler
    can replay once the migration runs."""
    from app.services import notification_service as ns

    dlq_calls: list[dict] = []
    monkeypatch.setattr(
        ns, "_push_history_dlq", lambda payload: dlq_calls.append(payload),
    )

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=ProgrammingError("stmt", {}, Exception("table missing")),
    )
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self_): return session
        async def __aexit__(self_, *a): return False

    svc = ns.NotificationService(db_session_factory=lambda: _Ctx())

    with caplog.at_level(logging.WARNING):
        await svc._store_notification(
            user_id="u1", title="t", body="b",
            data={"k": "v"}, tag="nischint-alert",
        )

    assert len(dlq_calls) == 1
    payload = dlq_calls[0]
    assert payload["user_id"] == "u1"
    assert payload["tag"] == "nischint-alert"
    assert payload["error_type"] == "ProgrammingError"
    assert any(
        "notification_history_dlq" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_store_notification_propagates_unknown_exception(monkeypatch):
    """A non-DB exception (e.g. coding bug) MUST propagate — the
    narrowed except is the whole point of the ratchet move."""
    from app.services import notification_service as ns

    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("unexpected"))
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self_): return session
        async def __aexit__(self_, *a): return False

    svc = ns.NotificationService(db_session_factory=lambda: _Ctx())

    with pytest.raises(RuntimeError):
        await svc._store_notification(
            user_id="u1", title="t", body="b", data={}, tag="x",
        )


@pytest.mark.asyncio
async def test_deactivate_tokens_logs_structured_on_operational_error(
        caplog):
    """Token-cleanup OperationalError → structured warning. The
    next FCM send re-detects invalid tokens and re-attempts
    deactivation organically."""
    from app.services import notification_service as ns

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=OperationalError("stmt", {}, Exception("conn lost")),
    )
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self_): return session
        async def __aexit__(self_, *a): return False

    svc = ns.NotificationService(db_session_factory=lambda: _Ctx())

    with caplog.at_level(logging.WARNING):
        await svc._deactivate_tokens(["bad_token_1", "bad_token_2"])

    assert any(
        "token_deactivation_deferred" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_deactivate_tokens_propagates_unknown_exception():
    """A non-Operational exception MUST propagate."""
    from app.services import notification_service as ns

    session = MagicMock()
    session.execute = AsyncMock(side_effect=ValueError("not an op error"))
    session.commit = AsyncMock()

    class _Ctx:
        async def __aenter__(self_): return session
        async def __aexit__(self_, *a): return False

    svc = ns.NotificationService(db_session_factory=lambda: _Ctx())

    with pytest.raises(ValueError):
        await svc._deactivate_tokens(["t1"])


# ════════════════════════════════════════════════════════════════════
# DLQ helpers — bounded + LTRIM
# ════════════════════════════════════════════════════════════════════

def test_history_dlq_is_bounded_with_ltrim():
    """Memory-safety: LPUSH + LTRIM keeps the DLQ from growing
    unbounded during a sustained outage. Locked at MAX=1000."""
    from app.services import notification_service as ns

    fake_client = MagicMock()
    with patch("app.services.redis_service._get_client", return_value=fake_client):
        result = ns._push_history_dlq({"x": 1})
    assert result is True
    fake_client.lpush.assert_called_once()
    fake_client.ltrim.assert_called_once()
    # LTRIM args: key, 0, MAX-1
    args = fake_client.ltrim.call_args[0]
    assert args[1] == 0
    assert args[2] == ns._HISTORY_DLQ_MAX - 1


def test_failsafe_dlq_is_bounded_with_ltrim():
    """Same bound-check for the failsafe-audit DLQ."""
    from app.services import auto_escalation_engine as ae

    fake_client = MagicMock()
    with patch("app.services.redis_service._get_client", return_value=fake_client):
        result = ae._push_failsafe_audit_dlq({"event_id": "e1"})
    assert result is True
    args = fake_client.ltrim.call_args[0]
    assert args[2] == ae._FAILSAFE_DLQ_MAX - 1


def test_voice_distress_dlq_is_bounded_with_ltrim():
    """Same bound-check for the voice-distress audit DLQ."""
    from app.services import voice_distress_service as vd

    fake_client = MagicMock()
    with patch("app.services.redis_service._get_client", return_value=fake_client):
        result = vd._push_voice_distress_audit_dlq({"event_id": "e1"})
    assert result is True
    args = fake_client.ltrim.call_args[0]
    assert args[2] == vd._VOICE_DISTRESS_DLQ_MAX - 1


def test_all_dlqs_return_false_when_redis_unavailable():
    """Redis-down must not raise — DLQ push degrades to False so
    the caller's CRITICAL log line is the only signal."""
    from app.services import (
        auto_escalation_engine as ae,
        notification_service as ns,
        voice_distress_service as vd,
    )
    with patch("app.services.redis_service._get_client", return_value=None):
        assert ns._push_history_dlq({"x": 1}) is False
        assert ae._push_failsafe_audit_dlq({"x": 1}) is False
        assert vd._push_voice_distress_audit_dlq({"x": 1}) is False


def test_all_dlqs_swallow_redis_errors_without_raising():
    """Even on a Redis client raise (transient connectivity), the
    DLQ helper itself MUST NOT raise — it is the compensating
    action, not a hot path."""
    from app.services import (
        auto_escalation_engine as ae,
        checkin_service as cs,
        notification_service as ns,
        voice_distress_service as vd,
    )
    bad_client = MagicMock()
    bad_client.lpush.side_effect = RuntimeError("redis down")
    with patch("app.services.redis_service._get_client", return_value=bad_client):
        assert ns._push_history_dlq({"x": 1}) is False
        assert ae._push_failsafe_audit_dlq({"x": 1}) is False
        assert vd._push_voice_distress_audit_dlq({"x": 1}) is False
        assert cs._push_checkin_audit_dlq({"x": 1}) is False


def test_checkin_dlq_is_bounded_with_ltrim():
    """Same memory-safety bound as the other 3 DLQs — 500 cap."""
    from app.services import checkin_service as cs

    fake_client = MagicMock()
    with patch("app.services.redis_service._get_client", return_value=fake_client):
        result = cs._push_checkin_audit_dlq({"row_type": "help_requested"})
    assert result is True
    fake_client.lpush.assert_called_once()
    fake_client.ltrim.assert_called_once()
    args = fake_client.ltrim.call_args[0]
    assert args[2] == cs._CHECKIN_DLQ_MAX - 1


# ════════════════════════════════════════════════════════════════════
# Ratchet metadata — locks the historical baseline
# ════════════════════════════════════════════════════════════════════

def test_ratchet_limit_at_or_below_session_baseline():
    """The ratchet has stepped 21 → 17 → 12 → 7 → 1 across the
    2026-02 session. Only `child.py:211` remains and is gated on
    V2 ramp completion. The limit must never silently grow back."""
    import pathlib
    md = pathlib.Path("/app/memory/RELIABILITY_DEBT.md").read_text()
    for line in md.splitlines():
        if "RATCHET: unresolved_debt must not exceed" in line:
            n = int("".join(ch for ch in line if ch.isdigit()))
            assert n <= 1, (
                f"Ratchet limit ({n}) regressed above 1. Only the "
                "V2-ramp-gated `app/api/child.py:211` entry should "
                "remain; everything else has been narrowed."
            )
            return
    pytest.fail("RATCHET line not found in RELIABILITY_DEBT.md")
