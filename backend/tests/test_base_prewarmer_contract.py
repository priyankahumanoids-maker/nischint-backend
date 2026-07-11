"""Base `ProviderPrewarmer` contract — locks the invariants every
subclass inherits unchanged. A new subclass only needs to declare
config + `fetch()`; everything proven here applies to it for free.

Pure-unit: a mock subclass drives a controllable `fetch()`. No
real Redis, no real network, no scheduler spin.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from app.services.external_signals import base_prewarmer as base
from app.services.external_signals.base_prewarmer import (
    STATE_DEGRADED, STATE_DISABLED, STATE_HEALTHY, STATE_STALE,
    STATE_UNKNOWN, ProviderPrewarmer,
)


# ── Mock subclass ────────────────────────────────────────────────
class _MockPrewarmer(ProviderPrewarmer):
    """Controllable subclass. `next_fetch_result` drives the next
    call; `disabled` flips `is_enabled()`."""

    name = "MOCK"
    cache_namespace = "mock_cache"
    cache_key = "items_v1"
    cache_ttl_s = 300
    telemetry_namespace = "mock_prewarmer"
    history_source_name = "mock_health"
    jitter_base_s = 240
    jitter_range_s = 45
    scheduler_job_id = "mock_prewarm_cycle"
    active_count_field = "active_item_count"

    def __init__(self):
        super().__init__()
        self.next_fetch_result: Any = []
        self.disabled = False
        self.fetch_calls = 0

    def is_enabled(self) -> bool:
        return not self.disabled

    async def fetch(self):
        self.fetch_calls += 1
        result = self.next_fetch_result
        if isinstance(result, Exception):
            raise result
        return result


class _RedisDouble:
    """Minimal stand-in keyed by (namespace, key)."""

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
    d = _RedisDouble()
    monkeypatch.setattr(base.redis_service, "get_json", d.get_json)
    monkeypatch.setattr(base.redis_service, "set_json", d.set_json)
    return d


@pytest.fixture
def mock_pw():
    return _MockPrewarmer()


# ════════════════════════════════════════════════════════════════════
# Cache-preservation rule — inherited
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cache_preserved_when_fetch_returns_empty(
        redis_double, mock_pw):
    """Empty fetch must NOT overwrite the cache key — same locked
    contract Sachet + TomTom enforce, now proven once at the base."""
    healthy_cache = [{"id": "X", "v": 1}]
    redis_double.store[(mock_pw.cache_namespace, mock_pw.cache_key)] = (
        healthy_cache
    )
    mock_pw.next_fetch_result = []
    result = await mock_pw.run_cycle()

    assert result["status"] == "no_fresh_items"
    assert redis_double.store[
        (mock_pw.cache_namespace, mock_pw.cache_key)
    ] == healthy_cache
    cache_writes = [
        c for c in redis_double.set_calls if c[0] == mock_pw.cache_namespace
    ]
    assert cache_writes == []


@pytest.mark.asyncio
async def test_cache_preserved_when_fetch_raises(redis_double, mock_pw):
    """Defence-in-depth — a misbehaving subclass that DOES raise
    must NOT corrupt the cache via the base orchestrator."""
    healthy_cache = [{"id": "Y"}]
    redis_double.store[(mock_pw.cache_namespace, mock_pw.cache_key)] = (
        healthy_cache
    )
    mock_pw.next_fetch_result = RuntimeError("boom")
    result = await mock_pw.run_cycle()

    assert result["status"] == "no_fresh_items"
    assert result["raised"] is True
    assert redis_double.store[
        (mock_pw.cache_namespace, mock_pw.cache_key)
    ] == healthy_cache


@pytest.mark.asyncio
async def test_cache_overwritten_only_on_non_empty_success(
        redis_double, mock_pw):
    fresh = [{"id": "A"}, {"id": "B"}]
    mock_pw.next_fetch_result = fresh
    result = await mock_pw.run_cycle()
    assert result == {"status": "success", "item_count": 2}
    cache_writes = [
        c for c in redis_double.set_calls if c[0] == mock_pw.cache_namespace
    ]
    assert len(cache_writes) == 1
    ns, key, value, ttl = cache_writes[0]
    assert value == fresh
    assert ttl == mock_pw.cache_ttl_s


# ════════════════════════════════════════════════════════════════════
# 3-clean-read hysteresis — inherited
# ════════════════════════════════════════════════════════════════════

def test_regression_snaps_immediately(mock_pw):
    state, counter, transitioned = mock_pw.evaluate_state_transition(
        STATE_HEALTHY, 0, STATE_DEGRADED,
    )
    assert (state, counter, transitioned) == (STATE_DEGRADED, 0, True)


def test_recovery_requires_three_consecutive_clean_reads(mock_pw):
    # First read after degraded sees healthy — counter advances, no transition.
    state, counter, transitioned = mock_pw.evaluate_state_transition(
        STATE_DEGRADED, 0, STATE_HEALTHY,
    )
    assert (state, counter, transitioned) == (STATE_DEGRADED, 1, False)

    state, counter, transitioned = mock_pw.evaluate_state_transition(
        STATE_DEGRADED, 1, STATE_HEALTHY,
    )
    assert (state, counter, transitioned) == (STATE_DEGRADED, 2, False)

    state, counter, transitioned = mock_pw.evaluate_state_transition(
        STATE_DEGRADED, 2, STATE_HEALTHY,
    )
    assert (state, counter, transitioned) == (STATE_HEALTHY, 0, True)


def test_recovery_counter_resets_on_regression_during_gate(mock_pw):
    state, counter, transitioned = mock_pw.evaluate_state_transition(
        STATE_DEGRADED, 1, STATE_DEGRADED,
    )
    assert (state, counter, transitioned) == (STATE_DEGRADED, 0, False)


def test_unknown_to_first_observation_snaps(mock_pw):
    state, counter, transitioned = mock_pw.evaluate_state_transition(
        STATE_UNKNOWN, 0, STATE_HEALTHY,
    )
    assert (state, transitioned) == (STATE_HEALTHY, True)


# ════════════════════════════════════════════════════════════════════
# Disabled-mode short-circuit — inherited
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_disabled_mode_short_circuits_run_cycle(redis_double, mock_pw):
    mock_pw.disabled = True
    result = await mock_pw.run_cycle()
    assert result == {"status": "disabled", "reason": "no_api_key"}
    # No Redis writes anywhere — disabled is a true no-op.
    assert redis_double.set_calls == []
    # Fetch must NOT have been called.
    assert mock_pw.fetch_calls == 0


def test_disabled_mode_short_circuits_start(mock_pw):
    """Scheduler refuses to register when disabled — protects
    against the prewarmer poisoning Redis with empty-fetch noise."""
    mock_pw.disabled = True
    mock_pw.start()
    assert mock_pw._scheduler is None


def test_disabled_mode_telemetry_returns_disabled_shape(
        redis_double, mock_pw):
    mock_pw.disabled = True
    out = mock_pw.get_telemetry()
    assert out["health_state"] == STATE_DISABLED
    assert out["reason"] == "no_api_key"


def test_disabled_mode_health_state_returns_disabled(redis_double, mock_pw):
    mock_pw.disabled = True
    out = mock_pw.get_health_state()
    assert out["state"] == STATE_DISABLED
    assert out["reason"] == "no_api_key"


# ════════════════════════════════════════════════════════════════════
# Broadcast (transition-only) — inherited
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_broadcast_fires_only_on_state_transition(
        redis_double, mock_pw, monkeypatch):
    """Mirrors the per-provider test but proven once at the base —
    transition fires emit, no-op tick stays silent."""
    fires: list = []

    def _spy(prior, new, telem):
        fires.append((prior, new))

    monkeypatch.setattr(mock_pw, "emit_health_transition", _spy)

    # Cycle 1 — cold start, fetch succeeds → unknown → healthy.
    mock_pw.next_fetch_result = [{"id": 1}]
    await mock_pw.run_cycle()
    assert fires == [(STATE_UNKNOWN, STATE_HEALTHY)]

    # Cycle 2 — still healthy, no transition, no broadcast.
    mock_pw.next_fetch_result = [{"id": 2}]
    await mock_pw.run_cycle()
    assert fires == [(STATE_UNKNOWN, STATE_HEALTHY)]


@pytest.mark.asyncio
async def test_module_level_emit_shim_is_patchable(
        redis_double, mock_pw, monkeypatch):
    """The legacy `_emit_<source>_delta` module-level hook
    monkeypatched by tests must intercept the broadcast — the base
    class's `emit_health_transition` looks it up at call time via
    `sys.modules`. Without this indirection the refactor breaks
    every existing per-provider test that patches the emit
    function."""
    import sys
    mock_module = sys.modules[_MockPrewarmer.__module__]
    captured: list = []

    def _fake_emit(prior, new, telem):
        captured.append((prior, new))

    # Install the patchable shim with the conventional name.
    monkeypatch.setattr(
        mock_module, "_emit_mock_health_delta", _fake_emit,
        raising=False,
    )

    mock_pw.next_fetch_result = [{"id": 1}]
    await mock_pw.run_cycle()
    assert captured == [(STATE_UNKNOWN, STATE_HEALTHY)]


# ════════════════════════════════════════════════════════════════════
# Telemetry contract — inherited
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_telemetry_failure_does_not_advance_last_success(
        redis_double, mock_pw):
    prior_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=12)
    ).isoformat()
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ] = {
        "last_fetch_ts":      prior_iso,
        "last_success_ts":    prior_iso,
        "parse_failure_rate": 0.0,
        mock_pw.active_count_field: 7,
        "attempt_history":    [True],
    }
    mock_pw.next_fetch_result = []
    await mock_pw.run_cycle()
    telem = redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ]
    assert telem["last_success_ts"] == prior_iso
    assert telem["last_fetch_ts"] != prior_iso
    assert telem[mock_pw.active_count_field] == 7    # preserved
    assert telem["attempt_history"] == [True, False]


# ════════════════════════════════════════════════════════════════════
# Raw-state thresholds — inherited
# ════════════════════════════════════════════════════════════════════

def test_raw_state_thresholds_inherited(mock_pw):
    def _telem(age_s, rate=0.0):
        if age_s is None:
            return {"last_success_ts": None, "parse_failure_rate": rate}
        ts = datetime.now(timezone.utc) - timedelta(seconds=age_s)
        return {
            "last_success_ts":    ts.isoformat(),
            "parse_failure_rate": rate,
        }
    assert mock_pw.compute_raw_state(_telem(None)) == STATE_UNKNOWN
    assert mock_pw.compute_raw_state(_telem(120, 0.10)) == STATE_HEALTHY
    assert mock_pw.compute_raw_state(_telem(720, 0.0)) == STATE_STALE
    assert mock_pw.compute_raw_state(_telem(1801, 0.0)) == STATE_DEGRADED
    assert mock_pw.compute_raw_state(_telem(60, 0.20)) == STATE_DEGRADED


# ════════════════════════════════════════════════════════════════════
# Latency exporter — budget_pressure / budget_warning
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_latency_recorded_only_on_success(redis_double, mock_pw):
    """A failed fetch's wall-clock is dominated by the timeout
    itself — recording it would poison the rolling p95. Only
    successful fetches contribute to the latency window."""
    mock_pw.fetch_timeout_s = 8.0
    mock_pw.next_fetch_result = []
    await mock_pw.run_cycle()
    blob = redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ]
    # No latency entry on the failure path.
    assert blob.get(mock_pw.latency_history_key) == []

    # A success WILL contribute.
    mock_pw.next_fetch_result = [{"id": "A"}]
    await mock_pw.run_cycle()
    blob = redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ]
    assert len(blob[mock_pw.latency_history_key]) == 1


@pytest.mark.asyncio
async def test_budget_warning_fires_when_p95_above_80_percent(
        redis_double, mock_pw, monkeypatch):
    """Locked threshold: p95 / timeout_budget ≥ 80% → warning.
    Simulate by directly seeding 10 latencies bracketing the budget."""
    mock_pw.fetch_timeout_s = 1.0   # 1000 ms budget
    # 10 samples — p95 (nearest-rank) is the 10th when n=10 (ceil(0.95*10)=10).
    # Use 950 ms as the worst sample → 950/1000 = 95 % → warning.
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ] = {
        "attempt_history":    [True] * 10,
        "parse_failure_rate": 0.0,
        "last_fetch_ts":      "2026-05-01T00:00:00+00:00",
        "last_success_ts":    "2026-05-01T00:00:00+00:00",
        mock_pw.active_count_field: 1,
        mock_pw.latency_history_key: [
            100.0, 150.0, 200.0, 250.0, 300.0,
            400.0, 500.0, 700.0, 800.0, 950.0,
        ],
    }
    out = mock_pw.get_telemetry()
    assert out["latency_p50_ms"] == 300.0      # 5th of 10 (nearest-rank)
    assert out["latency_p95_ms"] == 950.0
    assert out["timeout_budget_ms"] == 1000.0
    assert out["budget_pressure_pct"] == 95.0
    assert out["budget_warning"] is True


@pytest.mark.asyncio
async def test_budget_warning_silent_below_threshold(redis_double, mock_pw):
    """p95 / budget < 80% MUST NOT fire — guards against
    operator-fatigue alerts on healthy providers."""
    mock_pw.fetch_timeout_s = 1.0
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ] = {
        "attempt_history":    [True] * 10,
        "parse_failure_rate": 0.0,
        "last_fetch_ts":      "2026-05-01T00:00:00+00:00",
        "last_success_ts":    "2026-05-01T00:00:00+00:00",
        mock_pw.active_count_field: 1,
        mock_pw.latency_history_key: [
            50.0, 80.0, 100.0, 120.0, 150.0,
            200.0, 250.0, 300.0, 400.0, 600.0,
        ],
    }
    out = mock_pw.get_telemetry()
    assert out["budget_pressure_pct"] == 60.0    # 600/1000
    assert out["budget_warning"] is False


@pytest.mark.asyncio
async def test_budget_warning_suppressed_under_3_samples(
        redis_double, mock_pw):
    """A single slow request must not amber-flag an otherwise-
    healthy provider. Minimum 3 samples required before the chip
    can warn — locked in `BUDGET_WARNING_PCT` guard."""
    mock_pw.fetch_timeout_s = 1.0
    # Two slow samples each at 99% of budget — would trigger if
    # the floor weren't enforced.
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ] = {
        "attempt_history":    [True, True],
        "parse_failure_rate": 0.0,
        "last_fetch_ts":      "2026-05-01T00:00:00+00:00",
        "last_success_ts":    "2026-05-01T00:00:00+00:00",
        mock_pw.active_count_field: 1,
        mock_pw.latency_history_key: [990.0, 995.0],
    }
    out = mock_pw.get_telemetry()
    assert out["latency_sample_size"] == 2
    # Pressure is computable from samples, but warning is gated.
    assert out["budget_pressure_pct"] is not None
    assert out["budget_warning"] is False


def test_latency_summary_cold_start_returns_nones(redis_double, mock_pw):
    """Cold Redis must return a stable shape with `None` percentiles
    and `budget_warning = False` — operator capsule polls this
    immediately on first paint, before any cycle has fired."""
    mock_pw.fetch_timeout_s = 2.0
    out = mock_pw.get_telemetry()
    assert out["latency_p50_ms"] is None
    assert out["latency_p95_ms"] is None
    assert out["latency_p99_ms"] is None
    assert out["latency_sample_size"] == 0
    assert out["timeout_budget_ms"] == 2000.0
    assert out["budget_warning"] is False


def test_latency_summary_handles_no_budget_declared(redis_double, mock_pw):
    """If a subclass forgets to set `fetch_timeout_s`, we MUST NOT
    divide by zero or fire spurious warnings — instead return
    `None`/`False` and let the operator notice via a missing
    `timeout_budget_ms` rather than a crash."""
    mock_pw.fetch_timeout_s = 0.0      # not declared
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ] = {
        "attempt_history":    [True] * 5,
        "parse_failure_rate": 0.0,
        "last_fetch_ts":      "2026-05-01T00:00:00+00:00",
        "last_success_ts":    "2026-05-01T00:00:00+00:00",
        mock_pw.active_count_field: 1,
        mock_pw.latency_history_key: [100.0, 200.0, 300.0, 400.0, 500.0],
    }
    out = mock_pw.get_telemetry()
    assert out["timeout_budget_ms"] is None
    assert out["budget_pressure_pct"] is None
    assert out["budget_warning"] is False
    # Percentiles still computed — they're useful even without a
    # budget for "is this provider getting slower?" trending.
    assert out["latency_p50_ms"] == 300.0
    assert out["latency_p95_ms"] == 500.0


def test_subclass_fetch_timeout_s_locked_per_provider():
    """Each shipped subclass MUST declare a non-zero
    fetch_timeout_s — protects against the regression that
    silently shipped this PR without wiring a provider's budget."""
    from app.services.external_signals.sachet_prewarmer import SachetPrewarmer
    from app.services.external_signals.tomtom_prewarmer import TomTomPrewarmer
    from app.services.external_signals.news_prewarmer import NewsPrewarmer
    assert SachetPrewarmer.fetch_timeout_s == 8.0
    assert TomTomPrewarmer.fetch_timeout_s == 1.0
    assert NewsPrewarmer.fetch_timeout_s == 5.0


