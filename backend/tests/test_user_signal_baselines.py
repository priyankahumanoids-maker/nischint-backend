"""SB-02 — `user_signal_baselines` matview service tests.

What's locked:
  1. `classify_freshness` — pure function, exhaustive truth table.
  2. `refresh_user_signal_baselines` — happy path records
     `last_status='success'` + duration_ms + rows; fall-back
     branch uses blocking SQL when `use_concurrent=False`.
  3. `refresh_user_signal_baselines` — failure path:
       * SQL raises → status='failure', `last_error` populated,
         the function does NOT propagate the exception.
       * Metadata write failure → swallowed, refresh result still
         returned (the operator UI gets the truth even when meta
         is sick).
  4. `get_user_baseline` — empty result on out-of-range hour
     short-circuits (no SQL call).
  5. `get_refresh_status` — None row → `unknown` shape; real row
     → freshness verdict derived from the timestamp.
  6. `_row_to_dict` — rounding + type contract.

DB calls are mocked at the session.execute seam. Tests do NOT touch
Supabase (which has SSL-cert issues in this preview pod).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.user_signal_baseline_service import (
    STALENESS_THRESHOLD_S,
    _row_to_dict,
    classify_freshness,
    get_refresh_status,
    get_user_baseline,
    get_user_baselines_24h,
    refresh_user_signal_baselines,
)


# ── classify_freshness ─────────────────────────────────────────────


def test_classify_freshness_fresh_inside_window():
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(hours=1)
    assert classify_freshness(last, now=now) == "fresh"


def test_classify_freshness_stale_outside_window():
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(hours=37)
    assert classify_freshness(last, now=now) == "stale"


def test_classify_freshness_boundary_is_fresh():
    """Exactly at the threshold — fresh, not stale. Inclusive boundary."""
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(seconds=STALENESS_THRESHOLD_S)
    assert classify_freshness(last, now=now) == "fresh"


def test_classify_freshness_none_is_unknown():
    assert classify_freshness(None) == "unknown"


def test_classify_freshness_naive_datetime_assumed_utc():
    """Defensive — a naive datetime should NOT raise. Assume UTC."""
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    last_naive = datetime(2026, 2, 1, 11, 0)
    assert classify_freshness(last_naive, now=now) == "fresh"


def test_classify_freshness_future_timestamp_defends_against_clock_skew():
    now = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    last = now + timedelta(seconds=5)
    assert classify_freshness(last, now=now) == "fresh"


# ── refresh_user_signal_baselines ──────────────────────────────────


def _mock_session_with_rows(row_count: int = 42):
    """Build an AsyncSession mock that:
      * Records every `execute(text)` call's SQL string + params.
      * Returns a fetcher that produces (`row_count`) for COUNT(*)
        queries.
      * No-ops commit/rollback.
    """
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    calls: list[dict] = []

    async def _execute(stmt, params=None):
        sql = str(stmt)
        calls.append({"sql": sql, "params": params})
        # Return a result whose .scalar() yields row_count for any
        # COUNT(*) call (the only scalar caller in the module).
        result = MagicMock()
        result.scalar.return_value = row_count
        return result

    session.execute.side_effect = _execute
    session._recorded_calls = calls
    return session


@pytest.mark.asyncio
async def test_refresh_happy_path_concurrent():
    session = _mock_session_with_rows(row_count=128)
    out = await refresh_user_signal_baselines(session)
    assert out["status"] == "success"
    assert out["mode"] == "concurrent"
    assert out["rows"] == 128
    assert out["error"] is None
    assert out["duration_ms"] >= 0
    # The CONCURRENT SQL was issued.
    sqls = [c["sql"] for c in session._recorded_calls]
    assert any("REFRESH MATERIALIZED VIEW CONCURRENTLY" in s for s in sqls)
    # Metadata row was updated.
    assert any("user_signal_baselines_meta" in s for s in sqls)


@pytest.mark.asyncio
async def test_refresh_blocking_mode_uses_non_concurrent_sql():
    session = _mock_session_with_rows()
    out = await refresh_user_signal_baselines(session, use_concurrent=False)
    assert out["mode"] == "blocking"
    sqls = [c["sql"] for c in session._recorded_calls]
    # The CONCURRENT phrase MUST NOT appear in the refresh SQL.
    assert any(
        "REFRESH MATERIALIZED VIEW" in s
        and "CONCURRENTLY" not in s
        for s in sqls
    )


@pytest.mark.asyncio
async def test_refresh_failure_records_status_and_returns_normally():
    """SQL refresh raises → status='failure', error populated, function
    does NOT propagate the exception."""
    session = MagicMock()
    calls = []

    async def _execute(stmt, params=None):
        sql = str(stmt)
        calls.append({"sql": sql, "params": params})
        if "REFRESH MATERIALIZED VIEW" in sql:
            raise RuntimeError("simulated DB outage")
        # Metadata UPDATE succeeds — we want to verify it ran.
        result = MagicMock()
        result.scalar.return_value = 0
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    out = await refresh_user_signal_baselines(session)
    assert out["status"] == "failure"
    assert "simulated DB outage" in out["error"]
    # The metadata UPDATE must still have run.
    assert any("user_signal_baselines_meta" in c["sql"] for c in calls)


@pytest.mark.asyncio
async def test_refresh_meta_write_failure_is_swallowed():
    """If the meta UPDATE itself fails (Redis would be analogous), the
    refresh result is still returned — the operator UI gets the truth
    even when the meta layer is sick."""
    session = MagicMock()

    async def _execute(stmt, params=None):
        sql = str(stmt)
        if "user_signal_baselines_meta" in sql:
            raise RuntimeError("meta UPDATE failed")
        # Refresh + COUNT succeed.
        result = MagicMock()
        result.scalar.return_value = 7
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    out = await refresh_user_signal_baselines(session)
    # The refresh itself succeeded — the meta-write failure must NOT
    # downgrade the visible result.
    assert out["status"] == "success"
    assert out["rows"] == 7


# ── get_user_baseline / get_user_baselines_24h ─────────────────────


@pytest.mark.asyncio
async def test_get_user_baseline_invalid_hour_short_circuits():
    """Out-of-range hour must NOT issue any SQL — defensive."""
    session = MagicMock()
    session.execute = AsyncMock()
    out = await get_user_baseline(session, "user-1", hour_of_day=24)
    assert out == []
    out = await get_user_baseline(session, "user-1", hour_of_day=-1)
    assert out == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_user_baseline_valid_hour_returns_rows():
    fake_row = SimpleNamespace(
        device_id="dev-1",
        device_identifier="watch-001",
        device_type="watch",
        device_status="online",
        hour_of_day=14,
        avg_movement=1.234,
        std_movement=0.5,
        avg_location_switch=0.3,
        std_location_switch=0.2,
        avg_interaction_rate=3.7,
        std_interaction_rate=1.1,
        sample_count=42,
        baseline_updated_at=datetime(2026, 2, 1, 14, 0, tzinfo=timezone.utc),
    )
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = [fake_row]
    session.execute = AsyncMock(return_value=result)

    out = await get_user_baseline(session, "user-1", hour_of_day=14)
    assert len(out) == 1
    assert out[0]["device_id"] == "dev-1"
    assert out[0]["hour_of_day"] == 14
    assert out[0]["avg_movement"] == 1.234
    assert out[0]["sample_count"] == 42
    assert out[0]["baseline_updated_at"] is not None


@pytest.mark.asyncio
async def test_get_user_baselines_24h_passes_user_id_param():
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    out = await get_user_baselines_24h(session, "user-42")
    assert out == []
    # Verify SQL parametrisation
    call_args = session.execute.call_args
    assert call_args.args[1] == {"uid": "user-42"}


# ── _row_to_dict ──────────────────────────────────────────────────


def test_row_to_dict_rounds_and_types():
    row = SimpleNamespace(
        device_id="dev-1",
        device_identifier="x",
        device_type="t",
        device_status="online",
        hour_of_day=9,
        avg_movement=1.23456,
        std_movement=0.98765,
        avg_location_switch=0.123456,
        std_location_switch=0.4321,
        avg_interaction_rate=3.789,
        std_interaction_rate=1.234,
        sample_count=15,
        baseline_updated_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
    )
    d = _row_to_dict(row)
    assert d["avg_movement"] == 1.235
    assert d["std_movement"] == 0.988
    assert d["avg_location_switch"] == 0.123
    assert d["avg_interaction_rate"] == 3.8
    assert d["sample_count"] == 15
    assert "2026-02-01" in d["baseline_updated_at"]


def test_row_to_dict_naive_updated_at_handled():
    row = SimpleNamespace(
        device_id="d", device_identifier="x", device_type="t",
        device_status="online", hour_of_day=0,
        avg_movement=0, std_movement=0, avg_location_switch=0,
        std_location_switch=0, avg_interaction_rate=0,
        std_interaction_rate=0, sample_count=0,
        baseline_updated_at=None,
    )
    d = _row_to_dict(row)
    assert d["baseline_updated_at"] is None


# ── get_refresh_status ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_refresh_status_empty_meta_returns_unknown_shape():
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = None
    session.execute = AsyncMock(return_value=result)

    out = await get_refresh_status(session)
    assert out["last_refreshed_at"] is None
    assert out["last_status"] == "unknown"
    assert out["freshness"] == "unknown"
    assert out["threshold_s"] == STALENESS_THRESHOLD_S


@pytest.mark.asyncio
async def test_get_refresh_status_fresh_row():
    fresh_ts = datetime.now(timezone.utc) - timedelta(hours=2)
    row = SimpleNamespace(
        last_refreshed_at=fresh_ts,
        last_refresh_duration_ms=234.5,
        last_refresh_rows=128,
        last_status="success",
        last_error=None,
    )
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = row
    session.execute = AsyncMock(return_value=result)

    out = await get_refresh_status(session)
    assert out["last_status"] == "success"
    assert out["last_refresh_duration_ms"] == 234.5
    assert out["last_refresh_rows"] == 128
    assert out["freshness"] == "fresh"


@pytest.mark.asyncio
async def test_get_refresh_status_stale_row_flips_verdict():
    stale_ts = datetime.now(timezone.utc) - timedelta(hours=48)
    row = SimpleNamespace(
        last_refreshed_at=stale_ts,
        last_refresh_duration_ms=200.0,
        last_refresh_rows=1,
        last_status="success",
        last_error=None,
    )
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = row
    session.execute = AsyncMock(return_value=result)

    out = await get_refresh_status(session)
    assert out["last_status"] == "success"      # historically succeeded
    assert out["freshness"] == "stale"          # but the data is now stale


# ── Scheduler module sanity ────────────────────────────────────────


def test_scheduler_constants_locked():
    """JOB_ID is locked because `scheduler_metrics` keys off it."""
    from app.services.user_signal_baselines_scheduler import JOB_ID
    assert JOB_ID == "user_signal_baselines_refresh"
