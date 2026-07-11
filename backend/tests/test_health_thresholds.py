"""Threshold-engine tests — locks the golden rule contract.

Critical: WS is for state change, not telemetry stream. These tests
prove the engine never emits except on a real transition.
"""
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, "/app/backend")
os.environ.setdefault("NISCHINT_ROLE", "all")

from app.services import health_thresholds as ht  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """In-memory fake of the prev-state cache + capture every emit."""
    state = {}

    def fake_read(source):
        return state.get(source)

    def fake_write(source, payload):
        state[source] = payload

    emitted: list[dict] = []

    def fake_emit(payload):
        emitted.append(payload)

    monkeypatch.setattr(ht, "_read_prev", fake_read)
    monkeypatch.setattr(ht, "_write_prev", fake_write)
    monkeypatch.setattr(ht, "_emit", fake_emit)
    yield emitted


def test_classifier_scheduler():
    # Missed jobs always degrade.
    assert ht._classify_scheduler(100, 1, 0)[0] == "degraded"
    # Drift beyond SLA → degraded.
    assert ht._classify_scheduler(2000, 0, 0)[0] == "degraded"
    # Errors with no drift / miss → warning.
    assert ht._classify_scheduler(100, 0, 1)[0] == "warning"
    # Clean → healthy.
    assert ht._classify_scheduler(100, 0, 0)[0] == "healthy"


def test_classifier_ai_requires_min_samples():
    # Fewer than 3 samples → never degraded even with extreme p95.
    assert ht._classify_ai(99999, 0, 1) == ("healthy", None, None)
    assert ht._classify_ai(99999, 0, 3)[0] == "degraded"


def test_classifier_queue_bands():
    assert ht._classify_queue(50)[0] == "healthy"
    assert ht._classify_queue(150)[0] == "warning"
    assert ht._classify_queue(900)[0] == "degraded"


def test_first_transition_emits(_isolate):
    emitted = _isolate
    # Cold start: first observation = degraded → emit.
    ht.evaluate_scheduler_state(2000, 0, 0)
    assert len(emitted) == 1
    assert emitted[0]["severity"] == "degraded"
    assert emitted[0]["source"] == "scheduler"
    assert emitted[0]["metric"] == "drift_p95"
    assert emitted[0]["previous_severity"] is None


def test_repeated_same_severity_does_not_emit(_isolate):
    emitted = _isolate
    ht.evaluate_scheduler_state(2000, 0, 0)
    ht.evaluate_scheduler_state(2200, 0, 0)
    ht.evaluate_scheduler_state(2500, 0, 0)
    # Only the first transition emits — same severity + same metric stays silent.
    assert len(emitted) == 1


def test_state_transition_back_to_healthy_emits(_isolate):
    emitted = _isolate
    ht.evaluate_scheduler_state(2000, 0, 0)
    # Wait past cooldown
    time.sleep(ht.EMIT_COOLDOWN_S + 0.1)
    ht.evaluate_scheduler_state(500, 0, 0)
    severities = [e["severity"] for e in emitted]
    assert severities == ["degraded", "healthy"]


def test_metric_change_within_same_severity_silent(_isolate):
    emitted = _isolate
    # Both crosses on different metrics within same severity band.
    ht.evaluate_scheduler_state(2000, 0, 0)        # degraded via drift
    ht.evaluate_scheduler_state(800, 1, 0)         # degraded via missed
    # Two emits — different driving metric so worth surfacing for the
    # operator. But repeating the same drift→drift would not.
    ht.evaluate_scheduler_state(900, 1, 0)
    severities_metrics = [(e["severity"], e["metric"]) for e in emitted]
    assert severities_metrics == [
        ("degraded", "drift_p95"),
        ("degraded", "missed_jobs"),
    ]


def test_ai_threshold_emits_only_on_cross(_isolate):
    emitted = _isolate
    ht.evaluate_ai_state(800, 0, 5)         # healthy
    ht.evaluate_ai_state(2900, 0, 5)        # still healthy (under SLA)
    ht.evaluate_ai_state(3500, 0, 5)        # degraded — emit
    # Replays inside same severity stay silent.
    ht.evaluate_ai_state(4000, 0, 6)
    assert len(emitted) == 1
    assert emitted[0]["severity"] == "degraded"
    assert emitted[0]["source"] == "ai"


def test_queue_warn_to_degraded_transition(_isolate):
    emitted = _isolate
    ht.evaluate_queue_state(150)   # warning
    ht.evaluate_queue_state(180)   # silent
    ht.evaluate_queue_state(900)   # degraded
    severities = [e["severity"] for e in emitted]
    assert severities == ["warning", "degraded"]


def test_payload_shape_carries_threshold_and_value(_isolate):
    emitted = _isolate
    ht.evaluate_scheduler_state(1500, 0, 0)
    p = emitted[0]
    for k in ("type", "ts", "severity", "source", "metric", "value", "threshold", "previous_severity"):
        assert k in p, f"missing key {k}"
    assert p["type"] == "system_health_delta"
    assert p["value"] == 1500.0
    assert p["threshold"] == float(ht.SCHED_DRIFT_P95_MS)
