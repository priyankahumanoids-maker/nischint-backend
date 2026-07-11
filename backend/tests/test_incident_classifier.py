"""Unit tests for `incident_classifier.classify_root_cause`.

Locks the upstream-first (queue → ai → scheduler) heuristic.
"""
from app.services.incident_classifier import classify_root_cause


def _snap(*, scheduler=None, ai=None, queue=None):
    return {
        "scheduler": scheduler or {},
        "ai":        ai or {},
        "queue":     queue or {},
    }


# ── Pure-domain breaches (one at a time) ────────────────────────────
def test_only_scheduler_breach_drift():
    s = _snap(scheduler={"drift_p95_ms": 1200})
    assert classify_root_cause(s, trigger_source="scheduler") == "scheduler"


def test_only_scheduler_breach_missed_jobs():
    s = _snap(scheduler={"drift_p95_ms": 50, "missed_total": 3})
    assert classify_root_cause(s, trigger_source="scheduler") == "scheduler"


def test_only_ai_breach_p95():
    s = _snap(ai={"p95_ms": 4500})
    assert classify_root_cause(s, trigger_source="ai") == "ai"


def test_only_ai_breach_error_rate():
    s = _snap(ai={"p95_ms": 100, "error_count": 5, "samples": 20})
    assert classify_root_cause(s, trigger_source="ai") == "ai"


def test_only_queue_breach_pending_total():
    s = _snap(queue={"pending_total": 250})
    assert classify_root_cause(s, trigger_source="queue") == "queue"


def test_only_queue_breach_by_stream_shape():
    s = _snap(queue={"by_stream": {"ai_signal": {"pending": 600}}})
    assert classify_root_cause(s, trigger_source="ai") == "queue"


# ── Multi-domain — upstream-first wins ───────────────────────────────
def test_queue_wins_over_ai():
    s = _snap(queue={"pending_total": 200}, ai={"p95_ms": 5000})
    assert classify_root_cause(s, trigger_source="ai") == "queue"


def test_queue_wins_over_scheduler():
    s = _snap(queue={"pending_total": 150}, scheduler={"drift_p95_ms": 2000})
    assert classify_root_cause(s, trigger_source="scheduler") == "queue"


def test_ai_wins_over_scheduler():
    s = _snap(ai={"p95_ms": 4000}, scheduler={"drift_p95_ms": 900})
    assert classify_root_cause(s, trigger_source="scheduler") == "ai"


def test_all_three_breach_picks_queue():
    s = _snap(
        queue={"pending_total": 800},
        ai={"p95_ms": 6000},
        scheduler={"drift_p95_ms": 1800},
    )
    assert classify_root_cause(s, trigger_source="scheduler") == "queue"


# ── Defensive fall-back when nothing crossed ─────────────────────────
def test_no_breach_falls_back_to_trigger_source():
    s = _snap(scheduler={"drift_p95_ms": 10}, ai={"p95_ms": 100}, queue={"pending_total": 0})
    assert classify_root_cause(s, trigger_source="ai") == "ai"


def test_no_breach_no_trigger_defaults_to_scheduler():
    s = _snap()
    assert classify_root_cause(s) == "scheduler"


def test_unavailable_subsnaps_dont_explode():
    # Mirrors `_capture_snapshot`'s "unavailable" fall-back shape.
    s = {"scheduler": {"error": "unavailable"},
         "ai":        {"error": "unavailable"},
         "queue":     {"error": "unavailable"}}
    assert classify_root_cause(s, trigger_source="ai") == "ai"


def test_empty_snapshot_no_trigger():
    assert classify_root_cause(None) == "scheduler"
    assert classify_root_cause({}) == "scheduler"


def test_threshold_edges():
    # AI just below 3000 → no AI breach; scheduler drift just above 750 → scheduler wins.
    s = _snap(ai={"p95_ms": 2999}, scheduler={"drift_p95_ms": 800})
    assert classify_root_cause(s, trigger_source="scheduler") == "scheduler"
    # AI exactly at 3000 → AI breach.
    s2 = _snap(ai={"p95_ms": 3000}, scheduler={"drift_p95_ms": 800})
    assert classify_root_cause(s2, trigger_source="scheduler") == "ai"
