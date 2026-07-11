"""System Incident Engine — contract tests.

Locks the design rules:
  • START on healthy → warning / degraded, OR warning → degraded
  • RESOLVE on X → healthy
  • Repeated same-severity ticks → silent (no second incident, no escalation noise)
  • 30 s debounce: a transient transition that recovers within the
    window writes nothing to the DB.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/app/backend")
os.environ.setdefault("NISCHINT_ROLE", "all")

from app.services import system_incident_engine as eng  # noqa: E402


@pytest.fixture(autouse=True)
def _shorten_debounce(monkeypatch):
    """30 s debounce is fine in production, but tests should run fast."""
    monkeypatch.setattr(eng, "START_DEBOUNCE_S", 0.05)
    eng._pending.clear()
    yield
    eng._pending.clear()


@pytest.fixture
def fake_session_factory():
    """Stub async_session_factory + capture calls into _open / _resolve / _escalate."""
    calls = {"open": [], "resolve": 0, "escalate": []}

    async def fake_open(session, *, severity, source, metric):
        calls["open"].append({"severity": severity, "source": source, "metric": metric})

    async def fake_escalate(session, *, severity):
        calls["escalate"].append(severity)

    async def fake_resolve(session):
        calls["resolve"] += 1

    async def fake_capture():
        return {"taken_at": "stub"}

    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=fake_session)

    with patch("app.db.session.async_session", factory), \
         patch.object(eng, "_open_incident", side_effect=fake_open), \
         patch.object(eng, "_escalate_active", side_effect=fake_escalate), \
         patch.object(eng, "_resolve_active", side_effect=fake_resolve), \
         patch.object(eng, "_capture_snapshot", side_effect=fake_capture):
        yield calls


@pytest.mark.asyncio
async def test_healthy_to_warning_starts_after_debounce(fake_session_factory):
    await eng.handle_transition(prev_severity="healthy", new_severity="warning",
                                 source="scheduler", metric="error_count")
    # Pending — no DB write yet.
    assert fake_session_factory["open"] == []
    await asyncio.sleep(0.12)
    assert len(fake_session_factory["open"]) == 1
    assert fake_session_factory["open"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_transient_spike_is_debounced_silently(fake_session_factory):
    await eng.handle_transition(prev_severity="healthy", new_severity="degraded",
                                 source="ai", metric="p95_ms")
    # Recovery within debounce window — must cancel pending.
    await eng.handle_transition(prev_severity="degraded", new_severity="healthy",
                                 source="ai", metric=None)
    await asyncio.sleep(0.1)
    # No incident written. The resolve call also a no-op (no active row).
    assert fake_session_factory["open"] == []


@pytest.mark.asyncio
async def test_warning_to_degraded_escalates_existing_incident(fake_session_factory):
    await eng.handle_transition(prev_severity="warning", new_severity="degraded",
                                 source="scheduler", metric="drift_p95")
    await asyncio.sleep(0.05)
    assert fake_session_factory["escalate"] == ["degraded"]
    assert fake_session_factory["open"] == []


@pytest.mark.asyncio
async def test_resolve_path_calls_resolve_active(fake_session_factory):
    await eng.handle_transition(prev_severity="degraded", new_severity="healthy",
                                 source="scheduler", metric=None)
    assert fake_session_factory["resolve"] == 1
    assert fake_session_factory["open"] == []


@pytest.mark.asyncio
async def test_repeated_degraded_within_existing_does_not_double_open(fake_session_factory):
    # First start
    await eng.handle_transition(prev_severity="healthy", new_severity="degraded",
                                 source="scheduler", metric="drift_p95")
    await asyncio.sleep(0.1)
    # Second tick — same severity, just an escalation no-op (already at peak)
    await eng.handle_transition(prev_severity="degraded", new_severity="degraded",
                                 source="scheduler", metric="missed_jobs")
    await asyncio.sleep(0.1)
    # Only ONE open call.
    assert len(fake_session_factory["open"]) == 1


def test_is_escalation_strict_ranking():
    assert eng._is_escalation("healthy", "warning") is True
    assert eng._is_escalation("warning", "degraded") is True
    assert eng._is_escalation("degraded", "warning") is False
    assert eng._is_escalation("warning", "warning") is False
    assert eng._is_escalation(None, "degraded") is True


def test_cancel_pending_drops_queued_start():
    eng._pending["start:scheduler"] = {"severity": "warning", "deadline": 999}
    eng.cancel_pending("scheduler")
    assert "start:scheduler" not in eng._pending
