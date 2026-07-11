"""Tests for the public status endpoint.

These tests are pure-unit — they exercise the data sanitization helpers
without touching Redis or PostgreSQL, so they run in CI without any
fixture setup.
"""

import importlib

import pytest


@pytest.fixture
def public_status():
    return importlib.import_module("app.api.public_status")


# ── _api_status ──────────────────────────────────────────────────────


def test_api_status_always_operational(public_status):
    """If this function runs at all, the API is up — never publish anything else."""
    out = public_status._api_status()
    assert out["name"] == "API"
    assert out["status"] == "operational"
    assert "responding" in out["description"].lower()


# ── _db_status_from ──────────────────────────────────────────────────


def test_db_status_outage_when_active_incident(public_status):
    out = public_status._db_status_from({
        "pool": {"available": True, "size": 10, "checked_out": 2},
        "active_incidents": [{"id": "abc", "severity_peak": "degraded"}],
    })
    assert out["status"] == "outage"


def test_db_status_degraded_when_pool_pressure(public_status):
    out = public_status._db_status_from({
        "pool": {"available": True, "size": 10, "checked_out": 9},
        "active_incidents": [],
    })
    assert out["status"] == "degraded"


def test_db_status_degraded_when_pool_unavailable(public_status):
    out = public_status._db_status_from({
        "pool": {"available": False, "error": "redis down"},
        "active_incidents": [],
    })
    assert out["status"] == "degraded"
    # Public output must NEVER leak internal error strings.
    assert "redis" not in out["description"].lower()


def test_db_status_operational_when_healthy(public_status):
    out = public_status._db_status_from({
        "pool": {"available": True, "size": 10, "checked_out": 3},
        "active_incidents": [],
    })
    assert out["status"] == "operational"


def test_db_status_handles_empty_input(public_status):
    """Missing pool block must not crash — public endpoint never errors."""
    out = public_status._db_status_from({})
    assert out["status"] in ("operational", "degraded")


# ── _sachet_status_from ──────────────────────────────────────────────


@pytest.mark.parametrize("state,expected", [
    ("healthy",  "operational"),
    ("HEALTHY",  "operational"),
    ("degraded", "degraded"),
    ("outage",   "outage"),
    ("",         "operational"),  # unknown / not-yet-reported
])
def test_sachet_status_state_mapping(public_status, state, expected):
    out = public_status._sachet_status_from({"state": state})
    assert out["status"] == expected


def test_sachet_status_error_becomes_degraded(public_status):
    out = public_status._sachet_status_from({"error": "connection timeout: 10.0.5.7"})
    assert out["status"] == "degraded"
    # No leakage of internal IPs / stack traces.
    assert "10.0.5.7" not in out["description"]
    assert "timeout" not in out["description"].lower()


# ── _compute_uptime_pct ──────────────────────────────────────────────


def test_uptime_pct_zero_downtime(public_status):
    assert public_status._compute_uptime_pct(0) == 100.00


def test_uptime_pct_one_hour_downtime(public_status):
    # 1 hour out of 30 days
    pct = public_status._compute_uptime_pct(60 * 60 * 1000)
    assert 99.85 <= pct <= 99.90


def test_uptime_pct_caps_at_100(public_status):
    """Negative or weird downtime values still produce a sane bound."""
    pct = public_status._compute_uptime_pct(-99999)
    assert pct == 100.00


def test_uptime_pct_floors_at_zero(public_status):
    """Downtime greater than window → 0, never negative."""
    huge = public_status.UPTIME_WINDOW_MS * 2
    pct = public_status._compute_uptime_pct(huge)
    assert pct == 0.00


# ── _overall_status ──────────────────────────────────────────────────


def test_overall_worst_of_outage(public_status):
    out = public_status._overall_status([
        {"status": "operational"},
        {"status": "outage"},
        {"status": "degraded"},
    ])
    assert out == "outage"


def test_overall_worst_of_degraded(public_status):
    out = public_status._overall_status([
        {"status": "operational"},
        {"status": "degraded"},
        {"status": "operational"},
    ])
    assert out == "degraded"


def test_overall_all_operational(public_status):
    out = public_status._overall_status([
        {"status": "operational"},
        {"status": "operational"},
    ])
    assert out == "operational"


def test_overall_empty_list_safe(public_status):
    assert public_status._overall_status([]) == "operational"


# ── Public surface — no leaked internal fields ───────────────────────


def test_public_envelope_does_not_leak_internal_keys(public_status, monkeypatch):
    """Smoke-check: the gather() result keys must be filtered, not echoed."""
    # Stub out the heavy admin gather with a fake bundle that contains
    # admin-only fields. The public envelope must not echo any of them.
    async def fake_gather():
        return {
            "db": {
                "pool": {"available": True, "size": 10, "checked_out": 1, "url": "postgres://secret"},
                "active_incidents": [],
            },
            "sachet": {"state": "healthy", "internal_error": "ignore me"},
            "dlqs":    {"streams": [{"name": "internal:queue:xyz"}]},
            "consent": {"records": 42},
            "trust":   {"level": "HIGH"},
        }

    import asyncio
    monkeypatch.setattr(
        "app.api.monitoring._gather_dashboard_summary",
        fake_gather,
    )
    # We don't have an event loop fixture in this file; run synchronously
    # via asyncio.run on a wrapper that stubs the DB session.
    async def call_with_no_db():
        async def fake_db_session():
            return
            yield  # pragma: no cover (unreachable generator)
        monkeypatch.setattr(public_status, "get_db_session", lambda: fake_db_session())
        return await public_status._build_status_envelope()

    out = asyncio.run(call_with_no_db())
    # Top-level keys must be exactly the public schema
    assert set(out.keys()) == {
        "overall", "components", "uptime_30d_pct", "uptime_window_days",
        "incidents", "generated_at",
    }
    # Components are all dicts with only public keys
    public_comp_keys = {"name", "status", "description"}
    for c in out["components"]:
        assert set(c.keys()) <= public_comp_keys, f"leaked key in {c}"
    # No "postgres://" anywhere in serialised envelope
    import json
    payload = json.dumps(out)
    assert "postgres://" not in payload
    assert "internal_error" not in payload
    assert "ignore me" not in payload
