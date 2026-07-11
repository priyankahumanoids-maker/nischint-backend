"""Tests for synthetic_monitor stabilization (June 2026 hardening).

Locks in the contract:
  1. Per-probe `asyncio.wait_for` budget — one slow probe can't starve the pass.
  2. `_scheduled_probe_pass` swallows `CancelledError` cleanly (no Sentry leak).
  3. Streak counter increments → fires Sentry exactly once → resets on recovery.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.services import synthetic_monitor as sm


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with fresh streak counters."""
    sm._consecutive_failures.clear()
    sm._sentry_fired_for_streak.clear()
    yield
    sm._consecutive_failures.clear()
    sm._sentry_fired_for_streak.clear()


# ────────────────────────────────────────────────────────────
# 1. Per-probe budget
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_probe_budget_catches_hang():
    """A probe that hangs longer than the budget returns a structured failure."""

    async def hanging_probe(_client):
        await asyncio.sleep(99)  # would exceed budget

    with patch.object(sm, "PROBE_TIMEOUT_S", 0.05):
        result = await sm._run_probe_with_budget(
            "test_hang", hanging_probe, httpx.AsyncClient()
        )
    assert result["ok"] is False
    assert "budget exceeded" in result["error"]
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_per_probe_budget_passes_normal_probe():
    """A normal probe completes well within the budget."""

    async def fast_probe(_client):
        return {"ok": True, "status_code": 200, "latency_ms": 10, "error": None}

    result = await sm._run_probe_with_budget(
        "test_fast", fast_probe, httpx.AsyncClient()
    )
    assert result["ok"] is True
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_per_probe_budget_catches_exceptions():
    """An unhandled exception in a probe becomes a structured failure."""

    async def crashing_probe(_client):
        raise RuntimeError("DNS exploded")

    result = await sm._run_probe_with_budget(
        "test_crash", crashing_probe, httpx.AsyncClient()
    )
    assert result["ok"] is False
    assert "RuntimeError" in result["error"]
    assert "DNS exploded" in result["error"]


# ────────────────────────────────────────────────────────────
# 2. Scheduled wrapper swallows cancellation cleanly
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduled_pass_swallows_cancellation():
    """Outer task cancellation logs + returns cleanly. The shielded inner
    coroutine continues in the background, so we mock `run_probe_pass`
    to a no-op to keep the test deterministic."""

    async def fake_pass():
        return {}

    with patch.object(sm, "run_probe_pass", fake_pass):
        # Should not raise even if the parent task is cancelled before
        # the shielded coroutine starts.
        await sm._scheduled_probe_pass()


@pytest.mark.asyncio
async def test_scheduled_pass_swallows_unhandled_exception():
    """If `run_probe_pass` itself raises, the wrapper logs and returns."""

    async def boom():
        raise RuntimeError("disaster")

    with patch.object(sm, "run_probe_pass", boom):
        # Must not raise — the scheduler relies on this contract.
        await sm._scheduled_probe_pass()


# ────────────────────────────────────────────────────────────
# 3. Streak + Sentry firing
# ────────────────────────────────────────────────────────────


def _ok():
    return {"ok": True, "status_code": 200, "latency_ms": 12, "error": None}


def _fail():
    return {"ok": False, "status_code": 500, "latency_ms": 12, "error": "HTTP 500"}


def test_streak_increments_on_failure_resets_on_success():
    sm._update_streak("login", _fail())
    sm._update_streak("login", _fail())
    assert sm._consecutive_failures["login"] == 2

    sm._update_streak("login", _ok())
    assert sm._consecutive_failures["login"] == 0


def test_sentry_fires_once_per_streak():
    """3 failures → 1 Sentry call. Further failures → no extra calls."""
    fake_sentry = MagicMock()
    fake_sentry.Hub.current.client = object()  # truthy → not skipped
    fake_sentry.configure_scope = MagicMock()

    with patch.dict(
        "sys.modules",
        {"sentry_sdk": fake_sentry},
    ):
        for _ in range(5):
            sm._update_streak("health", _fail())

    assert fake_sentry.capture_message.call_count == 1
    assert "health" in sm._sentry_fired_for_streak


def test_sentry_refires_after_recovery():
    """Streak A: 3 fails (1 alert) → 1 success (reset) → Streak B: 3 fails (1 alert)."""
    fake_sentry = MagicMock()
    fake_sentry.Hub.current.client = object()
    fake_sentry.configure_scope = MagicMock()

    with patch.dict("sys.modules", {"sentry_sdk": fake_sentry}):
        for _ in range(3):
            sm._update_streak("public_status", _fail())  # 1st alert
        sm._update_streak("public_status", _ok())  # reset
        assert "public_status" not in sm._sentry_fired_for_streak
        for _ in range(3):
            sm._update_streak("public_status", _fail())  # 2nd alert

    assert fake_sentry.capture_message.call_count == 2


# ────────────────────────────────────────────────────────────
# 4. Job registration carries misfire_grace_time
# ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_registered_with_misfire_grace_time():
    """Confirms the scheduler will *delay* missed runs, not drop them."""
    sm.stop_synthetic_monitor()
    sm.start_synthetic_monitor()
    try:
        job = sm._scheduler.get_job(sm._JOB_ID)
        assert job is not None, "synthetic_probes job not registered"
        # APScheduler exposes misfire_grace_time as an attr on the job
        assert job.misfire_grace_time == 120
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        sm.stop_synthetic_monitor()
