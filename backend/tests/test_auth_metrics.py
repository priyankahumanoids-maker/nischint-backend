"""Unit tests for app.services.auth_metrics and the matching
threshold contract in app.services.health_thresholds.

Locks the SLA: rolling 30s p95 of `get_current_user` resolution >
500 ms → `system_health_delta` emitted with source=`auth`. Sub-window
or sub-sample noise must NOT fire.
"""
from __future__ import annotations

import time

import pytest

from app.services import auth_metrics
from app.services.health_thresholds import (
    _classify_auth, AUTH_P95_MS, AUTH_MIN_SAMPLES_DEGRADED,
)
import app.services.health_thresholds as _ht


@pytest.fixture(autouse=True)
def _isolated_auth_state(monkeypatch):
    """Reset module-level state between tests + bypass startup grace.

    Most classifier tests are checking the steady-state contract, not
    the startup-grace behaviour. Tests that want to exercise the grace
    window monkey-patch `_PROCESS_START_TS` themselves.
    """
    auth_metrics._samples.clear()
    auth_metrics._hits_total = 0
    auth_metrics._misses_total = 0
    # Pretend we're well past the 60 s startup grace window.
    monkeypatch.setattr(_ht, "_PROCESS_START_TS", 0.0)
    yield
    auth_metrics._samples.clear()
    auth_metrics._hits_total = 0
    auth_metrics._misses_total = 0


def test_record_appends_to_window(monkeypatch):
    monkeypatch.setattr(auth_metrics, "_maybe_emit_threshold_event", lambda: None)
    auth_metrics.record(12.5, cache_hit=True)
    auth_metrics.record(220.0, cache_hit=False)
    snap = auth_metrics.get_snapshot()
    assert snap["samples"] == 2
    assert snap["hits_window"] == 1
    assert snap["misses_window"] == 1
    assert snap["hits_total"] == 1
    assert snap["misses_total"] == 1
    # p95 of [12.5, 220] ≈ 220
    assert snap["p95_ms"] is not None and snap["p95_ms"] >= 200


def test_window_eviction_drops_old_samples(monkeypatch):
    """Samples older than WINDOW_S must NOT contribute to the snapshot."""
    monkeypatch.setattr(auth_metrics, "_maybe_emit_threshold_event", lambda: None)
    now = time.time()
    auth_metrics._samples.append(auth_metrics._Sample(now - 60, 5000.0, False))  # stale
    auth_metrics._samples.append(auth_metrics._Sample(now - 1, 50.0, True))      # fresh
    snap = auth_metrics.get_snapshot()
    # The 5000 ms stale sample must be evicted.
    assert snap["samples"] == 1
    assert snap["p95_ms"] is not None and snap["p95_ms"] < 100


def test_hit_rate_computed_only_when_samples(monkeypatch):
    monkeypatch.setattr(auth_metrics, "_maybe_emit_threshold_event", lambda: None)
    snap = auth_metrics.get_snapshot()
    assert snap["samples"] == 0
    assert snap["hit_rate"] is None
    assert snap["p95_ms"] is None


# ── Threshold engine contract ────────────────────────────────────────


def test_classify_auth_healthy_when_below_sla():
    sev, metric, value = _classify_auth(p95_ms=300.0, samples=20)
    assert sev == "healthy" and metric is None and value is None


def test_classify_auth_healthy_when_p95_none():
    sev, metric, value = _classify_auth(p95_ms=None, samples=0)
    assert sev == "healthy"


def test_classify_auth_healthy_under_min_samples():
    """Below the 10-sample noise floor — never alert (was 5; raised
    after a cold-start false positive in prod that tagged a 3-sample
    spike as degraded)."""
    sev, _, _ = _classify_auth(p95_ms=4000.0, samples=9)
    assert sev == "healthy"


