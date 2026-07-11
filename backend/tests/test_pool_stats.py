"""REL-04 — Tests for `get_pool_stats()` introspection.

Pin the shape and the fallback behaviour. We don't try to drive real
checkout/return cycles here — that's covered by the live curl smoke
against `/api/admin/monitoring/runtime-info` during deploy.
"""
from __future__ import annotations

import pytest

from app.db.pool_stats import get_pool_stats


def test_returns_stable_keys():
    stats = get_pool_stats()
    expected = {
        "pg_pool_size",
        "pg_pool_max_overflow",
        "pg_pool_checked_out",
        "pg_pool_checked_in",
        "pg_pool_overflow",
        "pg_pool_total_capacity",
        "pg_pool_utilization_pct",
        "pg_pool_wait_count",
        "available",
    }
    assert expected.issubset(stats.keys())


def test_available_implies_numeric_fields():
    stats = get_pool_stats()
    if not stats["available"]:
        pytest.skip("engine not initialised in this test runner")
    # When available, every count field must be an int.
    for k in (
        "pg_pool_size",
        "pg_pool_checked_out",
        "pg_pool_checked_in",
        "pg_pool_overflow",
        "pg_pool_total_capacity",
        "pg_pool_wait_count",
    ):
        assert isinstance(stats[k], int), f"{k} must be int when available"
    # Utilization must be a float in [0, ~100+] — overflow can push
    # checked_out beyond pool_size temporarily, so we don't cap at 100.
    assert isinstance(stats["pg_pool_utilization_pct"], float)
    assert stats["pg_pool_utilization_pct"] >= 0


def test_configured_pool_size_matches_engine_config():
    # The engine is created with pool_size=20, max_overflow=10 in
    # `app/db/session.py`. If anyone retunes those, the alerting math
    # changes too, so we lock the contract here.
    stats = get_pool_stats()
    if not stats["available"]:
        pytest.skip("engine not initialised in this test runner")
    assert stats["pg_pool_size"] == 20
    assert stats["pg_pool_max_overflow"] == 10
    assert stats["pg_pool_total_capacity"] == 30
