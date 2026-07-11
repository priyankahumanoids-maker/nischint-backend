"""LT-03 — Loop-lag Sentry/Slack fan-out monitor invariants.

These tests lock the state-machine behaviour so a future refactor
can't accidentally:
  * Drop the fingerprint (which would un-group Sentry issues)
  * Remove the sustained-window guard (which would re-introduce flapping)
  * Skip the hysteresis (which would oscillate around a single threshold)
  * Forget to call Sentry's `capture_message` on transitions
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import loop_lag_monitor as llm


# ── State machine invariants ─────────────────────────────────────


def test_lt03_baseline_stays_healthy():
    """Below-threshold samples never flip to degraded."""
    s = llm._LoopLagState(degraded_threshold_ms=500, healthy_threshold_ms=200, sustained_window_s=30)
    t = 0.0
    for _ in range(100):
        assert s.feed(0.1, now=t) is None
        t += 1.0
    assert s.state == "healthy"


def test_lt03_brief_spike_does_not_flip():
    """One high sample (no sustained window) must NOT flip."""
    s = llm._LoopLagState(degraded_threshold_ms=500, healthy_threshold_ms=200, sustained_window_s=30)
    assert s.feed(2000, now=0.0) is None  # streak starts
    assert s.feed(2000, now=5.0) is None  # only 5s elapsed
    assert s.feed(50,   now=10.0) is None  # back to healthy, streak drops
    assert s.feed(2000, now=11.0) is None  # streak restarts at 11s
    assert s.feed(2000, now=12.0) is None  # only 1s
    assert s.state == "healthy"


def test_lt03_sustained_high_lag_flips_to_degraded():
    """Sustained ≥ 30s of high lag → degraded transition emitted."""
    s = llm._LoopLagState(degraded_threshold_ms=500, healthy_threshold_ms=200, sustained_window_s=30)
    # Streak starts at t=0
    assert s.feed(800, now=0.0) is None
    # At t=29 — still under threshold for total elapsed
    assert s.feed(800, now=29.0) is None
    assert s.state == "healthy"
    # At t=30 — crosses sustained-window boundary
    transition = s.feed(900, now=30.0)
    assert transition == "degraded"
    assert s.state == "degraded"
    # Peak captured correctly
    assert s._last_transition_peak_ms == 900


def test_lt03_recovery_requires_sustained_low_lag():
    """A few low samples while degraded don't recover; only sustained does."""
    s = llm._LoopLagState(degraded_threshold_ms=500, healthy_threshold_ms=200, sustained_window_s=30)
    # Force into degraded
    s.state = "degraded"
    # 5 low samples → not enough for recovery
    for i, t in enumerate([0.0, 5.0, 10.0, 15.0, 20.0]):
        assert s.feed(50, now=t) is None
    assert s.state == "degraded"
    # High spike resets the recovery streak
    assert s.feed(600, now=22.0) is None
    assert s.state == "degraded"
    # Fresh recovery streak — needs another 30s
    assert s.feed(50, now=23.0) is None
    assert s.feed(50, now=52.0) is None    # 29s under threshold
    transition = s.feed(50, now=53.0)      # 30s — flips
    assert transition == "recovered"
    assert s.state == "healthy"


def test_lt03_hysteresis_prevents_flapping_around_400ms():
    """Lag oscillating between healthy_threshold and degraded_threshold
    must NOT trigger transitions — that's the hysteresis band."""
    s = llm._LoopLagState(degraded_threshold_ms=500, healthy_threshold_ms=200, sustained_window_s=30)
    # 400ms = in the hysteresis band (above healthy, below degraded)
    # From healthy state: 400ms is < degraded_threshold → never flips
    t = 0.0
    for _ in range(200):
        assert s.feed(400, now=t) is None
        t += 1.0
    assert s.state == "healthy"


# ── Sentry emission invariants ───────────────────────────────────


def _fake_sentry():
    """Build a mock sentry_sdk + scope. Returns (sdk_mock, scope_mock)."""
    sdk = MagicMock()
    scope = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=scope)
    cm.__exit__ = MagicMock(return_value=False)
    sdk.push_scope.return_value = cm
    return sdk, scope


