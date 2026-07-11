"""NISCH-012.3 — Sachet pre-warmer scheduler unit tests.

Locks the four invariants the user mandated:
  1. Jitter stays within bounds over 100 iterations.
  2. Cache untouched when fetch returns None / empty list.
  3. Cache untouched when fetch raises an exception.
  4. Telemetry is written correctly on both success and failure paths.

Plus contract tests for `get_prewarmer_telemetry()` and the
scheduler lifecycle (start/stop is idempotent).

Pure-unit. No real network, no real Redis.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.external_signals import sachet_prewarmer as sp
from app.services.external_signals.sachet_prewarmer import (
    FAILURE_RATE_THRESHOLD, HEALTHY_MAX_AGE_S, HISTORY_WINDOW,
    JITTER_BASE_S, JITTER_RANGE_S, RECOVERY_READS_REQUIRED,
    STALE_MAX_AGE_S, STATE_DEGRADED, STATE_HEALTHY, STATE_KEY,
    STATE_STALE, STATE_UNKNOWN, TELEMETRY_KEY, TELEMETRY_NAMESPACE,
    compute_next_interval_seconds, compute_raw_state,
    evaluate_state_transition, get_health_state, get_prewarmer_telemetry,
    run_prewarm_cycle, start_sachet_prewarm_scheduler,
    stop_sachet_prewarm_scheduler,
)


# ════════════════════════════════════════════════════════════════════
# Jitter contract — uniform 4 min ± 45 s
# ════════════════════════════════════════════════════════════════════

def test_jitter_bounds_locked():
    assert JITTER_BASE_S == 240          # 4 min
    assert JITTER_RANGE_S == 45          # ±45 s


def test_jitter_stays_within_bounds_over_100_iterations():
    """Uniform random must stay strictly inside [base-range, base+range]
    across 100 samples — protects against drift from regenerating
    schedulers and prevents thundering-herd-on-restart."""
    rng = random.Random(1234)
    low_bound = JITTER_BASE_S - JITTER_RANGE_S       # 195 s
    high_bound = JITTER_BASE_S + JITTER_RANGE_S      # 285 s
    samples = [compute_next_interval_seconds(rng) for _ in range(100)]
    assert min(samples) >= low_bound, f"min={min(samples)} < {low_bound}"
    assert max(samples) <= high_bound, f"max={max(samples)} > {high_bound}"
    # Uniform draw should not collapse to a single value
    assert len(set(round(s, 2) for s in samples)) > 50


def test_jitter_is_uniform_not_constant():
    """The distribution must have spread — a misconfigured constant
    would be a thundering-herd hazard."""
    rng = random.Random(42)
    samples = [compute_next_interval_seconds(rng) for _ in range(200)]
    mean = sum(samples) / len(samples)
    # Mean should sit near the base; large deviation = bias bug.
    assert abs(mean - JITTER_BASE_S) < 5
    spread = max(samples) - min(samples)
    # A real uniform[-45,45] should cover most of the 90-s window.
    assert spread > 60


# ════════════════════════════════════════════════════════════════════
# Cache-preservation contract
# ════════════════════════════════════════════════════════════════════

class _RedisDouble:
    """Minimal stand-in: records every set_json call by (namespace, key)
    so the tests can assert "cache key untouched"."""

    def __init__(self, initial_telemetry=None):
        self.store: dict[tuple[str, str], object] = {}
        if initial_telemetry is not None:
            self.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)] = initial_telemetry
        self.set_calls: list[tuple[str, str, object, int | None]] = []

    def get_json(self, namespace, key):
        return self.store.get((namespace, key))

    def set_json(self, namespace, key, value, ttl=None):
        self.set_calls.append((namespace, key, value, ttl))
        self.store[(namespace, key)] = value
        return True


@pytest.fixture
def redis_double(monkeypatch):
    """Swap redis_service for both the prewarmer module and the
    underlying provider so every set_json hop is observed."""
    dbl = _RedisDouble()
    monkeypatch.setattr(sp.redis_service, "get_json", dbl.get_json)
    monkeypatch.setattr(sp.redis_service, "set_json", dbl.set_json)
    return dbl


@pytest.mark.asyncio
async def test_cache_untouched_when_fetch_returns_empty(redis_double):
    """A fetch that returns `[]` (transient NDMA outage / empty feed)
    must NOT overwrite the parsed-feed cache key. Only the telemetry
    key is touched."""
    # Seed an existing healthy cache so we can prove it stays frozen.
    healthy_cache = [{"identifier": "old1", "title": "old alert"}]
    redis_double.store[("sachet", "rss_parsed_v1")] = healthy_cache

    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=[]),
    ):
        result = await run_prewarm_cycle()

    assert result["status"] == "no_fresh_alerts"
    assert result["raised"] is False
    # Cache key untouched
    assert redis_double.store[("sachet", "rss_parsed_v1")] == healthy_cache
    # No write to the cache namespace; only telemetry + state were written.
    cache_writes = [c for c in redis_double.set_calls if c[0] == "sachet"]
    assert cache_writes == []
    telem_keys = {
        c[1] for c in redis_double.set_calls if c[0] == TELEMETRY_NAMESPACE
    }
    # Telemetry blob + health-state blob (both under sachet_prewarmer ns).
    assert telem_keys == {"telemetry", "health_state"}


@pytest.mark.asyncio
async def test_cache_untouched_when_fetch_raises(redis_double):
    """Defence-in-depth: if `_fetch_feed_uncached` ever stops swallowing
    its own errors (future regression), the pre-warmer must still
    refuse to corrupt the cache."""
    healthy_cache = [{"identifier": "old1"}]
    redis_double.store[("sachet", "rss_parsed_v1")] = healthy_cache

    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(side_effect=RuntimeError("simulated upstream blow-up")),
    ):
        result = await run_prewarm_cycle()

    assert result["status"] == "no_fresh_alerts"
    assert result["raised"] is True
    # Healthy cache survives the upstream blow-up
    assert redis_double.store[("sachet", "rss_parsed_v1")] == healthy_cache
    cache_writes = [c for c in redis_double.set_calls if c[0] == "sachet"]
    assert cache_writes == []


@pytest.mark.asyncio
async def test_cache_overwritten_only_on_non_empty_success(redis_double):
    """Positive path: a non-empty parsed feed must overwrite the
    cache key with the configured 5-min TTL."""
    fresh = [
        {"identifier": "X1", "title": "Cyclone Maharashtra", "severity": "extreme"},
        {"identifier": "X2", "title": "Heat wave Gujarat",   "severity": "severe"},
    ]
    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=fresh),
    ):
        result = await run_prewarm_cycle()

    assert result == {"status": "success", "alert_count": 2}
    # Cache key now holds the fresh list, written with CACHE_TTL_S=300.
    cache_writes = [c for c in redis_double.set_calls if c[0] == "sachet"]
    assert len(cache_writes) == 1
    ns, key, value, ttl = cache_writes[0]
    assert (ns, key) == ("sachet", "rss_parsed_v1")
    assert value == fresh
    assert ttl == 300


# ════════════════════════════════════════════════════════════════════
# Telemetry contract
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_telemetry_written_on_success_path(redis_double):
    fresh = [{"identifier": "X1"}, {"identifier": "X2"}, {"identifier": "X3"}]
    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=fresh),
    ):
        await run_prewarm_cycle()

    telem = redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)]
    assert telem["last_fetch_ts"] is not None
    assert telem["last_success_ts"] is not None
    # Success path → last_fetch_ts == last_success_ts (same call)
    assert telem["last_fetch_ts"] == telem["last_success_ts"]
    assert telem["active_alert_count"] == 3
    assert telem["parse_failure_rate"] == 0.0
    assert telem["attempt_history"] == [True]


@pytest.mark.asyncio
async def test_telemetry_written_on_failure_path(redis_double):
    """On failure: last_fetch_ts advances, last_success_ts does NOT.
    This is the field operators key off — a fresh fetch with a stale
    last_success_ts is the cache-stale signal."""
    # Pre-seed a prior successful run so last_success_ts is non-null.
    prior_success_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=12)
    ).isoformat()
    redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)] = {
        "last_fetch_ts":      prior_success_iso,
        "last_success_ts":    prior_success_iso,
        "parse_failure_rate": 0.0,
        "active_alert_count": 7,
        "attempt_history":    [True],
    }

    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=[]),
    ):
        await run_prewarm_cycle()

    telem = redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)]
    # last_success_ts MUST NOT advance on failure
    assert telem["last_success_ts"] == prior_success_iso
    # last_fetch_ts MUST advance
    assert telem["last_fetch_ts"] != prior_success_iso
    # active_alert_count preserved from the last successful parse
    assert telem["active_alert_count"] == 7
    # rolling history grew, and failure rate reflects the new sample
    assert telem["attempt_history"] == [True, False]
    assert telem["parse_failure_rate"] == 0.5


@pytest.mark.asyncio
async def test_telemetry_history_window_bounded_to_10(redis_double):
    """The rolling parse_failure_rate is per spec the LAST 10 attempts,
    not lifetime. A lifetime metric would mask recent regressions."""
    # Seed 10 successes — the next failure should evict the oldest.
    redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)] = {
        "last_fetch_ts":      "2026-01-01T00:00:00+00:00",
        "last_success_ts":    "2026-01-01T00:00:00+00:00",
        "parse_failure_rate": 0.0,
        "active_alert_count": 5,
        "attempt_history":    [True] * 10,
    }

    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=[]),
    ):
        await run_prewarm_cycle()

    telem = redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)]
    assert len(telem["attempt_history"]) == HISTORY_WINDOW == 10
    # One failure across last-10 → 10% rate, not 100% lifetime.
    assert telem["parse_failure_rate"] == 0.1


# ════════════════════════════════════════════════════════════════════
# get_prewarmer_telemetry — read-time derivation
# ════════════════════════════════════════════════════════════════════

def test_get_prewarmer_telemetry_derives_cache_age(redis_double):
    """`cache_age_seconds` MUST be computed at read time, never stored —
    so a paused scheduler immediately shows an ever-growing age."""
    last_success_dt = datetime.now(timezone.utc) - timedelta(seconds=42)
    redis_double.store[(TELEMETRY_NAMESPACE, TELEMETRY_KEY)] = {
        "last_fetch_ts":      last_success_dt.isoformat(),
        "last_success_ts":    last_success_dt.isoformat(),
        "parse_failure_rate": 0.2,
        "active_alert_count": 4,
        "attempt_history":    [True, False, True],
    }
    out = get_prewarmer_telemetry()
    assert out["cache_age_seconds"] is not None
    # Allow a small tolerance for wall-clock skew during the test
    assert 40 <= out["cache_age_seconds"] <= 60
    assert out["parse_failure_rate"] == 0.2
    assert out["active_alert_count"] == 4
    assert out["cache_ttl_s"] == 300
    assert out["jitter_base_s"] == JITTER_BASE_S
    assert out["jitter_range_s"] == JITTER_RANGE_S


def test_get_prewarmer_telemetry_returns_stable_shape_when_empty(redis_double):
    """Cold Redis (no telemetry yet) must NOT raise — operator UI
    polls this endpoint immediately on first paint."""
    out = get_prewarmer_telemetry()
    assert out["last_fetch_ts"] is None
    assert out["last_success_ts"] is None
    assert out["cache_age_seconds"] is None
    assert out["parse_failure_rate"] == 0.0
    assert out["active_alert_count"] == 0
    assert out["attempt_history_size"] == 0


# ════════════════════════════════════════════════════════════════════
# Scheduler lifecycle
# ════════════════════════════════════════════════════════════════════

def test_start_then_stop_is_idempotent():
    """Calling start twice or stop on a non-running scheduler must
    not raise — supervisor restarts and test fixtures rely on this."""
    import asyncio

    async def _run():
        try:
            start_sachet_prewarm_scheduler()
            start_sachet_prewarm_scheduler()      # double-start no-op
        finally:
            stop_sachet_prewarm_scheduler()
            stop_sachet_prewarm_scheduler()       # double-stop no-op

    asyncio.run(_run())


# ════════════════════════════════════════════════════════════════════
# NISCH-012.4 — Health state machine
# ════════════════════════════════════════════════════════════════════

def _telem(last_success_ago_s, parse_failure_rate=0.0):
    """Build a telemetry blob whose `last_success_ts` sits a fixed
    number of seconds in the past. None → cold-Redis case."""
    if last_success_ago_s is None:
        return {"last_success_ts": None, "parse_failure_rate": parse_failure_rate}
    ts = datetime.now(timezone.utc) - timedelta(seconds=last_success_ago_s)
    return {
        "last_success_ts":    ts.isoformat(),
        "parse_failure_rate": parse_failure_rate,
    }


def test_thresholds_locked():
    """Operator UI legend + state-machine thresholds must move in
    lock-step — break this on purpose if the contract changes."""
    assert HEALTHY_MAX_AGE_S == 600
    assert STALE_MAX_AGE_S == 1800
    assert FAILURE_RATE_THRESHOLD == 0.20
    assert RECOVERY_READS_REQUIRED == 3


def test_raw_state_unknown_when_no_success_ever():
    assert compute_raw_state(_telem(last_success_ago_s=None)) == STATE_UNKNOWN


def test_raw_state_healthy_under_thresholds():
    # 2 min old, 10% failure rate → healthy
    assert compute_raw_state(_telem(120, 0.10)) == STATE_HEALTHY
    # Boundary just below 10 min and just below 20 %.
    assert compute_raw_state(_telem(599, 0.19)) == STATE_HEALTHY


def test_raw_state_stale_between_10_and_30_minutes():
    # 12 min old, 0 % failure → stale (cache still fresh enough to use)
    assert compute_raw_state(_telem(720, 0.0)) == STATE_STALE
    # Just under the 30-min boundary stays stale
    assert compute_raw_state(_telem(1799, 0.0)) == STATE_STALE


def test_raw_state_degraded_beyond_30_minutes_or_high_failure():
    # > 30 min old → degraded
    assert compute_raw_state(_telem(1801, 0.0)) == STATE_DEGRADED
    # < 10 min old BUT failure rate ≥ 20% → degraded (rolling outage)
    assert compute_raw_state(_telem(60, 0.20)) == STATE_DEGRADED
    assert compute_raw_state(_telem(60, 0.50)) == STATE_DEGRADED


# ── Hysteresis: regression snaps, recovery delays ─────────────────

def test_regression_snaps_immediately_from_healthy_to_degraded():
    """An outage that shows up mid-cycle must NOT wait for a
    confirmation gate — operators see the problem on the next tick."""
    state, counter, transitioned = evaluate_state_transition(
        prior_state=STATE_HEALTHY,
        prior_consecutive=0,
        raw_state=STATE_DEGRADED,
    )
    assert state == STATE_DEGRADED
    assert counter == 0
    assert transitioned is True


def test_regression_snaps_from_healthy_to_stale():
    state, counter, transitioned = evaluate_state_transition(
        STATE_HEALTHY, 0, STATE_STALE,
    )
    assert state == STATE_STALE
    assert counter == 0
    assert transitioned is True


def test_recovery_requires_three_consecutive_clean_reads():
    """The locked invariant — single lucky fetch after a degraded
    period must NOT flip us back to healthy."""
    # Read 1 — counter advances but state stays degraded.
    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 0, STATE_HEALTHY,
    )
    assert state == STATE_DEGRADED
    assert counter == 1
    assert transitioned is False

    # Read 2 — still pending.
    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 1, STATE_HEALTHY,
    )
    assert state == STATE_DEGRADED
    assert counter == 2
    assert transitioned is False

    # Read 3 — gate opens.
    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 2, STATE_HEALTHY,
    )
    assert state == STATE_HEALTHY
    assert counter == 0
    assert transitioned is True


def test_recovery_resets_on_regression_during_gate():
    """If a "recovering" cycle sees the bad state again before the
    gate opens, the counter must reset — we are NOT recovering."""
    state, counter, transitioned = evaluate_state_transition(
        STATE_DEGRADED, 0, STATE_HEALTHY,
    )
    assert counter == 1  # making progress

    # Next tick reverts to the bad state — counter resets.
    state, counter, transitioned = evaluate_state_transition(
        state, counter, STATE_DEGRADED,
    )
    assert state == STATE_DEGRADED
    assert counter == 0
    assert transitioned is False


def test_unknown_to_first_observation_snaps():
    """First-ever read from cold start must not wait 3 cycles —
    treating `unknown` as a placeholder lets the operator see
    state immediately on first successful fetch."""
    state, counter, transitioned = evaluate_state_transition(
        STATE_UNKNOWN, 0, STATE_HEALTHY,
    )
    assert state == STATE_HEALTHY
    assert transitioned is True


def test_same_state_does_not_transition():
    state, counter, transitioned = evaluate_state_transition(
        STATE_HEALTHY, 0, STATE_HEALTHY,
    )
    assert state == STATE_HEALTHY
    assert counter == 0
    assert transitioned is False


# ── Transition broadcast wiring ──────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_fires_only_on_transition(redis_double, monkeypatch):
    """WS emission must fire on the cycle that transitions and stay
    silent on no-op ticks — protects operator inbox from heartbeat
    spam and keeps the V2-parity-style invariant in place."""
    broadcasts: list = []

    def _fake_emit(prior, new, telem):
        broadcasts.append((prior, new))

    monkeypatch.setattr(sp, "_emit_sachet_health_delta", _fake_emit)

    fresh = [{"identifier": "X1"}]

    # Tick 1: cold → first successful fetch → transitions UNKNOWN→HEALTHY.
    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=fresh),
    ):
        await run_prewarm_cycle()
    assert broadcasts == [(STATE_UNKNOWN, STATE_HEALTHY)]

    # Tick 2: still healthy → no transition → no broadcast.
    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=fresh),
    ):
        await run_prewarm_cycle()
    assert broadcasts == [(STATE_UNKNOWN, STATE_HEALTHY)]


@pytest.mark.asyncio
async def test_broadcast_fires_on_regression(redis_double, monkeypatch):
    """A run of failures that drives the rolling rate to ≥20%
    snaps the chip to DEGRADED and broadcasts the transition."""
    broadcasts: list = []
    monkeypatch.setattr(
        sp, "_emit_sachet_health_delta",
        lambda p, n, t: broadcasts.append((p, n)),
    )

    fresh = [{"identifier": "X1"}]
    # Establish healthy baseline.
    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=fresh),
    ):
        await run_prewarm_cycle()
    assert broadcasts[-1] == (STATE_UNKNOWN, STATE_HEALTHY)

    # Four consecutive failures → rolling failure_rate = 4/5 = 0.8 ≥ 0.2
    # → regression to DEGRADED snaps on the cycle that crosses the line.
    with patch(
        "app.services.external_signals.sachet_prewarmer._fetch_feed_uncached",
        new=AsyncMock(return_value=[]),
    ):
        for _ in range(4):
            await run_prewarm_cycle()

    # There must be exactly ONE healthy→degraded transition recorded
    # (the cycle that crosses the threshold). All subsequent failing
    # cycles must NOT re-broadcast — same state.
    healthy_to_degraded = [
        (p, n) for p, n in broadcasts
        if p == STATE_HEALTHY and n == STATE_DEGRADED
    ]
    assert len(healthy_to_degraded) == 1


# ── Endpoint surface ─────────────────────────────────────────────

def test_get_health_state_shape_on_cold_redis(redis_double):
    out = get_health_state()
    assert out["state"] == STATE_UNKNOWN
    assert out["consecutive_better"] == 0
    assert out["recovery_required"] == RECOVERY_READS_REQUIRED
    assert out["last_transition_at"] is None


def test_get_prewarmer_telemetry_includes_health_block(redis_double):
    """The /admin/monitoring/sachet-prewarmer payload must expose
    `health_state` so the operator UI can paint colour-coded chips
    without making a second request."""
    out = get_prewarmer_telemetry()
    for k in (
        "health_state", "recovery_progress", "recovery_required",
        "healthy_max_age_s", "stale_max_age_s", "failure_rate_threshold",
    ):
        assert k in out, f"missing field: {k}"
