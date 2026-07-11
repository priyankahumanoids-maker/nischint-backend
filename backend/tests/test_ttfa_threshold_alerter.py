"""NISCH-006 Day 3++ — TTFA threshold alerter tests.

Locks the operational contract:
  * Breach → fires `notify_failure` with the worst-state title and
    full state breakdown body.
  * No breach → no Slack call.
  * Per-state cooldown gates re-alerts inside 15 min.
  * Cooldown expires → re-alert allowed.
  * Redis unavailable → fail open (alert still fires).
  * Each state's cooldown is isolated — `escalated` cooldown does NOT
    silence a fresh `validating` breach.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import ttfa_threshold_alerter as alerter


# Dummy session — tests stub out `get_state_stats` so the session
# is never actually hit.
class _DummySession:
    pass


# ── 1. No breach → no Slack call ───────────────────────────────────
@pytest.mark.asyncio
async def test_no_breach_no_alert(monkeypatch):
    async def fake_stats(*a, **kw):
        return {
            "escalated":    {"count": 10, "p50_ms": 2000,  "p95_ms": 5000},
            "validating":   {"count": 12, "p50_ms": 200,   "p95_ms":  800},
            "acknowledged": {"count": 8,  "p50_ms": 5000,  "p95_ms": 12000},
        }
    monkeypatch.setattr(alerter, "get_state_stats", fake_stats)
    notify_mock = MagicMock(return_value=True)
    monkeypatch.setattr(alerter, "notify_failure", notify_mock)

    out = await alerter.check_and_alert(_DummySession())
    assert out["alerts_fired"] == 0
    assert out["breaches"] == {}
    notify_mock.assert_not_called()


# ── 2. Breach fires Slack with breakdown ───────────────────────────
@pytest.mark.asyncio
async def test_breach_fires_slack(monkeypatch):
    async def fake_stats(*a, **kw):
        return {
            "escalated":  {"count": 41, "p50_ms": 4200,  "p95_ms": 38200},
            "validating": {"count": 45, "p50_ms": 340,   "p95_ms":   890},
        }
    monkeypatch.setattr(alerter, "get_state_stats", fake_stats)
    monkeypatch.setattr(alerter, "_try_acquire_cooldown", lambda *a, **kw: True)
    notify_mock = MagicMock(return_value=True)
    monkeypatch.setattr(alerter, "notify_failure", notify_mock)

    out = await alerter.check_and_alert(_DummySession())
    assert out["alerts_fired"] == 1
    assert "escalated" in out["alertable"]
    notify_mock.assert_called_once()
    call_kwargs = notify_mock.call_args.kwargs
    assert call_kwargs["kind"] == "ttfa_p95_breach"
    assert "escalated" in call_kwargs["message"]
    assert "38,200ms" in call_kwargs["message"]  # threshold formatting
    assert "30,000ms" in call_kwargs["message"]  # threshold display
    # Body carries the full breakdown including non-breached states.
    assert "validating" in call_kwargs["message"]


# ── 3. Cooldown suppresses re-alert ────────────────────────────────
@pytest.mark.asyncio
async def test_cooldown_suppresses(monkeypatch):
    async def fake_stats(*a, **kw):
        return {"escalated": {"count": 5, "p50_ms": 4200, "p95_ms": 38200}}
    monkeypatch.setattr(alerter, "get_state_stats", fake_stats)
    # First call wins cooldown; second call is suppressed.
    monkeypatch.setattr(alerter, "_try_acquire_cooldown",
                        lambda state, ttl: False)  # always held
    notify_mock = MagicMock()
    monkeypatch.setattr(alerter, "notify_failure", notify_mock)

    out = await alerter.check_and_alert(_DummySession())
    assert out["alerts_fired"] == 0
    assert "escalated" in out["suppressed"]
    notify_mock.assert_not_called()


# ── 4. Cooldown expiry → re-alert allowed ──────────────────────────
@pytest.mark.asyncio
async def test_cooldown_expiry_allows_realert(monkeypatch):
    async def fake_stats(*a, **kw):
        return {"escalated": {"count": 5, "p50_ms": 4200, "p95_ms": 38200}}
    monkeypatch.setattr(alerter, "get_state_stats", fake_stats)
    # Simulate cooldown EXPIRED — acquire returns True (key was free).
    monkeypatch.setattr(alerter, "_try_acquire_cooldown",
                        lambda state, ttl: True)
    notify_mock = MagicMock()
    monkeypatch.setattr(alerter, "notify_failure", notify_mock)

    out = await alerter.check_and_alert(_DummySession())
    assert out["alerts_fired"] == 1
    notify_mock.assert_called_once()


# ── 5. Redis unavailable → fail open ───────────────────────────────
def test_cooldown_fail_open_on_redis_outage(monkeypatch):
    # Simulate redis client unavailable.
    monkeypatch.setattr(alerter.redis_service, "_get_client", lambda: None)
    # Still permits the alert.
    assert alerter._try_acquire_cooldown("escalated", 900) is True


def test_cooldown_fail_open_on_redis_exception(monkeypatch):
    class _Boom:
        def set(self, *a, **kw): raise RuntimeError("redis blew up")
    monkeypatch.setattr(alerter.redis_service, "_get_client", lambda: _Boom())
    assert alerter._try_acquire_cooldown("escalated", 900) is True


# ── 6. Per-state cooldown isolation ────────────────────────────────
@pytest.mark.asyncio
async def test_per_state_cooldown_isolation(monkeypatch):
    """If `escalated` cooldown is held but `validating` is free, the
    alert MUST still fire for `validating` only."""
    async def fake_stats(*a, **kw):
        return {
            "escalated":  {"count": 10, "p50_ms": 4000, "p95_ms": 35000},  # breach
            "validating": {"count": 20, "p50_ms":  300, "p95_ms":  9000},  # breach
        }
    monkeypatch.setattr(alerter, "get_state_stats", fake_stats)

    # `escalated` cooldown is held; `validating` is free.
    def selective_cooldown(state, ttl):
        return state != "escalated"
    monkeypatch.setattr(alerter, "_try_acquire_cooldown", selective_cooldown)

    notify_mock = MagicMock()
    monkeypatch.setattr(alerter, "notify_failure", notify_mock)

    out = await alerter.check_and_alert(_DummySession())
    assert out["alerts_fired"] == 1
    assert "validating" in out["alertable"]
    assert "escalated" not in out["alertable"]
    assert "escalated" in out["suppressed"]
    # The Slack message highlights `validating` (the only non-suppressed
    # breaching state in this scenario).
    msg = notify_mock.call_args.kwargs["message"]
    assert "validating" in msg


# ── 7. Notify_failure failure does NOT release cooldown ────────────
@pytest.mark.asyncio
async def test_slack_failure_keeps_cooldown_held(monkeypatch):
    """If `notify_failure` raises, we must NOT roll back the cooldown
    — that would cause a re-alert storm against the same breach as
    soon as the next tick runs."""
    async def fake_stats(*a, **kw):
        return {"escalated": {"count": 5, "p50_ms": 4200, "p95_ms": 38200}}
    monkeypatch.setattr(alerter, "get_state_stats", fake_stats)

    cooldown_calls = []
    def trap_cooldown(state, ttl):
        cooldown_calls.append(state)
        return True
    monkeypatch.setattr(alerter, "_try_acquire_cooldown", trap_cooldown)

    # Make notify_failure swallow internally (it does — it's
    # documented as never-raising). Verify cooldown was acquired
    # exactly once even if the post failed.
    monkeypatch.setattr(alerter, "notify_failure",
                        lambda **kw: False)  # simulate webhook fail

    out = await alerter.check_and_alert(_DummySession())
    assert cooldown_calls == ["escalated"]  # acquired once, no rollback
    assert out["alerts_fired"] == 1


# ── 8. Env-overridable thresholds ──────────────────────────────────
def test_thresholds_read_from_env(monkeypatch):
    monkeypatch.setenv("TTFA_THRESHOLD_ESCALATED_MS", "12345")
    monkeypatch.setenv("TTFA_THRESHOLD_VALIDATING_MS", "678")
    t = alerter._thresholds()
    assert t["escalated"] == 12345
    assert t["validating"] == 678


def test_thresholds_default_when_env_missing(monkeypatch):
    monkeypatch.delenv("TTFA_THRESHOLD_ESCALATED_MS", raising=False)
    monkeypatch.delenv("TTFA_THRESHOLD_VALIDATING_MS", raising=False)
    monkeypatch.delenv("TTFA_THRESHOLD_ACKNOWLEDGED_MS", raising=False)
    t = alerter._thresholds()
    assert t["escalated"]    == 30_000
    assert t["validating"]   == 5_000
    assert t["acknowledged"] == 60_000


def test_thresholds_default_on_garbage_env(monkeypatch):
    monkeypatch.setenv("TTFA_THRESHOLD_ESCALATED_MS", "not_a_number")
    t = alerter._thresholds()
    assert t["escalated"] == 30_000  # fallback to default
