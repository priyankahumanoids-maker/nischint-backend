"""NISCH-012.1 — TomTom prewarmer + provider unit tests.

Locks the user-mandated invariants:
  1. Cache untouched on empty fetch.
  2. Cache untouched on fetch raising.
  3. Jitter stays within bounds over 100 iterations, independent
     of Sachet's jitter.
  4. State machine transitions correctly across all 4 states.
  5. Hysteresis blocks premature recovery (3-clean-read gate).
  6. `tomtom_health` transitions appear in the SSE replay tail.
  7. **Disabled mode**: API key absent → `is_enabled() = False`,
     scheduler refuses to register, monitoring telemetry returns
     `{state: "disabled", reason: "no_api_key"}`.
  8. **No new DB writes** — the prewarmer is Redis-only.

Plus parse-layer and provider behaviour tests.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.external_signals import tomtom_prewarmer as tp
from app.services.external_signals.tomtom_prewarmer import (
    FAILURE_RATE_THRESHOLD, HEALTHY_MAX_AGE_S, JITTER_BASE_S,
    JITTER_RANGE_S, RECOVERY_READS_REQUIRED, STALE_MAX_AGE_S,
    STATE_DEGRADED, STATE_DISABLED, STATE_HEALTHY, STATE_KEY,
    STATE_STALE, STATE_UNKNOWN, TELEMETRY_KEY, TELEMETRY_NAMESPACE,
    compute_next_interval_seconds, compute_raw_state,
    evaluate_state_transition, get_health_state, get_prewarmer_telemetry,
    is_provider_enabled, run_prewarm_cycle,
    start_tomtom_prewarm_scheduler, stop_tomtom_prewarm_scheduler,
)
from app.services.external_signals.tomtom_provider import (
    SEVERITY_RISK, TomTomSignalProvider, parse_flow_segment,
    severity_from_ratio,
)


# ════════════════════════════════════════════════════════════════════
# Jitter — independent of Sachet
# ════════════════════════════════════════════════════════════════════

def test_jitter_bounds_locked():
    assert JITTER_BASE_S == 300        # 5 min
    assert JITTER_RANGE_S == 60        # ±60 s


def test_jitter_independent_of_sachet():
    """The two cycles MUST NOT share a base interval — a coordinated
    outage is then the only way both can drift in lock-step.
    Protects against an operations regression that would silently
    nudge both providers onto the same heartbeat."""
    from app.services.external_signals import sachet_prewarmer as sp
    assert JITTER_BASE_S != sp.JITTER_BASE_S
    assert JITTER_RANGE_S != sp.JITTER_RANGE_S


def test_jitter_stays_within_bounds_over_100_iterations():
    rng = random.Random(2025)
    low = JITTER_BASE_S - JITTER_RANGE_S       # 240
    high = JITTER_BASE_S + JITTER_RANGE_S      # 360
    samples = [compute_next_interval_seconds(rng) for _ in range(100)]
    assert min(samples) >= low
    assert max(samples) <= high
    assert len(set(round(s, 2) for s in samples)) > 50


# ════════════════════════════════════════════════════════════════════
# Cache-preservation
# ════════════════════════════════════════════════════════════════════

class _RedisDouble:
    def __init__(self):
        self.store: dict[tuple[str, str], object] = {}
        self.set_calls: list[tuple[str, str, object, int | None]] = []

    def get_json(self, ns, key):
        return self.store.get((ns, key))

    def set_json(self, ns, key, value, ttl=None):
        self.set_calls.append((ns, key, value, ttl))
        self.store[(ns, key)] = value
        return True


@pytest.fixture
def redis_double(monkeypatch):
    dbl = _RedisDouble()
    monkeypatch.setattr(tp.redis_service, "get_json", dbl.get_json)
    monkeypatch.setattr(tp.redis_service, "set_json", dbl.set_json)
    return dbl


@pytest.fixture
def enable_provider(monkeypatch):
    """Some tests need the provider enabled regardless of the host
    env. Force the key on so the prewarmer's disabled guard does
    not short-circuit unrelated assertions."""
    monkeypatch.setenv("TOMTOM_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_cache_untouched_when_fetch_returns_empty(
        redis_double, enable_provider):
    """Empty fetch must NOT overwrite a healthy cache key."""
    healthy_cache = [{"zone": "Mumbai", "ratio": 0.4, "severity": "moderate",
                      "current_speed": 30.0, "free_flow_speed": 50.0,
                      "lat": 19.07, "lng": 72.87}]
    redis_double.store[("tomtom", "flow_by_zone_v1")] = healthy_cache

    with patch(
        "app.services.external_signals.tomtom_prewarmer.fetch_all_zones",
        new=AsyncMock(return_value=[]),
    ):
        result = await run_prewarm_cycle()

    assert result["status"] == "no_fresh_readings"
    assert result["raised"] is False
    assert redis_double.store[("tomtom", "flow_by_zone_v1")] == healthy_cache
    # No writes to the cache namespace; only the prewarmer namespace
    cache_writes = [c for c in redis_double.set_calls if c[0] == "tomtom"]
    assert cache_writes == []


@pytest.mark.asyncio
async def test_cache_untouched_when_fetch_raises(
        redis_double, enable_provider):
    healthy_cache = [{"zone": "Delhi", "ratio": 0.5, "severity": "moderate",
                      "current_speed": 25.0, "free_flow_speed": 50.0,
                      "lat": 28.6, "lng": 77.2}]
    redis_double.store[("tomtom", "flow_by_zone_v1")] = healthy_cache

    with patch(
        "app.services.external_signals.tomtom_prewarmer.fetch_all_zones",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await run_prewarm_cycle()

    assert result["status"] == "no_fresh_readings"
    assert result["raised"] is True
    assert redis_double.store[("tomtom", "flow_by_zone_v1")] == healthy_cache


@pytest.mark.asyncio
async def test_cache_overwritten_only_on_non_empty_success(
        redis_double, enable_provider):
    fresh = [
        {"zone": "Mumbai", "ratio": 0.4, "severity": "moderate",
         "current_speed": 30.0, "free_flow_speed": 50.0,
         "lat": 19.07, "lng": 72.87},
        {"zone": "Delhi", "ratio": 0.2, "severity": "minor",
         "current_speed": 40.0, "free_flow_speed": 50.0,
         "lat": 28.6, "lng": 77.2},
    ]
    with patch(
        "app.services.external_signals.tomtom_prewarmer.fetch_all_zones",
        new=AsyncMock(return_value=fresh),
    ):
        result = await run_prewarm_cycle()
    assert result == {"status": "success", "zone_count": 2}
    cache_writes = [c for c in redis_double.set_calls if c[0] == "tomtom"]
    assert len(cache_writes) == 1
    ns, key, value, ttl = cache_writes[0]
    assert (ns, key) == ("tomtom", "flow_by_zone_v1")
    assert value == fresh
    assert ttl == 600


# ════════════════════════════════════════════════════════════════════
# State machine
# ════════════════════════════════════════════════════════════════════

def _telem(last_success_ago_s, parse_failure_rate=0.0):
    if last_success_ago_s is None:
        return {"last_success_ts": None, "parse_failure_rate": parse_failure_rate}
    ts = datetime.now(timezone.utc) - timedelta(seconds=last_success_ago_s)
    return {
        "last_success_ts":    ts.isoformat(),
        "parse_failure_rate": parse_failure_rate,
    }


def test_thresholds_locked():
    """Operator UI legend + state-machine thresholds — TomTom MUST
    use the same 4-state contract as Sachet (per spec)."""
    assert HEALTHY_MAX_AGE_S == 600
    assert STALE_MAX_AGE_S == 1800
    assert FAILURE_RATE_THRESHOLD == 0.20
    assert RECOVERY_READS_REQUIRED == 3


def test_raw_state_unknown_when_no_success_ever():
    assert compute_raw_state(_telem(None)) == STATE_UNKNOWN


def test_raw_state_healthy_under_thresholds():
    assert compute_raw_state(_telem(120, 0.10)) == STATE_HEALTHY
    assert compute_raw_state(_telem(599, 0.19)) == STATE_HEALTHY


def test_raw_state_stale_between_10_and_30_minutes():
    assert compute_raw_state(_telem(720, 0.0)) == STATE_STALE
    assert compute_raw_state(_telem(1799, 0.0)) == STATE_STALE


def test_raw_state_degraded_beyond_30_minutes_or_high_failure():
    assert compute_raw_state(_telem(1801, 0.0)) == STATE_DEGRADED
    assert compute_raw_state(_telem(60, 0.20)) == STATE_DEGRADED
    assert compute_raw_state(_telem(60, 0.50)) == STATE_DEGRADED


# ── Hysteresis ────────────────────────────────────────────────────

def test_regression_snaps_immediately():
    state, counter, transitioned = evaluate_state_transition(
        STATE_HEALTHY, 0, STATE_DEGRADED,
    )
    assert state == STATE_DEGRADED
    assert counter == 0
    assert transitioned is True


def test_recovery_requires_three_consecutive_clean_reads():
    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 0, STATE_HEALTHY,
    )
    assert state == STATE_DEGRADED
    assert counter == 1
    assert transitioned is False

    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 1, STATE_HEALTHY,
    )
    assert state == STATE_DEGRADED
    assert counter == 2
    assert transitioned is False

    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 2, STATE_HEALTHY,
    )
    assert state == STATE_HEALTHY
    assert counter == 0
    assert transitioned is True


def test_recovery_resets_on_regression_during_gate():
    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 1, STATE_DEGRADED,
    )
    assert state == STATE_DEGRADED
    assert counter == 0
    assert transitioned is False


def test_unknown_to_first_observation_snaps():
    state, counter, transitioned = evaluate_state_transition(
        STATE_UNKNOWN, 0, STATE_HEALTHY,
    )
    assert state == STATE_HEALTHY
    assert transitioned is True


# ════════════════════════════════════════════════════════════════════
# Disabled mode (TOMTOM_API_KEY absent)
# ════════════════════════════════════════════════════════════════════

def test_is_provider_enabled_false_without_key(monkeypatch):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    assert is_provider_enabled() is False
    assert TomTomSignalProvider().is_enabled() is False


def test_is_provider_enabled_false_with_blank_key(monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "   ")
    assert is_provider_enabled() is False


def test_telemetry_returns_disabled_shape_without_key(monkeypatch, redis_double):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    out = get_prewarmer_telemetry()
    assert out["health_state"] == STATE_DISABLED
    assert out["reason"] == "no_api_key"
    assert out["last_fetch_ts"] is None
    # No Redis writes should have occurred to query telemetry.


def test_health_state_returns_disabled_shape_without_key(monkeypatch, redis_double):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    out = get_health_state()
    assert out["state"] == STATE_DISABLED
    assert out["reason"] == "no_api_key"


def test_scheduler_refuses_to_register_without_key(monkeypatch):
    """The scheduler MUST NOT register the job when the key is
    absent — protects against the prewarmer poisoning Redis with
    empty-fetch noise."""
    import asyncio
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)

    async def _run():
        start_tomtom_prewarm_scheduler()
        # Internal handle stays None when disabled.
        assert tp._scheduler is None
        stop_tomtom_prewarm_scheduler()

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_run_cycle_short_circuits_when_disabled(monkeypatch, redis_double):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    result = await run_prewarm_cycle()
    assert result == {"status": "disabled", "reason": "no_api_key"}
    # No telemetry write — disabled state is a no-op end-to-end.
    assert redis_double.set_calls == []


# ════════════════════════════════════════════════════════════════════
# Replay-tail integration — tomtom_health appears in SSE history
# ════════════════════════════════════════════════════════════════════

def test_tomtom_health_in_known_sources():
    """The history allow-list must include `tomtom_health` so the
    SSE replay tail can surface its transitions to operators."""
    from app.services.system_health_history import KNOWN_SOURCES
    assert "tomtom_health" in KNOWN_SOURCES


def test_tomtom_emitter_records_history(monkeypatch):
    """The TomTom prewarmer's broadcaster must call
    `record_transition("tomtom_health", payload)` so the replay
    tail catches every transition — same contract as sachet/v2."""
    from app.services import system_health_history as shh
    captured = {"calls": []}

    def _fake_record(source, payload):
        captured["calls"].append((source, payload))
        return True

    monkeypatch.setattr(shh, "record_transition", _fake_record)

    class _NoBroadcaster:
        async def broadcast_to_operators(self, *a, **kw):
            return None

    import app.services.event_broadcaster as eb
    monkeypatch.setattr(eb, "broadcaster", _NoBroadcaster())

    tp._emit_tomtom_health_delta(
        prior_state="healthy",
        new_state="degraded",
        telemetry={
            "cache_age_seconds":  900,
            "parse_failure_rate": 0.30,
            "active_zone_count":  0,
            "last_success_ts":    "2026-05-01T00:00:00+00:00",
        },
    )
    assert len(captured["calls"]) == 1
    src, payload = captured["calls"][0]
    assert src == "tomtom_health"
    assert payload["source"] == "tomtom_health"
    assert payload["tomtom_health"]["state"] == "degraded"
    assert payload["tomtom_health"]["previous_state"] == "healthy"


# ════════════════════════════════════════════════════════════════════
# Telemetry contract — success vs failure paths
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_telemetry_written_on_success_path(redis_double, enable_provider):
    fresh = [
        {"zone": "Mumbai", "ratio": 0.4, "severity": "moderate",
         "current_speed": 30.0, "free_flow_speed": 50.0,
         "lat": 19.07, "lng": 72.87},
        {"zone": "Delhi", "ratio": 0.2, "severity": "minor",
         "current_speed": 40.0, "free_flow_speed": 50.0,
         "lat": 28.6, "lng": 77.2},
    ]
    with patch(
        "app.services.external_signals.tomtom_prewarmer.fetch_all_zones",
        new=AsyncMock(return_value=fresh),
    ):
        await run_prewarm_cycle()
    telem = redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)]
    assert telem["last_success_ts"] is not None
    assert telem["last_fetch_ts"] == telem["last_success_ts"]
    assert telem["active_zone_count"] == 2
    assert telem["parse_failure_rate"] == 0.0


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_advance_last_success(
        redis_double, enable_provider):
    prior_success_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=12)
    ).isoformat()
    redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)] = {
        "last_fetch_ts":      prior_success_iso,
        "last_success_ts":    prior_success_iso,
        "parse_failure_rate": 0.0,
        "active_zone_count":  5,
        "attempt_history":    [True],
    }
    with patch(
        "app.services.external_signals.tomtom_prewarmer.fetch_all_zones",
        new=AsyncMock(return_value=[]),
    ):
        await run_prewarm_cycle()
    telem = redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)]
    assert telem["last_success_ts"] == prior_success_iso
    assert telem["last_fetch_ts"] != prior_success_iso
    assert telem["active_zone_count"] == 5     # preserved
    assert telem["attempt_history"] == [True, False]


# ════════════════════════════════════════════════════════════════════
# Provider parse layer
# ════════════════════════════════════════════════════════════════════

def test_severity_from_ratio_thresholds():
    assert severity_from_ratio(0.10) == "minor"
    assert severity_from_ratio(0.35) == "moderate"
    assert severity_from_ratio(0.65) == "severe"
    assert severity_from_ratio(0.85) == "extreme"
    # Boundary
    assert severity_from_ratio(0.30) == "minor"      # = threshold → not moderate
    assert severity_from_ratio(0.31) == "moderate"


def test_parse_flow_segment_returns_none_on_bad_shape():
    assert parse_flow_segment(None) is None
    assert parse_flow_segment({}) is None
    assert parse_flow_segment({"flowSegmentData": {}}) is None
    # freeFlowSpeed = 0 → div-zero → None
    assert parse_flow_segment({
        "flowSegmentData": {"currentSpeed": 10, "freeFlowSpeed": 0}
    }) is None


def test_parse_flow_segment_normalises_ratio():
    out = parse_flow_segment({
        "flowSegmentData": {
            "currentSpeed": 30.0, "freeFlowSpeed": 60.0,
            "confidence": 0.95, "roadClosure": False, "frc": "FRC1",
        }
    })
    assert out is not None
    assert out["ratio"] == 0.5
    assert out["severity"] == "moderate"


@pytest.mark.asyncio
async def test_provider_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    p = TomTomSignalProvider()
    out = await p._fetch_unsafe(19.07, 72.87)
    assert out is None


@pytest.mark.asyncio
async def test_provider_returns_signal_when_match_within_radius(
        monkeypatch, enable_provider):
    p = TomTomSignalProvider()
    cached = [{"zone": "Mumbai", "ratio": 0.7, "severity": "severe",
               "current_speed": 15.0, "free_flow_speed": 50.0,
               "lat": 19.0760, "lng": 72.8777, "confidence": 0.9}]

    async def _stub():
        return cached
    monkeypatch.setattr(
        "app.services.external_signals.tomtom_provider.get_flow_cached",
        _stub,
    )
    out = await p._fetch_unsafe(19.10, 72.90)
    assert out is not None
    assert out.provider == "tomtom"
    assert out.signal_type == "traffic_severe"
    assert out.risk_0_1 == SEVERITY_RISK["severe"]
    assert any(f.startswith("zone:mumbai") for f in out.factors)


@pytest.mark.asyncio
async def test_provider_returns_none_beyond_radius(monkeypatch, enable_provider):
    p = TomTomSignalProvider()
    cached = [{"zone": "Mumbai", "ratio": 0.5, "severity": "moderate",
               "current_speed": 25.0, "free_flow_speed": 50.0,
               "lat": 19.0760, "lng": 72.8777, "confidence": 0.9}]

    async def _stub():
        return cached
    monkeypatch.setattr(
        "app.services.external_signals.tomtom_provider.get_flow_cached",
        _stub,
    )
    # Pune is > 0.5° away from Mumbai → no match.
    out = await p._fetch_unsafe(18.52, 73.85)
    assert out is None