# ════════════════════════════════════════════════════════════════════
# Latency exporter — defensive read-path edge cases
# ════════════════════════════════════════════════════════════════════

def test_percentile_monotonic_across_p50_p95_p99(mock_pw):
    """Nearest-rank percentiles MUST satisfy p50 ≤ p95 ≤ p99 for
    every non-empty input. A regression here corrupts every
    operator capsule decision."""
    import random as _r
    rng = _r.Random(42)
    for trial in range(50):
        n = rng.randint(1, 50)
        samples = [rng.uniform(0.5, 2000.0) for _ in range(n)]
        out = mock_pw._latency_summary(samples)
        p50, p95, p99 = (
            out["latency_p50_ms"], out["latency_p95_ms"], out["latency_p99_ms"],
        )
        # Round-trip via round(_, 1) means equality is possible at
        # small n; monotonicity is non-strict.
        assert p50 is not None and p95 is not None and p99 is not None
        assert p50 <= p95 <= p99, (
            f"non-monotonic at trial={trial} n={n}: "
            f"p50={p50} p95={p95} p99={p99}"
        )


def test_single_sample_returns_that_value_for_all_percentiles(mock_pw):
    """One sample → p50/p95/p99 all equal that sample. Sample size
    of 1 is below the 3-sample warning floor, so budget_warning
    must stay False even if the sample exceeds the threshold."""
    mock_pw.fetch_timeout_s = 1.0
    out = mock_pw._latency_summary([950.0])
    assert out["latency_p50_ms"] == 950.0
    assert out["latency_p95_ms"] == 950.0
    assert out["latency_p99_ms"] == 950.0
    assert out["latency_sample_size"] == 1
    assert out["budget_warning"] is False     # gated by 3-sample floor