def test_classify_auth_boundary_at_min_samples():
    """Exactly 10 samples is the inclusive lower bound."""
    sev, _, _ = _classify_auth(p95_ms=4000.0, samples=AUTH_MIN_SAMPLES_DEGRADED)
    assert sev == "degraded"


def test_classify_auth_startup_grace_window_suppresses_degraded(monkeypatch):
    """Within 60 s of process start, even a clear breach stays healthy.

    Cold-start cache misses (first 5–8 authed requests after a fresh
    process boot) legitimately pay the full Mumbai-pooler RTT until the
    in-process LRU warms. Firing degraded here would mis-classify
    expected behaviour as an incident.
    """
    # Force "we're 5 s into a fresh process" — well inside grace.
    monkeypatch.setattr(_ht, "_PROCESS_START_TS", _ht.time.time() - 5.0)
    sev, _, _ = _classify_auth(p95_ms=2000.0, samples=20)
    assert sev == "healthy"


def test_classify_auth_after_startup_grace_can_degrade(monkeypatch):
    monkeypatch.setattr(_ht, "_PROCESS_START_TS", _ht.time.time() - 120.0)
    sev, _, _ = _classify_auth(p95_ms=2000.0, samples=20)
    assert sev == "degraded"


def test_classify_auth_degraded_above_sla_with_samples():
    sev, metric, value = _classify_auth(p95_ms=720.0, samples=12)
    assert sev == "degraded"
    assert metric == "p95_ms"
    assert value == 720.0


def test_classify_auth_boundary_at_500ms():
    """500 ms is the SLA — only > 500 ms should degrade."""
    sev, _, _ = _classify_auth(p95_ms=500.0, samples=15)
    assert sev == "healthy"
    sev, _, _ = _classify_auth(p95_ms=AUTH_P95_MS + 0.01, samples=15)
    assert sev == "degraded"


def test_evaluate_auth_state_no_emit_on_cold_healthy(monkeypatch):
    """Cold start at healthy must NOT broadcast — silent record only."""
    emitted: list[dict] = []
    monkeypatch.setattr(
        "app.services.health_thresholds._emit",
        lambda payload: emitted.append(payload),
    )
    # Force "no previous state" cold start.
    monkeypatch.setattr(
        "app.services.health_thresholds._read_prev",
        lambda source: None,
    )
    monkeypatch.setattr(
        "app.services.health_thresholds._write_prev",
        lambda source, payload: None,
    )
    from app.services.health_thresholds import evaluate_auth_state
    evaluate_auth_state(p95_ms=100.0, samples=10)
    assert emitted == []


def test_evaluate_auth_state_emits_on_degraded_transition(monkeypatch):
    """healthy → degraded MUST fire exactly one delta with source=auth."""
    emitted: list[dict] = []
    monkeypatch.setattr(
        "app.services.health_thresholds._emit",
        lambda payload: emitted.append(payload),
    )
    monkeypatch.setattr(
        "app.services.health_thresholds._read_prev",
        lambda source: {"severity": "healthy", "metric": None, "ts": 0},
    )
    monkeypatch.setattr(
        "app.services.health_thresholds._write_prev",
        lambda source, payload: None,
    )
    # Stub out the incident engine wiring to keep this unit test pure.
    import sys, types
    fake = types.ModuleType("app.services.system_incident_engine")
    async def _noop(*a, **kw): return None
    fake.handle_transition = _noop
    fake.cancel_pending = lambda *a, **kw: None
    sys.modules["app.services.system_incident_engine"] = fake

    from app.services.health_thresholds import evaluate_auth_state
    evaluate_auth_state(p95_ms=900.0, samples=12)
    assert len(emitted) == 1
    payload = emitted[0]
    assert payload["source"] == "auth"
    assert payload["severity"] == "degraded"
    assert payload["metric"] == "p95_ms"
    assert payload["value"] == 900.0
    assert payload["threshold"] == 500.0
    assert payload["previous_severity"] == "healthy"
