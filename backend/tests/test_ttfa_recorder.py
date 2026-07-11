"""Tests for NISCH-003 — TTFA recorder + percentile maths.

Pure unit tests against the recorder. Endpoint integration is covered
in test_dev_endpoints.py.
"""
from __future__ import annotations

import time

import pytest

from app.services import ttfa_recorder


@pytest.fixture(autouse=True)
def _clean_buffer(monkeypatch):
    # Skip Redis mirror to keep these tests pure / fast.
    monkeypatch.setattr(
        "app.services.ttfa_recorder.redis_service.is_available", lambda: False
    )
    ttfa_recorder.reset_buffer()
    yield
    ttfa_recorder.reset_buffer()


# ── Empty state ─────────────────────────────────────────────────────
def test_empty_buffer_returns_zeros():
    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    assert out["samples_considered"] == 0
    assert out["overall"]["count"] == 0
    assert out["overall"]["p50"] == 0
    assert out["overall"]["p95"] == 0
    assert out["by_kind"] == {}


# ── Recording + summarization ───────────────────────────────────────
def test_records_sample_and_computes_percentiles():
    for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        ttfa_recorder.record(kind="voice_distress", ttfa_ms=ms)

    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    assert out["samples_considered"] == 10
    overall = out["overall"]
    assert overall["count"] == 10
    assert overall["min"] == 10
    assert overall["max"] == 100
    assert overall["mean"] == 55
    # p50 of [10..100] step 10 → 55 (linear interp)
    assert overall["p50"] == 55
    assert overall["p95"] >= 90
    assert overall["p99"] >= 95


def test_per_kind_breakdown():
    for ms in (50, 60, 70):
        ttfa_recorder.record(kind="sos", ttfa_ms=ms)
    for ms in (10, 20):
        ttfa_recorder.record(kind="low_battery", ttfa_ms=ms)

    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    assert set(out["by_kind"].keys()) == {"sos", "low_battery"}
    assert out["by_kind"]["sos"]["count"] == 3
    assert out["by_kind"]["low_battery"]["count"] == 2
    assert out["by_kind"]["sos"]["p50"] == 60
    assert out["by_kind"]["low_battery"]["p50"] == 15


def test_filter_kind_focuses_subblock():
    for ms in (50, 60, 70):
        ttfa_recorder.record(kind="sos", ttfa_ms=ms)
    for ms in (10, 20):
        ttfa_recorder.record(kind="low_battery", ttfa_ms=ms)

    out = ttfa_recorder.get_stats(since_s=3600, kind="sos", include_redis=False)
    assert out["filter_kind"] == "sos"
    assert out["filter_kind_stats"]["count"] == 3
    # by_kind still includes everyone
    assert "low_battery" in out["by_kind"]


# ── Time window filter ──────────────────────────────────────────────
def test_since_window_excludes_old_samples():
    # Manually inject a synthetic-old sample and a fresh one
    ttfa_recorder._BUFFER.append({
        "kind": "sos", "ttfa_ms": 999, "ts": time.time() - 7200,
        "guardians": 1, "louder": True, "priority": "critical",
    })
    ttfa_recorder.record(kind="sos", ttfa_ms=42)

    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    # Only the fresh one should be counted
    assert out["samples_considered"] == 1
    assert out["overall"]["min"] == 42 == out["overall"]["max"]


def test_since_zero_means_no_cap():
    ttfa_recorder._BUFFER.append({
        "kind": "sos", "ttfa_ms": 999, "ts": time.time() - 86400,
        "guardians": 1, "louder": True, "priority": "critical",
    })
    out = ttfa_recorder.get_stats(since_s=0, include_redis=False)
    assert out["samples_considered"] == 1


# ── Robustness — never raises ──────────────────────────────────────
def test_record_never_raises_on_garbage():
    # Should swallow everything quietly
    ttfa_recorder.record(kind=None, ttfa_ms="abc")  # type: ignore[arg-type]
    ttfa_recorder.record(kind="sos", ttfa_ms=123, priority=None)
    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    # at least the valid sample lands
    assert out["samples_considered"] >= 1


def test_louder_ratio_computed():
    ttfa_recorder.record(kind="sos", ttfa_ms=50, louder=True)
    ttfa_recorder.record(kind="sos", ttfa_ms=60, louder=False)
    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    assert out["overall"]["louder_ratio"] == 0.5


# ── Ring-buffer cap ────────────────────────────────────────────────
def test_ring_buffer_caps_at_max_samples():
    cap = ttfa_recorder._MAX_SAMPLES
    for ms in range(cap + 50):
        ttfa_recorder.record(kind="sos", ttfa_ms=ms)
    out = ttfa_recorder.get_stats(since_s=3600, include_redis=False)
    # Should not exceed cap
    assert out["samples_considered"] <= cap
    assert out["overall"]["count"] <= cap


# ── Percentile maths sanity ────────────────────────────────────────
def test_percentile_helper_edges():
    f = ttfa_recorder._percentile
    assert f([], 50) == 0
    assert f([100], 50) == 100
    assert f([10, 20], 0) == 10
    assert f([10, 20], 100) == 20
    assert f([10, 20], 50) == 15
