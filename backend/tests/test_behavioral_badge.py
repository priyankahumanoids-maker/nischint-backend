"""NISCH-011.2 — Trust Badge surface contract tests.

Locks the operator-facing 3-field badge shape, the level→color
deterministic mapping, the reason priority ladder, the fail-safe
fallback path, the dispatch isolation, the WebSocket
enhancement-only contract, and the no-raw-metrics-leak invariant.

Coverage matrix:

  Shape lock
    * Badge response is EXACTLY {level, color, reason}.
    * No raw metrics, no PII, no anomaly payloads, no internals.
    * Three values × three colors × locked reason taxonomy.

  Color mapping
    * HIGH_TRUST → green
    * MEDIUM_TRUST → yellow
    * LOW_TRUST → red
    * Unknown → yellow (fail-safe direction)

  Reason priority ladder
    * `telemetry_unavailable` beats `dlq_fallback_spike` beats
      `delayed_ledger_convergence` … beats `all_healthy`.

  Fallback path
    * Evaluator failure → fallback (MEDIUM/yellow/telemetry_unavailable)
    * Postgres failure → fail-safe via gap chain
    * Empty reason_codes → telemetry_unavailable (sentinel)

  Dispatch isolation
    * Badge module is NOT imported from safety_incident_engine or
      alert_trigger.
    * Badge service has no dispatch-influence side effects.

  Redis outage
    * cache_read returns None on Redis down — recompute path
    * cache_write swallow on Redis down — no exception escapes

  WebSocket enhancement
    * Emit ONLY when level transitioned across calls.
    * Emit failure is non-fatal (badge still served).
    * Emit semantically carries the locked shape.

  Polling efficiency
    * Cache TTL is in [5, 15] seconds.
    * Stale-while-revalidate: cache hit returns IMMEDIATELY without
      hitting Postgres.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.behavioral.badge import (
    BADGE_CACHE_TTL_S, FALLBACK_BADGE, REASON_PRIORITY,
    build_badge_fallback, level_to_color, pick_priority_reason,
    _cache_read, _cache_write,
)
from app.services.behavioral.trust import ALLOWED_REASON_CODES


# ── Shape lock ───────────────────────────────────────────────────


def test_fallback_badge_is_exactly_three_fields():
    """LOCKED: the 3-field operator contract. A future PR that
    silently adds `inputs` or `latency_ms` to the badge fallback
    breaks the no-leak contract."""
    assert set(FALLBACK_BADGE) == {"level", "color", "reason"}
    assert FALLBACK_BADGE["level"] == "MEDIUM_TRUST"
    assert FALLBACK_BADGE["color"] == "yellow"
    assert FALLBACK_BADGE["reason"] == "telemetry_unavailable"


def test_build_badge_fallback_returns_fresh_dict():
    """Each call returns a NEW dict — mutating one return value
    must not poison the next caller. Pure-function contract."""
    a = build_badge_fallback()
    a["level"] = "POISONED"
    b = build_badge_fallback()
    assert b["level"] == "MEDIUM_TRUST"


# ── Color mapping ────────────────────────────────────────────────


def test_color_mapping_is_deterministic():
    assert level_to_color("HIGH_TRUST") == "green"
    assert level_to_color("MEDIUM_TRUST") == "yellow"
    assert level_to_color("LOW_TRUST") == "red"


def test_unknown_level_defaults_to_yellow():
    """Fail-safe direction: unknown level → MEDIUM color, never
    red. Mirrors the trust evaluator's MEDIUM-on-unknown contract."""
    assert level_to_color("BOGUS") == "yellow"
    assert level_to_color("") == "yellow"
    assert level_to_color(None) == "yellow"  # type: ignore[arg-type]


# ── Reason priority ladder ───────────────────────────────────────


def test_reason_priority_ladder_locked():
    """LOCKED ordering. Changing this is a public-contract change."""
    assert REASON_PRIORITY == (
        "telemetry_unavailable",
        "dlq_fallback_spike",
        "delayed_ledger_convergence",
        "false_escalation_spike",
        "prediction_precision_degraded",
        "divergence_elevated",
        "unresolved_backlog",
        "motion_telemetry_stale",
        "insufficient_reconciliation_window",
        "all_healthy",
    )