def test_even_sized_window_percentile_uses_nearest_rank(mock_pw):
    """Locks the nearest-rank convention against a future
    'switch to linear interpolation' drive-by refactor. n=10
    → p50 = ceil(0.5*10) = 5th value; p95 = 10th; p99 = 10th."""
    samples = [10.0, 20.0, 30.0, 40.0, 50.0,
               60.0, 70.0, 80.0, 90.0, 100.0]
    out = mock_pw._latency_summary(samples)
    assert out["latency_p50_ms"] == 50.0     # 5th of 10
    assert out["latency_p95_ms"] == 100.0    # 10th
    assert out["latency_p99_ms"] == 100.0    # 10th
    # n=4 — even size, smaller
    out4 = mock_pw._latency_summary([5.0, 10.0, 15.0, 20.0])
    assert out4["latency_p50_ms"] == 10.0    # 2nd (ceil(0.5*4)=2)
    assert out4["latency_p95_ms"] == 20.0    # 4th (ceil(0.95*4)=4)


def test_malformed_latency_values_do_not_crash(mock_pw):
    """Defensive read: a corrupted Redis blob with strings/None/NaN/
    negatives must not crash the operator capsule. The exporter
    silently drops bad entries and reports on the survivors."""
    mock_pw.fetch_timeout_s = 1.0
    poisoned = [
        100.0, None, "oops", 200.0, float("nan"),
        -50.0, float("inf"), 300.0,
    ]
    out = mock_pw._latency_summary(poisoned)
    # Only the 3 clean values survive.
    assert out["latency_sample_size"] == 3
    assert out["latency_p50_ms"] == 200.0
    assert out["latency_p95_ms"] == 300.0
    assert out["latency_p99_ms"] == 300.0


