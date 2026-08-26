"""Tests for the scheduler-health metrics layer.

Exercises the recorder + snapshot without spinning up real APScheduler
jobs ? we synthesize EVENT_JOB_SUBMITTED / EXECUTED / MISSED / ERROR objects.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, "/app/backend")
os.environ.setdefault("NISCHINT_ROLE", "all")

from app.services import scheduler_metrics as sm  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    sm._stats.clear()
    sm._attached_schedulers.clear()
    # Force every code path inside scheduler_metrics to skip Redis so tests
    # only see in-process state.
    monkeypatch.setattr(sm, "_redis", lambda: None)
    yield
    sm._stats.clear()
    sm._attached_schedulers.clear()


def _evt(job_id, scheduled_seconds_ago=0, retval=None, exc=None):
    return SimpleNamespace(
        job_id=job_id,
        scheduled_run_time=datetime.now(timezone.utc) - timedelta(seconds=scheduled_seconds_ago),
        retval=retval,
        exception=exc,
    )


def _submitted_evt(job_id, scheduled_seconds_ago=0):
    return SimpleNamespace(
        job_id=job_id,
        scheduled_run_times=[
            datetime.now(timezone.utc)
            - timedelta(
                seconds=scheduled_seconds_ago
            )
        ],
    )


def test_submitted_records_dispatch_drift_and_executed_records_duration():
    sm._on_submitted(
        _submitted_evt(
            "j1",
            scheduled_seconds_ago=2,
        ),
        "owner.x",
    )

    sm._on_executed(
        _evt(
            "j1",
            scheduled_seconds_ago=2,
            retval={"_duration_ms": 130},
        ),
        "owner.x",
    )

    snap = sm.get_snapshot()

    assert snap["scheduler_count"] == 1

    j = snap["jobs"][0]

    assert j["id"] == "j1"
    assert j["owner"] == "owner.x"
    assert j["success_count"] == 1
    assert j["last_duration_ms"] == 130.0
    assert 1900 <= j["last_run_drift_ms"] <= 2100
    assert j["last_status"] == "success"


def test_execution_completion_time_does_not_inflate_dispatch_drift():
    sm._on_submitted(
        _submitted_evt(
            "j_runtime",
            scheduled_seconds_ago=0,
        ),
        "owner.runtime",
    )

    before = (
        sm._stats[
            "j_runtime"
        ].last_run_drift_ms
    )

    assert before is not None
    assert before < 500

    # Simulate a completion event 30 seconds after the
    # scheduled time. Completion latency must not become drift.
    sm._on_executed(
        _evt(
            "j_runtime",
            scheduled_seconds_ago=30,
            retval={
                "_duration_ms": 30000
            },
        ),
        "owner.runtime",
    )

    state = sm._stats[
        "j_runtime"
    ]

    assert state.last_run_drift_ms == before
    assert state.last_duration_ms == 30000.0
    assert state.success_count == 1


def test_missed_increments_count_and_marks_status():
    sm._on_missed(_evt("j2"), "owner.y")
    snap = sm.get_snapshot()
    j = snap["jobs"][0]
    assert j["missed_count"] == 1
    assert j["last_status"] == "missed"
    assert snap["status"] == "degraded"  # any missed → degraded


def test_error_records_message_and_marks_status():
    sm._on_error(_evt("j3", exc=RuntimeError("boom")), "owner.z")
    snap = sm.get_snapshot()
    j = snap["jobs"][0]
    assert j["error_count"] == 1
    assert "boom" in (j["last_error"] or "")
    assert j["last_status"] == "error"
    assert snap["status"] == "warning"


def test_drift_percentiles_use_rolling_window():
    for s in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        sm._on_submitted(_submitted_evt("j_p", scheduled_seconds_ago=s), "x")
    snap = sm.get_snapshot()
    j = snap["jobs"][0]
    assert j["drift_p50_ms"] is not None
    assert j["drift_p95_ms"] is not None
    assert j["drift_p95_ms"] >= j["drift_p50_ms"]
    # Largest sample was ~10s = 10000ms
    assert 9000 <= j["drift_p95_ms"] <= 11000


def test_status_degraded_when_p95_exceeds_one_second():
    sm._on_submitted(_submitted_evt("slow", scheduled_seconds_ago=2), "x")
    assert sm.get_snapshot()["status"] == "degraded"


def test_status_healthy_when_no_drift_and_no_failures():
    # Schedule a "now" event — drift ~ 0
    sm._on_submitted(_submitted_evt("fast", scheduled_seconds_ago=0), "x")
    snap = sm.get_snapshot()
    assert snap["status"] == "healthy"
    assert snap["error_total"] == 0
    assert snap["missed_total"] == 0


def test_reset_drift_baseline_clears_rolling_window():
    for s in (1, 2, 3):
        sm._on_submitted(_submitted_evt("j_reset", scheduled_seconds_ago=s), "x")
    before = sm.get_snapshot()["jobs"][0]["drift_p95_ms"]
    assert before is not None
    sm.reset_drift_baseline()
    after = sm.get_snapshot()["jobs"][0]["drift_p95_ms"]
    assert after is None  # rolling window cleared


def test_attach_is_idempotent():
    class FakeScheduler:
        running = True
        def __init__(self): self.listeners = []
        def add_listener(self, fn, mask): self.listeners.append((fn, mask))

    s = FakeScheduler()
    assert sm.attach(s, owner="m1") is True
    assert sm.attach(s, owner="m1") is False
    assert len(s.listeners) == 4  # submitted, executed, missed, error
