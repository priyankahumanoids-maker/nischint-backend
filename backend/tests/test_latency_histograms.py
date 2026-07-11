"""Tests for `latency_histograms` — Redis-backed per-endpoint p50/p95/p99.

Locked contracts:
  * Path normalization happens UP THE STACK (in the middleware) — the
    recorder itself is dumb. We pass templates in directly.
  * `record()` never raises, even on bad input.
  * `get_snapshot` returns percentiles that match a known-distribution.
  * Sort + truncate options work as advertised.
  * `reset_all` wipes both local and Redis state.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import latency_histograms as lh


@pytest.fixture(autouse=True)
def _isolate_state():
    """Each test starts with a clean in-process buffer.

    We force Redis-OFF by stubbing `_redis()` to return None — these
    are unit tests, not integration tests. Redis-on coverage happens
    in the manual smoke test at the bottom of the bundle.
    """
    with patch.object(lh, "_redis", return_value=None):
        lh.reset_all()
        yield
        lh.reset_all()


# ────────────────────────────────────────────────────────────
# 1. Recorder contract
# ────────────────────────────────────────────────────────────


def test_record_writes_to_local_buffer():
    lh.record("GET", "/api/health", 200, 12.5)
    snap = lh.snapshot_endpoint("GET /api/health")
    assert snap["samples"] == 1
    assert snap["p50_ms"] == 12.5
    assert snap["p95_ms"] == 12.5
    assert snap["p99_ms"] == 12.5
    assert snap["total_requests"] == 1
    assert snap["error_count"] == 0
    assert snap["error_rate"] == 0.0


def test_record_never_raises_on_bad_input():
    # Empty method / route — must silently no-op.
    lh.record("", "/api/health", 200, 10)
    lh.record("GET", "", 200, 10)
    # Negative duration — clamped to 0, recorded.
    lh.record("GET", "/api/x", 200, -5)
    snap = lh.snapshot_endpoint("GET /api/x")
    assert snap["samples"] == 1
    assert snap["p50_ms"] == 0.0


def test_record_counts_errors_only_on_5xx():
    lh.record("GET", "/api/x", 200, 10)
    lh.record("GET", "/api/x", 404, 10)
    lh.record("GET", "/api/x", 500, 10)
    lh.record("GET", "/api/x", 503, 10)
    snap = lh.snapshot_endpoint("GET /api/x")
    assert snap["total_requests"] == 4
    assert snap["error_count"] == 2
    assert snap["error_rate"] == 0.5


# ────────────────────────────────────────────────────────────
# 2. Percentile maths
# ────────────────────────────────────────────────────────────


def test_percentiles_on_known_distribution():
    """100 samples evenly distributed 1..100.

    Nearest-rank, indices into a 100-element sorted list:
      p50 → round(0.50 * 99) = 50 → list[50] = 51
      p95 → round(0.95 * 99) = 94 → list[94] = 95
      p99 → round(0.99 * 99) = 98 → list[98] = 99
    """
    for i in range(1, 101):
        lh.record("GET", "/api/x", 200, float(i))
    snap = lh.snapshot_endpoint("GET /api/x")
    assert snap["samples"] == 100
    assert snap["p50_ms"] == 51.0
    assert snap["p95_ms"] == 95.0
    assert snap["p99_ms"] == 99.0
    assert snap["min_ms"] == 1.0
    assert snap["max_ms"] == 100.0


def test_rolling_window_truncates_to_max_samples():
    # MAX_SAMPLES is 500 — feed 600, only last 500 should remain.
    # The new sample (LPUSH semantics on the Redis side; deque maxlen
    # on the local side) keeps the *latest* MAX_SAMPLES.
    for i in range(600):
        lh.record("GET", "/api/x", 200, float(i))
    snap = lh.snapshot_endpoint("GET /api/x")
    assert snap["samples"] == lh.MAX_SAMPLES
    # Total counter is cumulative — never trimmed.
    assert snap["total_requests"] == 600


def test_empty_endpoint_returns_none_percentiles():
    snap = lh.snapshot_endpoint("GET /api/never-hit")
    assert snap["samples"] == 0
    assert snap["p50_ms"] is None
    assert snap["p95_ms"] is None
    assert snap["p99_ms"] is None


# ────────────────────────────────────────────────────────────
# 3. Bulk snapshot — sort + truncate
# ────────────────────────────────────────────────────────────


def test_get_snapshot_sorts_by_p95_desc_by_default():
    lh.record("GET", "/api/fast", 200, 5.0)
    lh.record("GET", "/api/slow", 200, 1000.0)
    lh.record("GET", "/api/medium", 200, 50.0)

    snap = lh.get_snapshot()
    assert snap["endpoint_count"] == 3
    eps = [e["endpoint"] for e in snap["endpoints"]]
    assert eps == ["GET /api/slow", "GET /api/medium", "GET /api/fast"]


def test_get_snapshot_top_n_truncates():
    for n in range(10):
        lh.record("GET", f"/api/x{n}", 200, float(n * 100))
    snap = lh.get_snapshot(top_n=3)
    assert len(snap["endpoints"]) == 3
    # Top-3 by p95 desc: x9, x8, x7
    assert [e["endpoint"] for e in snap["endpoints"]] == [
        "GET /api/x9", "GET /api/x8", "GET /api/x7",
    ]


def test_get_snapshot_sort_by_total_requests():
    for _ in range(5):
        lh.record("GET", "/api/busy", 200, 10.0)
    lh.record("GET", "/api/quiet", 200, 999.0)

    snap = lh.get_snapshot(sort_by="total_requests")
    assert snap["sort_by"] == "total_requests"
    assert snap["endpoints"][0]["endpoint"] == "GET /api/busy"


def test_get_snapshot_invalid_sort_falls_back_to_p95():
    lh.record("GET", "/api/x", 200, 10)
    snap = lh.get_snapshot(sort_by="evil_field")
    assert snap["sort_by"] == "p95_ms"


def test_hot_endpoints_flag_set_correctly():
    lh.record("GET", "/api/health", 200, 10)
    lh.record("GET", "/api/some-random", 200, 10)
    snap = lh.get_snapshot()
    by_ep = {e["endpoint"]: e for e in snap["endpoints"]}
    assert by_ep["GET /api/health"]["is_hot"] is True
    assert by_ep["GET /api/some-random"]["is_hot"] is False


# ────────────────────────────────────────────────────────────
# 4. Reset
# ────────────────────────────────────────────────────────────


def test_reset_all_wipes_local_state():
    lh.record("GET", "/api/x", 200, 10)
    lh.record("GET", "/api/y", 500, 20)
    assert lh.get_snapshot()["endpoint_count"] == 2

    out = lh.reset_all()
    assert out["local_endpoints_cleared"] == 2
    # No matter what Redis returns (we stubbed it None), local IS empty.
    assert lh.get_snapshot()["endpoint_count"] == 0