def test_budget_warning_threshold_boundary_exactly_at_80_percent(
        redis_double, mock_pw):
    """Threshold is `>= 80%`. A p95 / budget hitting exactly 80.0%
    MUST trip the warning — locks the comparison operator so a
    future `>` drive-by refactor doesn't silently widen the
    operator-blind zone."""
    mock_pw.fetch_timeout_s = 1.0
    # 10 samples, p95 (rank 10) = 800.0 → exactly 80.0 % of 1000 ms.
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ] = {
        "attempt_history":    [True] * 10,
        "parse_failure_rate": 0.0,
        "last_fetch_ts":      "2026-05-01T00:00:00+00:00",
        "last_success_ts":    "2026-05-01T00:00:00+00:00",
        mock_pw.active_count_field: 1,
        mock_pw.latency_history_key: [
            100.0, 150.0, 200.0, 250.0, 300.0,
            400.0, 500.0, 600.0, 700.0, 800.0,
        ],
    }
    out = mock_pw.get_telemetry()
    assert out["latency_p95_ms"] == 800.0
    assert out["budget_pressure_pct"] == 80.0
    assert out["budget_warning"] is True

    # And one tick below the boundary — must stay silent.
    redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ][mock_pw.latency_history_key] = [
        100.0, 150.0, 200.0, 250.0, 300.0,
        400.0, 500.0, 600.0, 700.0, 799.0,
    ]
    out = mock_pw.get_telemetry()
    assert out["latency_p95_ms"] == 799.0
    assert out["budget_pressure_pct"] == 79.9
    assert out["budget_warning"] is False


