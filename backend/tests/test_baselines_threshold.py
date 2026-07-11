"""SB-02 follow-up — baselines health-threshold classifier + device-grain
read helpers + System Health Capsule wiring.

Three things locked here:
  1. `_classify_baselines` — pure function truth table.
       * `last_status='failure'` → degraded regardless of timestamp.
       * Stale matview (> 36 h) → degraded.
       * Fresh + success → healthy.
       * No timestamp on record → warning (cold start).
  2. `evaluate_baselines_state` — fires `system_health_delta` ONLY
     on transitions (golden rule of the threshold engine).
  3. `get_device_baseline` / `get_device_baselines_24h` — new
     device-grain readers carved from the matview, used by the
     migrated `operator.py` endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.health_thresholds import (
    BASELINES_STALENESS_THRESHOLD_S,
    _classify_baselines,
    evaluate_baselines_state,
)
from app.services.user_signal_baseline_service import (
    get_device_baseline, get_device_baselines_24h,
)


# ── _classify_baselines truth table ───────────────────────────────


def test_baselines_failure_is_degraded_regardless_of_timestamp():
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    # Even a "fresh" timestamp doesn't save a failure status.
    sev, metric, value = _classify_baselines(
        last_status="failure",
        last_refreshed_at=now - timedelta(minutes=5),
        now=now,
    )
    assert sev == "degraded"
    assert metric == "last_status"
    assert value == 1.0


def test_baselines_fresh_success_is_healthy():
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    sev, metric, value = _classify_baselines(
        last_status="success",
        last_refreshed_at=now - timedelta(hours=2),
        now=now,
    )
    assert sev == "healthy"
    assert metric is None
    assert value is None


def test_baselines_stale_matview_is_degraded():
    """> 36 h since last refresh = degraded with metric=staleness_s."""
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    sev, metric, value = _classify_baselines(
        last_status="success",
        last_refreshed_at=now - timedelta(hours=48),
        now=now,
    )
    assert sev == "degraded"
    assert metric == "staleness_s"
    # 48 h = 172,800 s
    assert value == pytest.approx(48 * 3600.0)


def test_baselines_exactly_at_threshold_still_healthy():
    """Inclusive boundary — matches `classify_freshness`'s contract
    so the snapshot and the WS push never disagree."""
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    sev, _m, _v = _classify_baselines(
        last_status="success",
        last_refreshed_at=now - timedelta(seconds=BASELINES_STALENESS_THRESHOLD_S),
        now=now,
    )
    assert sev == "healthy"


def test_baselines_no_refresh_recorded_is_warning():
    """Cold start — no timestamp yet. System isn't broken, we just
    don't have evidence of a successful refresh."""
    sev, metric, _v = _classify_baselines(
        last_status="unknown",
        last_refreshed_at=None,
    )
    assert sev == "warning"
    assert metric == "no_refresh_recorded"


def test_baselines_naive_timestamp_assumed_utc():
    """Defensive — a naive datetime must NOT raise."""
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 2, 1, 11, 0)        # 1 h ago, no tz
    sev, _m, _v = _classify_baselines(
        last_status="success",
        last_refreshed_at=naive,
        now=now,
    )
    assert sev == "healthy"


# ── evaluate_baselines_state — transition wiring ──────────────────


def test_evaluate_baselines_state_fires_evaluate(monkeypatch):
    """`evaluate_baselines_state` must call `_evaluate` with
    source='baselines' so the WS delta engine groups events under
    the right domain."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.services.health_thresholds._evaluate",
        lambda *a: calls.append(a),
    )
    evaluate_baselines_state(
        last_status="failure",
        last_refreshed_at=None,
        extra={"duration_ms": 1.5, "error": "boom"},
    )
    assert len(calls) == 1
    source, sev, metric, value, threshold, extra = calls[0]
    assert source == "baselines"
    assert sev == "degraded"
    assert metric == "last_status"
    assert extra["error"] == "boom"


def test_evaluate_baselines_state_passes_threshold_only_for_staleness(monkeypatch):
    """The 36h staleness threshold should appear in the event only
    when staleness is the dominant signal — the failure path has no
    threshold concept."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.services.health_thresholds._evaluate",
        lambda *a: calls.append(a),
    )
    now = datetime.now(timezone.utc)
    # Stale → threshold filled.
    evaluate_baselines_state(
        last_status="success",
        last_refreshed_at=now - timedelta(hours=48),
        extra={},
    )
    assert calls[-1][4] == float(BASELINES_STALENESS_THRESHOLD_S)
    # Failure → threshold None.
    evaluate_baselines_state(last_status="failure", last_refreshed_at=None)
    assert calls[-1][4] is None


