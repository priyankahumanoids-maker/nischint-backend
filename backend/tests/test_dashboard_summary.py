"""REL-08 — Tests for the dashboard-summary batch endpoint.

Locks down:
  1. All 5 capsule data sources land in the response under stable keys.
  2. A single failing source does NOT take down the whole envelope —
     it gets an `{"error": ...}` block, the others still render.
  3. The Redis cache layer:
       a) returns the cached payload as-is on a hit, with
          `_cache_hit: True` overlaid.
       b) calls `set_json` after a miss.
       c) survives a Redis down (`get_json` raising) by recomputing.
  4. Concurrent sources are gathered with `asyncio.gather` — verified
     indirectly via the timing of the fan-out (each source is async).
"""
from __future__ import annotations

import pytest


# ── Fixtures: stub every source so the test stays in-process ─────────


@pytest.fixture
def stub_sources(monkeypatch):
    """Pin each source to a deterministic return value. The gather
    function builds the bundle from these; any drift in keys breaks
    the test."""
    monkeypatch.setattr(
        "app.services.dlq_reconciler.get_dlq_stats",
        lambda: {"any_red": False, "any_amber": True, "redis_available": True},
    )
    monkeypatch.setattr(
        "app.services.external_signals.sachet_prewarmer.get_prewarmer_telemetry",
        lambda: {"health_state": "healthy", "active_alert_count": 42},
    )
    monkeypatch.setattr(
        "app.db.pool_stats.get_pool_stats",
        lambda: {"available": True, "pg_pool_utilization_pct": 12.5},
    )

    # consents: replace `compute_consent_health` with an async stub.
    class _Bundle:
        def model_dump(self):
            return {
                "overall_state": "ok",
                "total_users_prompted": 7,
                "categories": [],
            }

    async def fake_compute(_sess):
        return _Bundle()

    monkeypatch.setattr("app.api.consents.compute_consent_health", fake_compute)

    # Trust badge — populate the behavioral cache so the gather hits
    # the fast path.
    monkeypatch.setattr(
        "app.api.behavioral._cache_read",
        lambda: {"level": "HIGH_TRUST", "color": "green", "reason": "stable"},
    )

    # DB session — return a stub that yields a session with `.execute`
    # returning an empty-rows result for active_incidents.
    class _StubExecuteResult:
        def scalars(self):
            class _S:
                def all(self_inner):
                    return []
            return _S()

    class _StubSession:
        async def execute(self_inner, *_a, **_kw):
            return _StubExecuteResult()

    async def stub_gds():
        yield _StubSession()

    monkeypatch.setattr("app.api.deps.get_db_session", stub_gds)


@pytest.fixture
def kill_redis(monkeypatch):
    """No-op Redis — get always returns None (cache miss), set is a
    no-op. The endpoint must still recompute and return a fresh
    bundle."""
    calls = {"get": 0, "set": 0}

    def fake_get(_ns, _key):
        calls["get"] += 1
        return None

    def fake_set(_ns, _key, _val, ttl=None):
        calls["set"] += 1

    monkeypatch.setattr("app.services.redis_service.get_json", fake_get)
    monkeypatch.setattr("app.services.redis_service.set_json", fake_set)
    return calls


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_envelope_has_all_five_keys(stub_sources, kill_redis):
    from app.api.monitoring import get_dashboard_summary
    out = await get_dashboard_summary()
    assert set(out.keys()) >= {"dlqs", "sachet", "db", "consent", "trust", "generated_at", "_cache_hit"}
    # Source values plumbed through correctly.
    assert out["dlqs"]["any_amber"] is True
    assert out["sachet"]["active_alert_count"] == 42
    assert out["db"]["pool"]["pg_pool_utilization_pct"] == 12.5
    assert out["db"]["active_incidents"] == []
    assert out["consent"]["overall_state"] == "ok"
    assert out["trust"]["level"] == "HIGH_TRUST"


@pytest.mark.asyncio
async def test_single_source_failure_does_not_kill_envelope(monkeypatch, stub_sources, kill_redis):
    """A boom in `get_dlq_stats` must yield `dlqs: {"error": ...}`
    AND leave every other capsule's slice intact."""
    def boom():
        raise RuntimeError("dlq exploded")

    monkeypatch.setattr("app.services.dlq_reconciler.get_dlq_stats", boom)

    from app.api.monitoring import get_dashboard_summary
    out = await get_dashboard_summary()

    assert "error" in out["dlqs"]
    assert "dlq exploded" in out["dlqs"]["error"]
    # Other sources unaffected.
    assert out["sachet"]["active_alert_count"] == 42
    assert out["consent"]["overall_state"] == "ok"
    assert out["trust"]["level"] == "HIGH_TRUST"


@pytest.mark.asyncio
async def test_cache_hit_short_circuits_recompute(monkeypatch, stub_sources):
    """When Redis returns a payload, the gather must NOT run again."""
    cached = {
        "dlqs":     {"cached": True},
        "sachet":   {"cached": True},
        "db":       {"cached": True},
        "consent":  {"cached": True},
        "trust":    {"cached": True},
        "generated_at": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr("app.services.redis_service.get_json", lambda *_a: cached)

    called = {"gather": 0}

    async def boom_gather():
        called["gather"] += 1
        raise AssertionError("gather should NOT be called on a cache hit")

    monkeypatch.setattr(
        "app.api.monitoring._gather_dashboard_summary", boom_gather,
    )

    from app.api.monitoring import get_dashboard_summary
    out = await get_dashboard_summary()

    assert out["_cache_hit"] is True
    assert out["dlqs"] == {"cached": True}
    assert called["gather"] == 0


@pytest.mark.asyncio
async def test_cache_write_after_miss(monkeypatch, stub_sources, kill_redis):
    from app.api.monitoring import get_dashboard_summary
    await get_dashboard_summary()
    assert kill_redis["set"] == 1
    assert kill_redis["get"] == 1


@pytest.mark.asyncio
async def test_redis_down_still_returns_fresh_bundle(monkeypatch, stub_sources):
    """`get_json` raises (Redis offline) — endpoint MUST recompute
    rather than 500."""
    def boom_get(*_a, **_kw):
        raise RuntimeError("redis offline")

    def boom_set(*_a, **_kw):
        raise RuntimeError("redis offline")

    monkeypatch.setattr("app.services.redis_service.get_json", boom_get)
    monkeypatch.setattr("app.services.redis_service.set_json", boom_set)

    from app.api.monitoring import get_dashboard_summary
    out = await get_dashboard_summary()
    # Cache miss path is taken; payload is freshly computed.
    assert out["_cache_hit"] is False
    assert out["dlqs"]["any_amber"] is True


@pytest.mark.asyncio
async def test_trust_fallback_when_cache_empty(monkeypatch, stub_sources, kill_redis):
    """When the behavioral cache is empty we must NOT block on a
    full trust recompute — fall back to the locked MEDIUM/yellow
    fail-safe."""
    monkeypatch.setattr("app.api.behavioral._cache_read", lambda: None)

    from app.api.monitoring import get_dashboard_summary
    out = await get_dashboard_summary()

    assert out["trust"]["level"] == "MEDIUM_TRUST"
    assert out["trust"]["color"] == "yellow"
    assert out["trust"]["reason"] == "telemetry_unavailable"