def test_lt03_emit_degraded_sets_fingerprint(monkeypatch):
    """Fingerprint MUST be ['loop-lag-degraded'] — Sentry uses this to
    group every loop-lag episode into one issue + route to Slack."""
    sdk, scope = _fake_sentry()
    monkeypatch.setattr(llm, "_sentry", lambda: sdk)
    llm._emit_degraded(peak_lag_ms=1234.5, sustained_window_s=30, sample_count=42)
    assert scope.fingerprint == ["loop-lag-degraded"]
    sdk.capture_message.assert_called_once()
    args, kwargs = sdk.capture_message.call_args
    assert "saturated" in args[0].lower()
    assert kwargs.get("level") == "warning"


def test_lt03_emit_degraded_sets_canonical_tags(monkeypatch):
    """REL-09 contract: provider, transition, severity tags must be set."""
    sdk, scope = _fake_sentry()
    monkeypatch.setattr(llm, "_sentry", lambda: sdk)
    llm._emit_degraded(peak_lag_ms=600, sustained_window_s=30, sample_count=30)
    tag_calls = {c.args[0]: c.args[1] for c in scope.set_tag.call_args_list}
    assert tag_calls.get("provider") == "loop-lag"
    assert tag_calls.get("transition") == "healthy->degraded"
    assert tag_calls.get("severity") == "p1"


def test_lt03_emit_degraded_includes_peak_in_context(monkeypatch):
    """Operator looking at the Sentry issue must see the peak lag value
    in the 'loop_lag' context block — otherwise the issue is uninformative."""
    sdk, scope = _fake_sentry()
    monkeypatch.setattr(llm, "_sentry", lambda: sdk)
    llm._emit_degraded(peak_lag_ms=2228.0, sustained_window_s=30, sample_count=30)
    ctx_call = scope.set_context.call_args
    assert ctx_call.args[0] == "loop_lag"
    ctx = ctx_call.args[1]
    assert ctx["peak_lag_ms"] == 2228.0
    assert ctx["sustained_window_s"] == 30
    assert "pid" in ctx


def test_lt03_emit_recovered_uses_same_fingerprint(monkeypatch):
    """Recovery event MUST land on the same Sentry issue as the outage.
    Same fingerprint, but info-level so it shows as a 'resolved' marker."""
    sdk, scope = _fake_sentry()
    monkeypatch.setattr(llm, "_sentry", lambda: sdk)
    llm._emit_recovered(sustained_window_s=30)
    assert scope.fingerprint == ["loop-lag-degraded"]
    args, kwargs = sdk.capture_message.call_args
    assert "recovered" in args[0].lower()
    assert kwargs.get("level") == "info"


def test_lt03_no_sentry_configured_no_crash(monkeypatch):
    """If sentry_sdk isn't loaded (or has no client), monitor must
    log-and-skip — never crash. Pattern matches REL-09."""
    monkeypatch.setattr(llm, "_sentry", lambda: None)
    # Both should return without raising
    llm._emit_degraded(peak_lag_ms=999, sustained_window_s=30, sample_count=10)
    llm._emit_recovered(sustained_window_s=30)


def test_lt03_disabled_env_does_not_start_monitor(monkeypatch):
    """LOOP_LAG_MONITOR_DISABLED=true respected — operator can opt-out."""
    monkeypatch.setenv("LOOP_LAG_MONITOR_DISABLED", "true")
    task = llm.start_monitor()
    assert task is None


def test_lt03_disabled_env_falsy_does_not_disable(monkeypatch):
    """Anything other than truthy values leaves the monitor enabled.
    We don't actually start the task here (no running loop in pytest);
    we just confirm `_is_disabled` reads env correctly."""
    monkeypatch.setenv("LOOP_LAG_MONITOR_DISABLED", "")
    assert llm._is_disabled() is False
    monkeypatch.setenv("LOOP_LAG_MONITOR_DISABLED", "0")
    assert llm._is_disabled() is False
    monkeypatch.setenv("LOOP_LAG_MONITOR_DISABLED", "false")
    assert llm._is_disabled() is False


@pytest.mark.asyncio
async def test_lt03_sample_loop_lag_returns_float():
    """Sampler returns a non-negative float (round-trip of a no-op
    sleep is always >= 0; could be 0.001ms on a fast machine)."""
    lag = await llm._sample_loop_lag_ms()
    assert isinstance(lag, float)
    assert lag >= 0