def test_telemetry_serialization_shape_backward_compatible(
        redis_double, mock_pw):
    """The operator UI reads a stable shape. Lock the field set so
    the exporter never silently drops or renames a key. Updating
    this test requires updating the capsule UI in lockstep."""
    mock_pw.fetch_timeout_s = 1.0
    out = mock_pw.get_telemetry()
    expected_keys = {
        # Pre-existing fields (must remain).
        "last_fetch_ts", "last_success_ts", "parse_failure_rate",
        mock_pw.active_count_field, "cache_age_seconds", "cache_ttl_s",
        "attempt_history_size", "history_window",
        "jitter_base_s", "jitter_range_s", "health_state",
        "recovery_progress", "recovery_required", "last_transition_at",
        "healthy_max_age_s", "stale_max_age_s",
        "failure_rate_threshold",
        # Latency exporter fields (new — must be present).
        "latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
        "latency_sample_size", "timeout_budget_ms",
        "budget_pressure_pct", "budget_warning",
    }
    assert set(out.keys()) == expected_keys


@pytest.mark.asyncio
async def test_run_cycle_records_latency_on_cache_write_failure(
        redis_double, mock_pw, monkeypatch):
    """The cache-write-failed branch must still record latency —
    the fetch DID succeed and its wall-clock is a real signal.
    Without this the percentile window goes silent during a Redis
    write outage, masking provider slowdowns the operator needs to
    see."""
    mock_pw.fetch_timeout_s = 1.0
    mock_pw.next_fetch_result = [{"id": 1}]

    real_set = redis_double.set_json
    cache_ns = mock_pw.cache_namespace

    def _flaky_set(ns, key, value, ttl=None):
        if ns == cache_ns:
            raise RuntimeError("redis down")
        return real_set(ns, key, value, ttl=ttl)

    monkeypatch.setattr(base.redis_service, "set_json", _flaky_set)
    result = await mock_pw.run_cycle()
    assert result["status"] == "cache_write_failed"
    blob = redis_double.store[
        (mock_pw.telemetry_namespace, mock_pw.telemetry_key)
    ]
    # Latency recorded despite the cache write blowing up.
    assert len(blob[mock_pw.latency_history_key]) == 1
    assert blob[mock_pw.latency_history_key][0] >= 0

