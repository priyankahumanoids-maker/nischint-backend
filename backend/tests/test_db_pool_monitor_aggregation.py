"""REL-04 P1 — tests for the worst-of aggregator in db_pool_monitor.

The 2026-05-30 DR drill exposed a gap: `db_pool_monitor._tick()` only
read the *scheduler process's* pool, missing user-traffic-driven
exhaustion of the *uvicorn process's* pool. The P1 fix has uvicorn
publish its snapshot to Redis and the scheduler-side monitor read it,
taking the worst-of when evaluating the threshold.

These tests verify the aggregator picks the right snapshot under each
combination of inputs.
"""

from app.services.db_pool_monitor import _worst_of


HEALTHY = {
    "pg_pool_size": 20,
    "pg_pool_max_overflow": 10,
    "pg_pool_total_capacity": 30,
    "pg_pool_checked_out": 1,
    "pg_pool_utilization_pct": 3.33,
    "source": "scheduler",
    "available": True,
}

SATURATED = {
    "pg_pool_size": 20,
    "pg_pool_max_overflow": 10,
    "pg_pool_total_capacity": 30,
    "pg_pool_checked_out": 28,
    "pg_pool_utilization_pct": 93.33,
    "source": "uvicorn",
    "available": True,
}

ZERO = {
    "pg_pool_size": 20,
    "pg_pool_max_overflow": 10,
    "pg_pool_total_capacity": 30,
    "pg_pool_checked_out": 0,
    "pg_pool_utilization_pct": 0.0,
    "source": "uvicorn",
    "available": True,
}


def test_remote_missing_returns_local_unchanged():
    """When uvicorn hasn't published anything (Redis empty), use local only."""
    out = _worst_of(HEALTHY, None)
    assert out is HEALTHY


def test_remote_saturated_overrides_idle_local():
    """The original bug: scheduler pool idle, uvicorn pool saturated.
    Without this fix, the monitor evaluated 3.33 % and never fired an
    incident. With the fix, it evaluates the uvicorn 93.33 %.
    """
    out = _worst_of(HEALTHY, SATURATED)
    assert out["pg_pool_utilization_pct"] == 93.33
    assert out["source"] == "uvicorn"
    assert out["pg_pool_checked_out"] == 28


def test_local_saturated_keeps_local_when_remote_idle():
    """Symmetric — if local is the hotter pool, we keep using it."""
    out = _worst_of(SATURATED, ZERO)
    assert out["pg_pool_utilization_pct"] == 93.33
    assert out["source"] == "uvicorn"  # SATURATED came from "uvicorn" in our fixture


def test_remote_with_no_util_returns_local():
    """If the Redis payload is malformed (no util field), don't blow up — fall back to local."""
    bad_remote = {"pg_pool_checked_out": 99}  # no util
    out = _worst_of(HEALTHY, bad_remote)
    assert out is HEALTHY


def test_local_with_no_util_takes_remote():
    """If local is missing util but remote has it, use remote."""
    local_no_util = {"pg_pool_checked_out": 0}
    out = _worst_of(local_no_util, SATURATED)
    assert out["pg_pool_utilization_pct"] == 93.33


def test_tie_keeps_local():
    """When both are equal, prefer local (cheaper — already in hand)."""
    a = {"pg_pool_utilization_pct": 50.0, "source": "scheduler"}
    b = {"pg_pool_utilization_pct": 50.0, "source": "uvicorn"}
    out = _worst_of(a, b)
    assert out["source"] == "scheduler"


def test_remote_empty_dict_returns_local():
    """Defensive — `redis_service.get_json` returning `{}` shouldn't crash."""
    out = _worst_of(HEALTHY, {})
    assert out is HEALTHY


def test_aggregator_preserves_snapshot_fields_from_winner():
    """The threshold engine embeds raw pool numbers from `snapshot` into
    the incident payload — make sure those numbers come from the
    actually-saturated pool, not a stale healthy one.
    """
    out = _worst_of(HEALTHY, SATURATED)
    for k in (
        "pg_pool_size", "pg_pool_max_overflow", "pg_pool_total_capacity",
        "pg_pool_checked_out", "pg_pool_utilization_pct",
    ):
        assert out[k] == SATURATED[k], f"field {k} should come from saturated snapshot"
