"""HC-02 — by-device endpoint + admin dependents listing tests.

Locks:
  1. Admin/operator role can call `by-device` for anyone (no guardian gate).
  2. Non-privileged caller cannot read another user's by-device unless
     they are a registered guardian.
  3. `/admin/dependents` requires admin or operator role.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import health_signals as hs


def _user(role: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000aaa"),
        role=role,
    )


@pytest.mark.asyncio
async def test_by_device_admin_can_read_anyone(monkeypatch):
    """admin role bypasses guardian gate on by-device."""
    async def _is_guard(*a, **kw):
        raise AssertionError("guardian gate must NOT fire for admin")
    monkeypatch.setattr(hs, "_is_guardian_of", _is_guard)

    session = MagicMock()
    # session.execute(...).fetchall() returns []
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)

    out = await hs.get_dependent_signals_by_device(
        dependent_id="00000000-0000-0000-0000-0000000000ff",
        hours=24,
        user=_user(role="admin"),
        session=session,
    )
    assert out["dependent_id"] == "00000000-0000-0000-0000-0000000000ff"
    assert out["devices"] == []


@pytest.mark.asyncio
async def test_by_device_operator_can_read_anyone(monkeypatch):
    """operator role bypasses guardian gate on by-device."""
    async def _is_guard(*a, **kw):
        raise AssertionError("guardian gate must NOT fire for operator")
    monkeypatch.setattr(hs, "_is_guardian_of", _is_guard)

    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)

    out = await hs.get_dependent_signals_by_device(
        dependent_id="00000000-0000-0000-0000-0000000000ff",
        hours=24,
        user=_user(role="operator"),
        session=session,
    )
    assert out["devices"] == []


@pytest.mark.asyncio
async def test_by_device_unprivileged_blocked_when_not_guardian(monkeypatch):
    """A guardian-less peer caller cannot read someone else's by-device."""
    from fastapi import HTTPException

    async def _is_guard(*a, **kw):
        return False
    monkeypatch.setattr(hs, "_is_guardian_of", _is_guard)

    with pytest.raises(HTTPException) as exc:
        await hs.get_dependent_signals_by_device(
            dependent_id="00000000-0000-0000-0000-0000000000ff",
            hours=24,
            user=_user(role="user"),
            session=MagicMock(),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_by_device_groups_rows_by_device_id():
    """Rows from PG are bucketed by device_id with sample/breach counters."""
    from datetime import datetime, timezone

    t0 = datetime(2026, 5, 30, 5, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 5, 30, 5, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 30, 5, 2, tzinfo=timezone.utc)

    rows = [
        SimpleNamespace(device_id="dev-A", device_model="Pixel Watch 2",
                        signal_type="heart_rate", value=72.0, unit="bpm",
                        ts=t0, breach_tag=None),
        SimpleNamespace(device_id="dev-A", device_model="Pixel Watch 2",
                        signal_type="heart_rate", value=135.0, unit="bpm",
                        ts=t1, breach_tag="HR_HIGH"),
        SimpleNamespace(device_id="dev-B", device_model="Apple Watch S9",
                        signal_type="spo2", value=97.0, unit="%",
                        ts=t2, breach_tag=None),
        SimpleNamespace(device_id=None, device_model=None,
                        signal_type="heart_rate", value=75.0, unit="bpm",
                        ts=t2, breach_tag=None),  # legacy → 'unknown'
    ]

    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=result)

    out = await hs.get_dependent_signals_by_device(
        dependent_id="any",
        hours=24,
        user=_user(role="admin"),
        session=session,
    )
    devs = {d["device_id"] or "unknown": d for d in out["devices"]}
    assert "dev-A" in devs and "dev-B" in devs and "unknown" in devs
    assert devs["dev-A"]["sample_count"] == 2
    assert devs["dev-A"]["breach_count"] == 1
    assert devs["dev-A"]["device_model"] == "Pixel Watch 2"
    assert devs["dev-B"]["sample_count"] == 1
    assert devs["dev-B"]["breach_count"] == 0
    # unknown bucket — model defaults to 'unknown'
    assert devs["unknown"]["device_model"] == "unknown"
    assert devs["unknown"]["sample_count"] == 1


@pytest.mark.asyncio
async def test_admin_dependents_requires_role():
    """list_dependents_with_signals must reject non-admin / non-operator."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await hs.list_dependents_with_signals(
            hours=168,
            session=MagicMock(),
            user=_user(role="user"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_dependents_returns_shape():
    """Returns the dependent envelope with normalized fields."""
    from datetime import datetime, timezone

    ts = datetime(2026, 5, 30, 5, 0, tzinfo=timezone.utc)
    row = SimpleNamespace(
        user_id=uuid.UUID("00000000-0000-0000-0000-0000000000bb"),
        sample_count=42, device_count=2, breach_count=3,
        last_seen=ts,
        full_name="Kid Test", email="kid@test.com",
    )
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = [row]
    session.execute = AsyncMock(return_value=result)

    out = await hs.list_dependents_with_signals(
        hours=168, session=session, user=_user(role="admin"),
    )
    assert out["hours"] == 168
    assert len(out["dependents"]) == 1
    d = out["dependents"][0]
    assert d["user_id"] == "00000000-0000-0000-0000-0000000000bb"
    assert d["sample_count"] == 42
    assert d["device_count"] == 2
    assert d["breach_count"] == 3
    assert d["full_name"] == "Kid Test"
    assert d["email"] == "kid@test.com"
    assert d["last_seen"] == ts.isoformat()