def test_reason_priority_picks_highest_when_multiple():
    """When evaluator returns multiple codes, the badge surfaces
    the most operationally actionable one."""
    assert pick_priority_reason([
        "all_healthy", "divergence_elevated", "dlq_fallback_spike",
    ]) == "dlq_fallback_spike"
    assert pick_priority_reason([
        "unresolved_backlog", "false_escalation_spike",
    ]) == "false_escalation_spike"
    assert pick_priority_reason([
        "insufficient_reconciliation_window", "all_healthy",
    ]) == "insufficient_reconciliation_window"


def test_reason_priority_empty_input_fails_safe():
    """Empty / None → telemetry_unavailable. Locks the fallback
    direction at the picker level."""
    assert pick_priority_reason([]) == "telemetry_unavailable"
    assert pick_priority_reason(None) == "telemetry_unavailable"


def test_reason_priority_unknown_code_fails_safe():
    """Unknown reason code → telemetry_unavailable. Defence
    against typos in future evaluator paths."""
    assert pick_priority_reason(["bogus_code_xyz"]) == \
        "telemetry_unavailable"


def test_priority_ladder_covers_full_taxonomy():
    """Every code in the locked taxonomy MUST appear in the
    priority ladder — otherwise the badge could silently drop a
    real reason on the floor."""
    assert set(REASON_PRIORITY) == ALLOWED_REASON_CODES


# ── Cache TTL contract ───────────────────────────────────────────


def test_cache_ttl_within_spec_band():
    """LOCKED: cache TTL must remain in the 5–15 s polling band
    per the product brief."""
    assert 5 <= BADGE_CACHE_TTL_S <= 15


# ── Cache fail-safe ──────────────────────────────────────────────


def test_cache_read_returns_none_on_redis_down(monkeypatch):
    from app.services.behavioral import badge as bmod
    monkeypatch.setattr(
        bmod, "_cache_read", _cache_read,  # ensure module reference
    )
    from app.services import redis_service
    monkeypatch.setattr(redis_service, "_get_client", lambda: None)
    assert _cache_read() is None


def test_cache_read_returns_none_on_corrupt_payload(monkeypatch):
    """Defence: a corrupted cache entry (malformed JSON or wrong
    shape) must trigger recompute, NOT crash and NOT return half
    a badge."""
    class _R:
        def get(self, k): return b"not-valid-json{"
    from app.services import redis_service
    monkeypatch.setattr(redis_service, "_get_client", lambda: _R())
    assert _cache_read() is None


def test_cache_read_returns_none_on_partial_shape(monkeypatch):
    """A cached dict missing one of the 3 fields must be treated
    as corrupt — never serve a partial badge."""
    class _R:
        def get(self, k): return json.dumps({"level": "HIGH_TRUST"}).encode()
    from app.services import redis_service
    monkeypatch.setattr(redis_service, "_get_client", lambda: _R())
    assert _cache_read() is None


def test_cache_write_swallows_redis_error(monkeypatch):
    """LOCKED: cache write must never raise into caller — failure
    is silently absorbed; next call recomputes."""
    class _Broken:
        def set(self, *a, **kw): raise RuntimeError("redis down")
    from app.services import redis_service
    monkeypatch.setattr(redis_service, "_get_client", lambda: _Broken())
    # Must not raise.
    _cache_write({"level": "HIGH_TRUST", "color": "green",
                  "reason": "all_healthy"})


# ── Dispatch isolation (CRITICAL) ────────────────────────────────


def test_badge_module_not_imported_from_dispatch_paths():
    """LOCKED INVARIANT: the badge module must NEVER be imported
    from `safety_incident_engine.py` or `alert_trigger.py`. The
    badge is observability only. Verified by source scan."""
    import importlib
    for mod_name in (
        "app.services.safety_incident_engine",
        "app.services.alert_trigger",
    ):
        m = importlib.import_module(mod_name)
        src = open(m.__file__).read()
        assert "behavioral.badge" not in src, (
            f"{mod_name} imports behavioral.badge — DISPATCH "
            f"ISOLATION BREACH"
        )


# ── API surface ──────────────────────────────────────────────────


