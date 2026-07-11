"""NISCH-006 — Incident state machine: pure transition contract tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.incident_state_machine import (
    ALLOWED_TRANSITIONS,
    IncidentState,
    InvalidTransitionError,
    assert_valid_transition,
    is_valid_transition,
    transition,
)


ALL_STATES = list(IncidentState)


def _fake_incident(state: IncidentState) -> MagicMock:
    inc = MagicMock()
    inc.id = uuid.uuid4()
    inc.child_id = uuid.uuid4()
    inc.state = state.value
    inc.acknowledged_by = None
    inc.acknowledged_at = None
    inc.resolved_at = None
    inc.archived_at = None
    inc.updated_at = None
    return inc


# ── Pure validation surface ─────────────────────────────────────────
@pytest.mark.parametrize("from_state,to_state", [
    (IncidentState.DETECTED,     IncidentState.VALIDATING),
    (IncidentState.VALIDATING,   IncidentState.ESCALATED),
    (IncidentState.VALIDATING,   IncidentState.RESOLVED),
    (IncidentState.ESCALATED,    IncidentState.ACKNOWLEDGED),
    (IncidentState.ESCALATED,    IncidentState.RESOLVED),
    (IncidentState.ACKNOWLEDGED, IncidentState.RESOLVED),
    (IncidentState.RESOLVED,     IncidentState.ARCHIVED),
])
def test_valid_transitions_pass(from_state, to_state):
    assert is_valid_transition(from_state, to_state) is True
    assert_valid_transition(from_state, to_state)  # must not raise


def test_every_state_pair_outside_allowed_map_is_rejected():
    """Brute-force every (from, to) pair; reject everything not in
    ALLOWED_TRANSITIONS."""
    rejections = 0
    for f in ALL_STATES:
        for t in ALL_STATES:
            if t in ALLOWED_TRANSITIONS[f]:
                continue
            assert is_valid_transition(f, t) is False
            with pytest.raises(InvalidTransitionError) as exc:
                assert_valid_transition(f, t)
            assert f"{f.value} → {t.value}" in str(exc.value)
            rejections += 1
    # 6 states × 6 = 36 pairs; 7 are valid; 29 must be rejected.
    assert rejections == len(ALL_STATES) * len(ALL_STATES) - 7


def test_terminal_state_rejects_all_transitions():
    """ARCHIVED is terminal — nothing leaves it."""
    for t in ALL_STATES:
        assert is_valid_transition(IncidentState.ARCHIVED, t) is False


def test_no_self_loops_allowed():
    for s in ALL_STATES:
        assert is_valid_transition(s, s) is False


def test_cannot_skip_validating():
    """DETECTED cannot jump to anything except VALIDATING."""
    for t in ALL_STATES:
        if t is IncidentState.VALIDATING:
            continue
        assert is_valid_transition(IncidentState.DETECTED, t) is False


def test_cannot_acknowledge_without_escalation():
    """A still-VALIDATING incident cannot be ACKNOWLEDGED — only
    ESCALATED ones can."""
    assert is_valid_transition(IncidentState.VALIDATING, IncidentState.ACKNOWLEDGED) is False


def test_cannot_archive_directly():
    """Only RESOLVED → ARCHIVED is allowed."""
    for s in ALL_STATES:
        if s is IncidentState.RESOLVED:
            continue
        assert is_valid_transition(s, IncidentState.ARCHIVED) is False


# ── transition() persistence semantics ─────────────────────────────
@pytest.mark.asyncio
async def test_transition_persists_state_and_timestamps(monkeypatch):
    # Stub SSE/TTFA emitters so we don't hit the broadcaster.
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_sse", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_ttfa", lambda *a, **kw: None
    )
    inc = _fake_incident(IncidentState.DETECTED)
    session = MagicMock()
    session.flush = AsyncMock()

    event = await transition(session, inc, IncidentState.VALIDATING)

    assert inc.state == IncidentState.VALIDATING.value
    assert isinstance(inc.updated_at, datetime)
    assert event.from_state is IncidentState.DETECTED
    assert event.to_state   is IncidentState.VALIDATING
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_transition_to_acknowledged_stamps_actor(monkeypatch):
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_sse", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_ttfa", lambda *a, **kw: None
    )
    inc = _fake_incident(IncidentState.ESCALATED)
    actor = uuid.uuid4()
    session = MagicMock(); session.flush = AsyncMock()

    await transition(session, inc, IncidentState.ACKNOWLEDGED, actor_id=actor)

    assert inc.state == "acknowledged"
    assert inc.acknowledged_by == actor
    assert isinstance(inc.acknowledged_at, datetime)


@pytest.mark.asyncio
async def test_transition_to_resolved_stamps_resolved_at(monkeypatch):
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_sse", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_ttfa", lambda *a, **kw: None
    )
    inc = _fake_incident(IncidentState.ACKNOWLEDGED)
    session = MagicMock(); session.flush = AsyncMock()

    await transition(session, inc, IncidentState.RESOLVED)
    assert isinstance(inc.resolved_at, datetime)


@pytest.mark.asyncio
async def test_transition_to_archived_stamps_archived_at(monkeypatch):
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_sse", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_ttfa", lambda *a, **kw: None
    )
    inc = _fake_incident(IncidentState.RESOLVED)
    session = MagicMock(); session.flush = AsyncMock()

    await transition(session, inc, IncidentState.ARCHIVED)
    assert isinstance(inc.archived_at, datetime)


@pytest.mark.asyncio
async def test_transition_invalid_raises_and_does_not_flush(monkeypatch):
    inc = _fake_incident(IncidentState.RESOLVED)
    session = MagicMock(); session.flush = AsyncMock()

    with pytest.raises(InvalidTransitionError) as exc:
        await transition(session, inc, IncidentState.DETECTED)
    assert "resolved → detected" in str(exc.value)
    # State must NOT have changed; flush must NOT have been called.
    assert inc.state == "resolved"
    session.flush.assert_not_called()


# ── SSE event payload shape ────────────────────────────────────────
@pytest.mark.asyncio
async def test_transition_event_to_sse_shape(monkeypatch):
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_sse", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "app.services.incident_state_machine._emit_ttfa", lambda *a, **kw: None
    )
    inc = _fake_incident(IncidentState.DETECTED)
    session = MagicMock(); session.flush = AsyncMock()
    event = await transition(session, inc, IncidentState.VALIDATING)
    payload = event.to_sse()
    assert payload["type"] == "incident_state_change"
    assert payload["from"] == "detected"
    assert payload["to"]   == "validating"
    assert "incident_id" in payload
    assert "timestamp" in payload
