"""Auth-domain root-cause classification tests.

Locks the contract:
  * `trigger_source="auth"` MUST classify into `db` or `redis`, never
    `scheduler` / `ai` / `queue`.
  * Redis-probe signal wins over miss-rate signal.
  * Default fallback when both signals are clean = `db` (the historical
    dominant suspect on the Mumbai pooler).
"""
from __future__ import annotations

from app.services.incident_classifier import classify_root_cause


def _snap(*, auth=None, redis=None, scheduler=None, ai=None, queue=None) -> dict:
    return {
        "taken_at":  "2026-05-25T10:00:00+00:00",
        "scheduler": scheduler or {},
        "ai":        ai or {},
        "queue":     queue or {},
        "auth":      auth or {},
        "redis":     redis or {},
    }


# ── Redis-probe signal wins ──────────────────────────────────────────


def test_auth_redis_unavailable_classifies_redis():
    snap = _snap(
        auth={"p95_ms": 800.0, "samples": 10, "misses_window": 0},
        redis={"available": False},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "redis"


def test_auth_redis_slow_ping_classifies_redis():
    snap = _snap(
        auth={"p95_ms": 800.0, "samples": 10, "misses_window": 0},
        redis={"available": True, "ping_ms": 250.0},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "redis"


def test_auth_redis_fast_ping_does_not_classify_redis():
    snap = _snap(
        auth={"p95_ms": 800.0, "samples": 10, "misses_window": 7},
        redis={"available": True, "ping_ms": 5.0},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "db"


# ── Miss-rate signal ─────────────────────────────────────────────────


def test_auth_high_miss_rate_classifies_db():
    snap = _snap(
        auth={"p95_ms": 1800.0, "samples": 10, "misses_window": 5},
        redis={"available": True, "ping_ms": 5.0},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "db"


def test_auth_low_miss_rate_default_classifies_db():
    """Default fallback — Mumbai pooler is the historical suspect."""
    snap = _snap(
        auth={"p95_ms": 700.0, "samples": 10, "misses_window": 0},
        redis={"available": True, "ping_ms": 5.0},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "db"


def test_auth_miss_rate_threshold_is_strict():
    # 29 % miss rate → below the 30 % trigger → still defaults to db.
    snap = _snap(
        auth={"p95_ms": 700.0, "samples": 100, "misses_window": 29},
        redis={"available": True, "ping_ms": 5.0},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "db"


# ── Auth axis is independent of queue/ai/scheduler ────────────────────


def test_auth_source_ignores_unrelated_queue_breach():
    """Even with a queue breach in the snapshot, auth-source must
    classify on the auth/redis axis (not queue)."""
    snap = _snap(
        auth={"p95_ms": 800.0, "samples": 10, "misses_window": 0},
        redis={"available": False},
        queue={"pending_total": 5000},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "redis"


def test_auth_source_ignores_unrelated_scheduler_drift():
    snap = _snap(
        auth={"p95_ms": 1500.0, "samples": 10, "misses_window": 6},
        redis={"available": True, "ping_ms": 8.0},
        scheduler={"drift_p95_ms": 5000.0, "missed_total": 3},
    )
    assert classify_root_cause(snap, trigger_source="auth") == "db"


# ── Defensive: empty snapshot ────────────────────────────────────────


def test_auth_empty_snapshot_falls_back_to_db():
    assert classify_root_cause({}, trigger_source="auth") == "db"


def test_auth_none_snapshot_falls_back_to_db():
    assert classify_root_cause(None, trigger_source="auth") == "db"


# ── Existing axes still work (regression) ─────────────────────────────


def test_queue_axis_still_classified_queue():
    snap = _snap(queue={"pending_total": 200})
    assert classify_root_cause(snap, trigger_source="ai") == "queue"


def test_scheduler_axis_still_classified_scheduler():
    snap = _snap(scheduler={"drift_p95_ms": 5000.0})
    assert classify_root_cause(snap, trigger_source="scheduler") == "scheduler"
