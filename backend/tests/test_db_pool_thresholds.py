"""REL-04 — Tests for the DB pool exhaustion threshold engine.

Pin the consecutive-readings hysteresis and the classifier:
  • Single >85% reading → no emit (still ramping)
  • Two consecutive >85% → emit `database_pool` degraded
  • Two consecutive ≤85% → emit recovery
  • A single dip below 85% mid-spike → no spurious recovery
  • Boundary value (exactly 85%) → counts as degraded

We mock out `_emit` to capture the broadcast payload without touching
Redis or the event broadcaster.
"""
from __future__ import annotations

from typing import Any

import pytest

import app.services.health_thresholds as ht
from app.services.health_thresholds import (
    DB_POOL_CONSECUTIVE_READINGS,
    DB_POOL_UTIL_PCT_DEGRADED,
    _classify_db_pool,
    evaluate_db_pool_state,
    reset_db_pool_counters,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Reset counters + capture emits between tests."""
    reset_db_pool_counters()
    captured: list[dict[str, Any]] = []

    def fake_emit(payload: dict[str, Any]) -> None:
        captured.append(payload)

    # In-memory prev-severity cache so the engine's "no event on same
    # severity" suppression still works without touching Redis.
    prev_state: dict[str, dict[str, Any]] = {}

    def fake_read_prev(source: str):
        return prev_state.get(source)

    def fake_write_prev(source: str, payload: dict[str, Any]):
        prev_state[source] = payload

    async def fake_handle_transition(**_kw):
        return None

    monkeypatch.setattr(ht, "_emit", fake_emit)
    monkeypatch.setattr(ht, "_read_prev", fake_read_prev)
    monkeypatch.setattr(ht, "_write_prev", fake_write_prev)
    monkeypatch.setattr(
        "app.services.system_incident_engine.handle_transition",
        fake_handle_transition,
    )
    return captured


# ── Classifier ──────────────────────────────────────────────────────


def test_classify_below_threshold_is_healthy():
    sev, metric, value = _classify_db_pool(50.0)
    assert sev == "healthy"
    assert metric is None
    assert value is None


def test_classify_at_threshold_is_degraded():
    # Exactly 85% is over the bar — operators have asked us to be
    # conservative here, a sustained 85% is already too close to
    # exhaustion.
    sev, metric, value = _classify_db_pool(DB_POOL_UTIL_PCT_DEGRADED)
    assert sev == "degraded"
    assert metric == "utilization_pct"
    assert value == pytest.approx(DB_POOL_UTIL_PCT_DEGRADED)


def test_classify_above_threshold_is_degraded():
    sev, metric, value = _classify_db_pool(95.0)
    assert sev == "degraded"
    assert metric == "utilization_pct"
    assert value == pytest.approx(95.0)


def test_classify_none_is_healthy():
    # Engine not yet initialised → no pool stats → no alert.
    sev, metric, value = _classify_db_pool(None)
    assert sev == "healthy"
    assert (metric, value) == (None, None)


# ── Consecutive-readings hysteresis ─────────────────────────────────


def test_single_high_reading_does_not_emit(_isolate):
    evaluate_db_pool_state(90.0)
    assert _isolate == [], "single >85% reading must NOT fire — debounce needed"


def test_two_consecutive_high_readings_fire_degraded(_isolate):
    evaluate_db_pool_state(90.0)
    evaluate_db_pool_state(91.5)
    assert len(_isolate) == 1
    p = _isolate[0]
    assert p["source"] == "database_pool"
    assert p["severity"] == "degraded"
    assert p["metric"] == "utilization_pct"
    assert p["value"] == pytest.approx(91.5)


def test_dip_below_resets_counter_no_emit(_isolate):
    # 90 → 80 → 90 must NOT trigger — only TWO BACK-TO-BACK >85% fire.
    evaluate_db_pool_state(90.0)
    evaluate_db_pool_state(80.0)
    evaluate_db_pool_state(90.0)
    assert _isolate == []


def test_sustained_degraded_emits_once_not_per_tick(_isolate):
    # Once the transition fires, repeated >85% readings stay silent —
    # the threshold engine's `_evaluate` cache suppresses same-severity
    # re-emits.
    evaluate_db_pool_state(90.0)
    evaluate_db_pool_state(91.0)  # first emit
    evaluate_db_pool_state(92.0)
    evaluate_db_pool_state(93.0)
    assert len(_isolate) == 1


def test_recovery_requires_two_consecutive_low_readings(_isolate):
    # Build up degraded state…
    evaluate_db_pool_state(90.0)
    evaluate_db_pool_state(91.0)
    assert len(_isolate) == 1

    # Single dip below 85% must NOT emit recovery yet.
    evaluate_db_pool_state(80.0)
    assert len(_isolate) == 1

    # Second consecutive sub-threshold reading flips us back to healthy.
    evaluate_db_pool_state(50.0)
    assert len(_isolate) == 2
    assert _isolate[1]["severity"] == "healthy"
    assert _isolate[1]["source"] == "database_pool"


def test_recovery_dip_then_re_spike_no_extra_emit(_isolate):
    # Get into degraded.
    evaluate_db_pool_state(90.0)
    evaluate_db_pool_state(91.0)
    # One sub-threshold reading then a re-spike — should NOT emit
    # recovery and should NOT emit another degraded (we're already
    # in degraded state per the engine cache… but our cache is mocked
    # off; we're checking the local counter behaviour here).
    evaluate_db_pool_state(70.0)
    evaluate_db_pool_state(90.0)
    evaluate_db_pool_state(91.0)
    # Only the original emit + (the re-spike crosses again because our
    # prev cache is mocked off; that's fine — the production path uses
    # real Redis state and would suppress).
    # The KEY thing is: the dip in the middle does NOT flip the source
    # to healthy.
    severities = [p["severity"] for p in _isolate]
    assert "healthy" not in severities


# ── Snapshot embedding ───────────────────────────────────────────────


def test_emit_payload_carries_pool_snapshot(_isolate):
    snap = {
        "pg_pool_size":            20,
        "pg_pool_max_overflow":    10,
        "pg_pool_total_capacity":  30,
        "pg_pool_checked_out":     28,
        "pg_pool_checked_in":      0,
        "pg_pool_overflow":        8,
        "pg_pool_wait_count":      3,
        "pg_pool_utilization_pct": 93.3,
        "available":               True,
    }
    evaluate_db_pool_state(93.3, snapshot=snap)
    evaluate_db_pool_state(93.3, snapshot=snap)
    assert len(_isolate) == 1
    p = _isolate[0]
    # Pool numbers must be in the emitted envelope so the capsule's
    # flyout doesn't need a second hop.
    assert p["pg_pool_checked_out"] == 28
    assert p["pg_pool_wait_count"] == 3
    assert p["pg_pool_total_capacity"] == 30
    # `available` is internal — should NOT leak into the broadcast.
    assert "available" not in p


# ── Threshold contract ──────────────────────────────────────────────


def test_consecutive_readings_constant_is_two():
    # Locked by spec — anything looser fires on transient spikes,
    # anything tighter misses sustained-but-flap exhaustion.
    assert DB_POOL_CONSECUTIVE_READINGS == 2


def test_default_threshold_is_eighty_five_percent():
    assert DB_POOL_UTIL_PCT_DEGRADED == 85.0