# ── Device-grain helpers (SB-02 follow-up for operator.py) ────────


@pytest.mark.asyncio
async def test_get_device_baseline_invalid_hour_short_circuits():
    session = MagicMock()
    session.execute = AsyncMock()
    out = await get_device_baseline(session, "dev-1", 24)
    assert out is None
    out = await get_device_baseline(session, "dev-1", -1)
    assert out is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_device_baseline_valid_hour_returns_single_dict():
    fake_row = SimpleNamespace(
        device_id="dev-1",
        device_identifier="watch-001",
        device_type="watch",
        device_status="online",
        hour_of_day=14,
        avg_movement=1.5,
        std_movement=0.5,
        avg_location_switch=0.3,
        std_location_switch=0.1,
        avg_interaction_rate=4.2,
        std_interaction_rate=1.0,
        sample_count=99,
        baseline_updated_at=datetime(2026, 2, 1, 14, 0, tzinfo=timezone.utc),
    )
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = fake_row
    session.execute = AsyncMock(return_value=result)

    out = await get_device_baseline(session, "dev-1", 14)
    assert isinstance(out, dict)
    assert out["hour_of_day"] == 14
    assert out["avg_movement"] == 1.5
    assert out["sample_count"] == 99


@pytest.mark.asyncio
async def test_get_device_baseline_no_row_returns_none():
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result)

    out = await get_device_baseline(session, "dev-1", 0)
    assert out is None


@pytest.mark.asyncio
async def test_get_device_baselines_24h_passes_device_id_param():
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    out = await get_device_baselines_24h(session, "dev-42")
    assert out == []
    call_args = session.execute.call_args
    assert call_args.args[1] == {"did": "dev-42"}


# ── End-to-end: refresh service fires health_thresholds ───────────


@pytest.mark.asyncio
async def test_refresh_success_triggers_baselines_threshold(monkeypatch):
    """A clean refresh must drive the baselines threshold evaluator
    with `last_status='success'`. Any subsequent transition (e.g.
    after a failure) will then correctly fire system_health_delta."""
    from app.services.user_signal_baseline_service import (
        refresh_user_signal_baselines,
    )

    captured: dict = {}
    def _capture(*, last_status, last_refreshed_at, extra=None):
        captured["last_status"] = last_status
        captured["last_refreshed_at"] = last_refreshed_at
        captured["extra"] = extra

    monkeypatch.setattr(
        "app.services.health_thresholds.evaluate_baselines_state",
        _capture,
    )

    session = MagicMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.scalar.return_value = 17
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    out = await refresh_user_signal_baselines(session)
    assert out["status"] == "success"
    assert captured["last_status"] == "success"
    assert captured["last_refreshed_at"] is not None
    assert captured["extra"]["rows"] == 17


@pytest.mark.asyncio
async def test_refresh_failure_triggers_baselines_threshold_with_none_ts(monkeypatch):
    """On refresh failure, the evaluator gets `last_refreshed_at=None`
    so the classifier honours the failure signal regardless of the
    metadata row's possibly-stale timestamp."""
    from app.services.user_signal_baseline_service import (
        refresh_user_signal_baselines,
    )

    captured: dict = {}
    def _capture(*, last_status, last_refreshed_at, extra=None):
        captured["last_status"] = last_status
        captured["last_refreshed_at"] = last_refreshed_at

    monkeypatch.setattr(
        "app.services.health_thresholds.evaluate_baselines_state",
        _capture,
    )

    session = MagicMock()

    async def _execute(stmt, params=None):
        sql = str(stmt)
        if "REFRESH MATERIALIZED VIEW" in sql:
            raise RuntimeError("simulated DB outage")
        result = MagicMock()
        result.scalar.return_value = 0
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    out = await refresh_user_signal_baselines(session)
    assert out["status"] == "failure"
    assert captured["last_status"] == "failure"
    assert captured["last_refreshed_at"] is None