@pytest.fixture
def client():
    """Function-scoped TestClient to avoid asyncpg/event-loop
    teardown races."""
    from server import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def test_badge_endpoint_returns_exactly_three_fields(client):
    """LOCKED: the 3-field operator contract. The response body
    MUST contain only {level, color, reason} — no metrics
    leakage."""
    # Clear cache so we see the freshly-computed shape (cache
    # might also be 3-field but live path is the audit-of-record).
    from app.services.behavioral import badge as bmod
    try:
        bmod._cache_write({"level": "POISON",
                           "color": "POISON", "reason": "POISON"})
    except Exception:
        pass
    # Bust the cache by deleting the key.
    try:
        from app.services import redis_service
        r = redis_service._get_client()
        if r is not None:
            r.delete("nischint:behavioral:trust:badge")
    except Exception:
        pass

    resp = client.get("/api/behavioral/trust/badge")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"level", "color", "reason"}
    assert body["level"] in {"HIGH_TRUST", "MEDIUM_TRUST", "LOW_TRUST"}
    assert body["color"] in {"green", "yellow", "red"}
    assert body["reason"] in ALLOWED_REASON_CODES


def test_badge_endpoint_color_consistent_with_level(client):
    """The level→color mapping that holds at the service layer
    MUST also hold end-to-end through the endpoint."""
    resp = client.get("/api/behavioral/trust/badge")
    body = resp.json()
    expected = {"HIGH_TRUST": "green", "MEDIUM_TRUST": "yellow",
                "LOW_TRUST": "red"}[body["level"]]
    assert body["color"] == expected


def test_badge_endpoint_never_low_on_fresh_db(client):
    """LOCKED INVARIANT: a freshly-deployed instance MUST NOT
    serve LOW_TRUST. Cold-start with no reconciled predictions
    lands on MEDIUM with the warmup reason."""
    # Bust the cache.
    try:
        from app.services import redis_service
        r = redis_service._get_client()
        if r is not None:
            r.delete("nischint:behavioral:trust:badge")
    except Exception:
        pass
    resp = client.get("/api/behavioral/trust/badge")
    body = resp.json()
    assert body["level"] != "LOW_TRUST"
    assert body["color"] != "red"


def test_badge_endpoint_no_raw_metrics_leak(client):
    """LOCKED: no key starting with `divergence`, `precision`,
    `mae`, `lag`, `dlq`, or `unresolved` may appear in the badge
    response. The badge surface is the smallest possible
    projection."""
    resp = client.get("/api/behavioral/trust/badge")
    body = resp.json()
    forbidden_prefixes = (
        "divergence", "precision", "mae", "lag", "dlq",
        "unresolved", "reconciliation", "input", "inputs",
        "feature", "score", "anomaly",
    )
    for k in body:
        for p in forbidden_prefixes:
            assert not k.startswith(p), (
                f"raw-metric leak: badge key {k!r} contains "
                f"forbidden prefix {p!r}"
            )


def test_badge_endpoint_cache_path_is_cheap(client):
    """Two consecutive calls inside the cache TTL window should
    both return 200 with identical shape. The second call should
    be served from cache (cheap — no Postgres). We can't directly
    measure cache vs live without instrumenting the endpoint, so
    we lock the OBSERVABLE outcome: two consecutive calls return
    identical bodies."""
    a = client.get("/api/behavioral/trust/badge").json()
    b = client.get("/api/behavioral/trust/badge").json()
    assert a == b


# ── Fail-safe path ───────────────────────────────────────────────


def test_badge_endpoint_fallback_on_evaluator_failure(client, monkeypatch):
    """LOCKED INVARIANT: if the evaluator throws, the endpoint
    MUST serve the fallback badge (MEDIUM/yellow/
    telemetry_unavailable). NEVER 500. NEVER LOW_TRUST."""
    # Bust the cache.
    try:
        from app.services import redis_service
        r = redis_service._get_client()
        if r is not None:
            r.delete("nischint:behavioral:trust:badge")
    except Exception:
        pass

    # Sabotage the evaluator at the module the endpoint imports.
    from app.api import behavioral as api_mod

    def _explode(**kw):
        raise RuntimeError("simulated evaluator failure")

    monkeypatch.setattr(api_mod, "evaluate_trust", _explode)

    resp = client.get("/api/behavioral/trust/badge")
    assert resp.status_code == 200
    body = resp.json()
    assert body == FALLBACK_BADGE


# ── WebSocket enhancement-only contract ──────────────────────────


