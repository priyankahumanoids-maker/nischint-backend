"""REL-04 — Tests for pg_stat_activity post-mortem capture.

We don't drive a real saturating workload here. Instead we:
  1. Mock the asyncpg pool's `acquire().fetch()` to return canned rows
     → verify the shape we hand to the snapshot column.
  2. Mock `get_pool_stats` to return various utilization levels →
     verify the gating in `_capture_snapshot` (capture iff util ≥ 85%
     OR wait_count > 0).
"""
from __future__ import annotations

from typing import Any

import pytest


# ── Fixtures: asyncpg pool mock ────────────────────────────────────


class _FakeRecord(dict):
    """asyncpg.Record is dict-like (`r["column"]`). dict subclass is
    a close-enough stand-in for tests."""


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    async def fetch(self, *_args, **_kw):
        return [_FakeRecord(r) for r in self._rows]


class _FakeAcquireCM:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc):
        return False


class _FakePool:
    def __init__(self, rows: list[dict[str, Any]] | None = None,
                 fail_fetch: bool = False):
        self._rows = rows or []
        self._fail = fail_fetch

    def acquire(self):
        if self._fail:
            class _RaisingCM:
                async def __aenter__(_self):
                    raise RuntimeError("pg-down")
                async def __aexit__(_self, *_exc):
                    return False
            return _RaisingCM()
        return _FakeAcquireCM(_FakeConn(self._rows))


# ── capture_top_queries ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_returns_normalised_rows(monkeypatch):
    """Captured rows must be plain dicts with float duration_ms."""
    rows = [
        {
            "pid": 12345,
            "duration_ms": 17234.5,
            "state": "active",
            "wait_event_type": "Lock",
            "wait_event": "transactionid",
            "application_name": "backend",
            "usename": "postgres",
            "query": "SELECT * FROM users WHERE …",
        },
    ]
    fake_pool = _FakePool(rows=rows)

    async def fake_get_pool():
        return fake_pool

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    from app.db.pg_diagnostics import capture_top_queries
    out = await capture_top_queries()
    assert len(out) == 1
    r = out[0]
    assert r["pid"] == 12345
    assert isinstance(r["duration_ms"], float)
    assert r["state"] == "active"
    assert r["wait_event_type"] == "Lock"
    assert r["wait_event"] == "transactionid"
    assert r["query"].startswith("SELECT")


@pytest.mark.asyncio
async def test_capture_empty_when_pool_unavailable(monkeypatch):
    """Diagnostic path must never throw — failure → []."""
    async def fake_get_pool():
        raise RuntimeError("dsn-broken")

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    from app.db.pg_diagnostics import capture_top_queries
    out = await capture_top_queries()
    assert out == []


@pytest.mark.asyncio
async def test_capture_empty_when_query_raises(monkeypatch):
    fake_pool = _FakePool(fail_fetch=True)

    async def fake_get_pool():
        return fake_pool

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    from app.db.pg_diagnostics import capture_top_queries
    out = await capture_top_queries()
    assert out == []


@pytest.mark.asyncio
async def test_capture_handles_null_wait_event(monkeypatch):
    """A backend with `wait_event = NULL` must serialise cleanly."""
    fake_pool = _FakePool(rows=[{
        "pid": 7,
        "duration_ms": 42.0,
        "state": "active",
        "wait_event_type": None,
        "wait_event": None,
        "application_name": None,
        "usename": "postgres",
        "query": "SELECT 1",
    }])

    async def fake_get_pool():
        return fake_pool

    monkeypatch.setattr("app.db.session.get_db_pool", fake_get_pool)

    from app.db.pg_diagnostics import capture_top_queries
    out = await capture_top_queries()
    assert out[0]["wait_event"] is None
    assert out[0]["wait_event_type"] is None


# ── _capture_snapshot gating ───────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_skips_capture_when_pool_healthy(monkeypatch):
    """At 50% utilization with no waiters, we must NOT pay the
    pg_stat_activity round-trip on every transition."""
    monkeypatch.setattr(
        "app.db.pool_stats.get_pool_stats",
        lambda: {
            "available": True,
            "pg_pool_utilization_pct": 50.0,
            "pg_pool_wait_count": 0,
        },
    )

    called = {"capture": False}

    async def stub_capture():
        called["capture"] = True
        return [{"pid": 1}]

    monkeypatch.setattr("app.db.pg_diagnostics.capture_top_queries", stub_capture)

    # Stub out the other snapshot pieces — they may need scheduler
    # metrics / redis we don't care about here.
    monkeypatch.setattr(
        "app.services.scheduler_metrics.metric_snapshot",
        lambda: {"missed_total": 0, "drift_p95": 0},
        raising=False,
    )

    from app.services import system_incident_engine
    snap = await system_incident_engine._capture_snapshot()

    assert snap.get("pg_stat_activity_top") == []
    assert called["capture"] is False, "must not query pg_stat_activity below threshold"


@pytest.mark.asyncio
async def test_snapshot_captures_when_utilization_high(monkeypatch):
    monkeypatch.setattr(
        "app.db.pool_stats.get_pool_stats",
        lambda: {
            "available": True,
            "pg_pool_utilization_pct": 92.5,
            "pg_pool_wait_count": 0,
        },
    )

    canned = [{"pid": 42, "duration_ms": 9000.0, "state": "active",
               "wait_event_type": "IO", "wait_event": "DataFileRead",
               "application_name": "backend", "usename": "postgres",
               "query": "UPDATE huge_table SET …"}]

    async def stub_capture():
        return canned

    monkeypatch.setattr("app.db.pg_diagnostics.capture_top_queries", stub_capture)

    from app.services import system_incident_engine
    snap = await system_incident_engine._capture_snapshot()

    top = snap.get("pg_stat_activity_top", [])
    assert len(top) == 1
    assert top[0]["pid"] == 42
    assert top[0]["wait_event"] == "DataFileRead"


@pytest.mark.asyncio
async def test_snapshot_captures_on_waiters_even_if_util_low(monkeypatch):
    """A process that just dropped below 85% but still has waiters
    queued up is STILL in trouble — we must capture."""
    monkeypatch.setattr(
        "app.db.pool_stats.get_pool_stats",
        lambda: {
            "available": True,
            "pg_pool_utilization_pct": 80.0,
            "pg_pool_wait_count": 3,
        },
    )

    canned = [{"pid": 99, "duration_ms": 50.0, "state": "active",
               "wait_event_type": None, "wait_event": None,
               "application_name": "backend", "usename": "postgres",
               "query": "SELECT 1"}]

    async def stub_capture():
        return canned

    monkeypatch.setattr("app.db.pg_diagnostics.capture_top_queries", stub_capture)

    from app.services import system_incident_engine
    snap = await system_incident_engine._capture_snapshot()

    assert len(snap.get("pg_stat_activity_top", [])) == 1


@pytest.mark.asyncio
async def test_snapshot_does_not_propagate_capture_failures(monkeypatch):
    """A failing pg_stat_activity capture must NOT break the
    incident-open path — degrade gracefully to []."""
    monkeypatch.setattr(
        "app.db.pool_stats.get_pool_stats",
        lambda: {
            "available": True,
            "pg_pool_utilization_pct": 99.0,
            "pg_pool_wait_count": 0,
        },
    )

    async def stub_capture():
        raise RuntimeError("oh no")

    monkeypatch.setattr("app.db.pg_diagnostics.capture_top_queries", stub_capture)

    from app.services import system_incident_engine
    snap = await system_incident_engine._capture_snapshot()

    assert snap["pg_stat_activity_top"] == []
