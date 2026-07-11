"""SB-04 — `behavior_ai._load_baseline_dual` dual-read tests.

Locked invariants:
  1. `_band_std` — pure function, σ ≈ (upper - lower) / 4, floored
     at MIN_BAND_STD (0.1).
  2. **device_baselines preferred when present** — the consumer
     reads the new band-derived stats, NOT the legacy EMA.
  3. **behavior_baselines used as fallback** — when device_baselines
     has no matching row, the legacy table fills the gap.
  4. **Returns None when BOTH sources empty** — caller's
     MIN_SAMPLES_FOR_BASELINE gate trips cleanly.
  5. **Returns None when movement OR interaction couldn't be
     filled** — anomaly detection needs both; a half-filled
     baseline is unusable.
  6. **sample_count provenance** — legacy when legacy has it,
     synthesised `MIN_SAMPLES_FOR_BASELINE` when only device_baselines.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.behavior_ai import (
    MIN_SAMPLES_FOR_BASELINE,
    _band_std,
    _BaselineRow,
    _load_baseline_dual,
    _MIN_BAND_STD,
)


# ── _band_std ──────────────────────────────────────────────────


def test_band_std_normal_band():
    """Width = 4.0 → σ = 1.0."""
    assert _band_std(0.0, 4.0) == 1.0


def test_band_std_narrow_band_floored():
    """Width = 0 → σ floored at MIN_BAND_STD."""
    assert _band_std(1.0, 1.0) == _MIN_BAND_STD


def test_band_std_none_inputs():
    """Defensive — None lower/upper are treated as 0.0."""
    assert _band_std(None, None) == _MIN_BAND_STD


def test_band_std_negative_band_floored():
    """Inverted band (data anomaly) — still floored, not negative."""
    assert _band_std(5.0, 1.0) == _MIN_BAND_STD


# ── _load_baseline_dual ────────────────────────────────────────


def _mock_session(*, device_rows: list, legacy_row):
    """Build an AsyncSession mock returning (device_baselines fetch,
    behavior_baselines fetch). Order of execute() calls is locked
    by the helper: device_baselines first, then behavior_baselines."""
    session = MagicMock()
    fetched: list = []

    async def _execute(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        if "FROM device_baselines" in sql:
            result.fetchall.return_value = list(device_rows)
        elif "FROM behavior_baselines" in sql:
            result.fetchone.return_value = legacy_row
        else:
            raise AssertionError(f"unexpected SQL: {sql[:80]}")
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session


@pytest.mark.asyncio
async def test_returns_none_when_both_sources_empty():
    session = _mock_session(device_rows=[], legacy_row=None)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out is None


@pytest.mark.asyncio
async def test_legacy_only_fallback_returns_legacy_values():
    legacy = SimpleNamespace(
        avg_movement=1.5, std_movement=0.4,
        avg_location_switch=0.3, std_location_switch=0.1,
        avg_interaction_rate=4.0, std_interaction_rate=1.2,
        sample_count=20,
    )
    session = _mock_session(device_rows=[], legacy_row=legacy)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert isinstance(out, _BaselineRow)
    assert out.avg_movement == 1.5
    assert out.std_movement == 0.4
    assert out.avg_interaction_rate == 4.0
    assert out.sample_count == 20


@pytest.mark.asyncio
async def test_device_baselines_preferred_over_legacy():
    """device_baselines wins when present — the band-derived σ
    overrides the legacy std."""
    device_rows = [
        SimpleNamespace(metric="movement",
                        expected_value=2.0,
                        lower_band=1.0, upper_band=3.0),
        SimpleNamespace(metric="interaction_rate",
                        expected_value=8.0,
                        lower_band=4.0, upper_band=12.0),
    ]
    legacy = SimpleNamespace(
        avg_movement=99.9, std_movement=99.9,      # noise — must be ignored
        avg_location_switch=0.5, std_location_switch=0.2,
        avg_interaction_rate=99.9, std_interaction_rate=99.9,  # noise
        sample_count=10,
    )
    session = _mock_session(device_rows=device_rows, legacy_row=legacy)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out.avg_movement == 2.0
    assert out.std_movement == _band_std(1.0, 3.0)    # = 0.5
    assert out.avg_interaction_rate == 8.0
    assert out.std_interaction_rate == _band_std(4.0, 12.0)  # = 2.0
    # location_switch had no device_baselines row → fall back to legacy
    assert out.avg_location_switch == 0.5
    assert out.std_location_switch == 0.2


@pytest.mark.asyncio
async def test_partial_device_baselines_fills_remainder_from_legacy():
    """Only `movement` in device_baselines — interaction_rate and
    location_switch fall through to legacy."""
    device_rows = [
        SimpleNamespace(metric="movement",
                        expected_value=2.5,
                        lower_band=1.5, upper_band=3.5),
    ]
    legacy = SimpleNamespace(
        avg_movement=99.9, std_movement=99.9,
        avg_location_switch=0.4, std_location_switch=0.15,
        avg_interaction_rate=6.0, std_interaction_rate=1.0,
        sample_count=15,
    )
    session = _mock_session(device_rows=device_rows, legacy_row=legacy)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out.avg_movement == 2.5
    assert out.avg_interaction_rate == 6.0           # from legacy
    assert out.avg_location_switch == 0.4            # from legacy


@pytest.mark.asyncio
async def test_device_baselines_only_synthesises_sample_count():
    """No legacy row at all — sample_count synthesised to
    MIN_SAMPLES_FOR_BASELINE so the consumer's readiness gate doesn't
    reject a perfectly good baseline."""
    device_rows = [
        SimpleNamespace(metric="movement",
                        expected_value=1.0,
                        lower_band=0.5, upper_band=1.5),
        SimpleNamespace(metric="interaction_rate",
                        expected_value=5.0,
                        lower_band=3.0, upper_band=7.0),
    ]
    session = _mock_session(device_rows=device_rows, legacy_row=None)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out is not None
    assert out.sample_count == MIN_SAMPLES_FOR_BASELINE


@pytest.mark.asyncio
async def test_returns_none_when_movement_unfilled():
    """Only location_switch present — anomaly detection needs both
    movement AND interaction, so the helper returns None."""
    device_rows = [
        SimpleNamespace(metric="location_switch",
                        expected_value=0.3,
                        lower_band=0.1, upper_band=0.5),
    ]
    session = _mock_session(device_rows=device_rows, legacy_row=None)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out is None


@pytest.mark.asyncio
async def test_returns_none_when_interaction_unfilled():
    device_rows = [
        SimpleNamespace(metric="movement",
                        expected_value=1.0,
                        lower_band=0.5, upper_band=1.5),
    ]
    session = _mock_session(device_rows=device_rows, legacy_row=None)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out is None


@pytest.mark.asyncio
async def test_device_baselines_with_none_expected_value_falls_through():
    """A device_baselines row exists for `movement` but
    `expected_value` is NULL (incomplete write) — fall through to
    legacy for that metric."""
    device_rows = [
        SimpleNamespace(metric="movement",
                        expected_value=None,
                        lower_band=0.5, upper_band=1.5),
        SimpleNamespace(metric="interaction_rate",
                        expected_value=5.0,
                        lower_band=3.0, upper_band=7.0),
    ]
    legacy = SimpleNamespace(
        avg_movement=1.7, std_movement=0.4,
        avg_location_switch=0.3, std_location_switch=0.1,
        avg_interaction_rate=99.9, std_interaction_rate=99.9,
        sample_count=10,
    )
    session = _mock_session(device_rows=device_rows, legacy_row=legacy)
    out = await _load_baseline_dual(session, "dev-1", 14)
    assert out.avg_movement == 1.7              # legacy used as fallback
    assert out.avg_interaction_rate == 5.0      # device_baselines used