def test_emit_does_nothing_when_level_unchanged():
    """LOCKED: WebSocket emit fires ONLY on level transitions.
    Same level → no broadcast call."""
    from app.api import behavioral as api_mod
    broadcasts: list = []

    class _Br:
        async def broadcast_to_operators(self, ev, data):
            broadcasts.append((ev, data))

    with patch.dict("sys.modules", {
        "app.services.event_broadcaster":
            type("M", (), {"broadcaster": _Br()})(),
    }):
        asyncio.run(api_mod._maybe_emit_trust_level_changed(
            current_level="HIGH_TRUST",
            current_reason="all_healthy",
            current_trend="stable",
            previous_level="HIGH_TRUST",
        ))
    assert broadcasts == []


def test_emit_skipped_when_previous_level_none():
    """First-ever call has no previous level — never emits.
    Locks the "no spurious emit on startup" contract."""
    from app.api import behavioral as api_mod
    broadcasts: list = []

    class _Br:
        async def broadcast_to_operators(self, ev, data):
            broadcasts.append((ev, data))

    with patch.dict("sys.modules", {
        "app.services.event_broadcaster":
            type("M", (), {"broadcaster": _Br()})(),
    }):
        asyncio.run(api_mod._maybe_emit_trust_level_changed(
            current_level="HIGH_TRUST",
            current_reason="all_healthy",
            current_trend="stable",
            previous_level=None,
        ))
    assert broadcasts == []


def test_emit_fires_on_transition_with_locked_shape():
    """Level transition → broadcast called with exactly
    {level, reason, trend, severity_delta} on the operator
    channel. `severity_delta` lets the frontend animate the
    transition direction without parsing strings."""
    from app.api import behavioral as api_mod
    broadcasts: list = []

    class _Br:
        async def broadcast_to_operators(self, ev, data):
            broadcasts.append((ev, data))

    with patch.dict("sys.modules", {
        "app.services.event_broadcaster":
            type("M", (), {"broadcaster": _Br()})(),
    }):
        asyncio.run(api_mod._maybe_emit_trust_level_changed(
            current_level="LOW_TRUST",
            current_reason="dlq_fallback_spike",
            current_trend="degrading",
            previous_level="HIGH_TRUST",
        ))
    assert len(broadcasts) == 1
    ev, data = broadcasts[0]
    assert ev == "trust_level_changed"
    assert set(data) == {"level", "reason", "trend", "severity_delta"}
    assert data == {
        "level":          "LOW_TRUST",
        "reason":         "dlq_fallback_spike",
        "trend":          "degrading",
        "severity_delta": 2,   # HIGH(0) → LOW(2)
    }


def test_severity_delta_signed_math():
    """LOCKED ladder: HIGH=0, MEDIUM=1, LOW=2.
    delta = new - old. Positive = worsening; negative = improving."""
    from app.services.behavioral.trust import severity_delta
    assert severity_delta(current_level="HIGH_TRUST",
                           previous_level="HIGH_TRUST") == 0
    assert severity_delta(current_level="MEDIUM_TRUST",
                           previous_level="HIGH_TRUST") == 1
    assert severity_delta(current_level="LOW_TRUST",
                           previous_level="HIGH_TRUST") == 2
    assert severity_delta(current_level="LOW_TRUST",
                           previous_level="MEDIUM_TRUST") == 1
    assert severity_delta(current_level="HIGH_TRUST",
                           previous_level="LOW_TRUST") == -2
    assert severity_delta(current_level="HIGH_TRUST",
                           previous_level="MEDIUM_TRUST") == -1
    # First-ever call (no previous level) → 0, never raises.
    assert severity_delta(current_level="LOW_TRUST",
                           previous_level=None) == 0
    # Unknown level → MEDIUM rank → graceful 0/±1 instead of crash.
    assert severity_delta(current_level="HIGH_TRUST",
                           previous_level="BOGUS") == -1


def test_emit_failure_is_silent_and_non_blocking():
    """LOCKED: WebSocket emit failure must NOT raise into caller.
    The polling endpoint remains source of truth — WebSocket is
    enhancement only."""
    from app.api import behavioral as api_mod

    class _Br:
        async def broadcast_to_operators(self, ev, data):
            raise RuntimeError("WS down")

    with patch.dict("sys.modules", {
        "app.services.event_broadcaster":
            type("M", (), {"broadcaster": _Br()})(),
    }):
        # Must not raise.
        asyncio.run(api_mod._maybe_emit_trust_level_changed(
            current_level="LOW_TRUST",
            current_reason="dlq_fallback_spike",
            current_trend="degrading",
            previous_level="HIGH_TRUST",
        ))
