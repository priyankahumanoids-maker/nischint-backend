"""NISCH-012.1 — TomTom Flow pre-warmer.

Thin subclass of `ProviderPrewarmer`. Mirrors `sachet_prewarmer.py`
exactly but with TomTom-specific config:

  * Cache namespace = `tomtom`
  * Jitter = 5 min ± 60 s (INDEPENDENT of Sachet — locked by test)
  * Disabled when `TOMTOM_API_KEY` is absent (`is_enabled()`
    override)
  * History source name = `tomtom_health` (in KNOWN_SOURCES)
  * active_count field = `active_zone_count`

All cache-preservation, hysteresis, telemetry, broadcast, and
scheduler plumbing lives in the base class.
"""
from __future__ import annotations

import logging
import os

from app.services.external_signals import base_prewarmer as _base
from app.services.external_signals.base_prewarmer import (
    STATE_DEGRADED, STATE_DISABLED, STATE_HEALTHY, STATE_STALE,
    STATE_UNKNOWN, ProviderPrewarmer,
)
from app.services.external_signals.tomtom_provider import (
    CACHE_KEY as _CACHE_KEY, CACHE_NAMESPACE as _CACHE_NAMESPACE,
    CACHE_TTL_S as _CACHE_TTL_S, fetch_all_zones,
)

logger = logging.getLogger(__name__)


def is_provider_enabled() -> bool:
    """Single source of truth — usable from outside without
    instantiating the prewarmer (the registry checks this)."""
    return bool(os.environ.get("TOMTOM_API_KEY", "").strip())


class TomTomPrewarmer(ProviderPrewarmer):
    name = "TOMTOM"
    cache_namespace = _CACHE_NAMESPACE
    cache_key = _CACHE_KEY
    cache_ttl_s = _CACHE_TTL_S
    telemetry_namespace = "tomtom_prewarmer"
    history_source_name = "tomtom_health"
    jitter_base_s = 300             # 5 min — independent of Sachet
    jitter_range_s = 60             # ±60 s — independent of Sachet
    scheduler_job_id = "tomtom_prewarm_cycle"
    active_count_field = "active_zone_count"
    # Wall-clock budget per cycle. `fetch_all_zones` runs 8 zones
    # in parallel with `HTTP_TIMEOUT_S = 1.0` each — total cycle
    # wall-clock is bounded by the slowest zone, so 1.0 s is the
    # right budget for the chip's amber flag.
    fetch_timeout_s = 1.0

    def is_enabled(self) -> bool:
        return is_provider_enabled()

    async def fetch(self) -> list[dict]:
        result = await fetch_all_zones()
        return list(result) if result else []


# ══════════════════════════════════════════════════════════════════
# Module surface — backward-compat with all tests written against
# the previous module-level API.
# ══════════════════════════════════════════════════════════════════
_instance = TomTomPrewarmer()

# Re-exported constants (legacy import path)
JITTER_BASE_S = TomTomPrewarmer.jitter_base_s
JITTER_RANGE_S = TomTomPrewarmer.jitter_range_s
TELEMETRY_NAMESPACE = TomTomPrewarmer.telemetry_namespace
TELEMETRY_KEY = TomTomPrewarmer.telemetry_key
TELEMETRY_TTL_S = TomTomPrewarmer.telemetry_ttl_s
HISTORY_WINDOW = TomTomPrewarmer.history_window
STATE_KEY = TomTomPrewarmer.state_key

HEALTHY_MAX_AGE_S = TomTomPrewarmer.healthy_max_age_s
STALE_MAX_AGE_S = TomTomPrewarmer.stale_max_age_s
FAILURE_RATE_THRESHOLD = TomTomPrewarmer.failure_rate_threshold
RECOVERY_READS_REQUIRED = TomTomPrewarmer.recovery_reads_required

redis_service = _base.redis_service


# ── Backward-compat: expose `_scheduler` attribute that legacy
# tests inspect directly. We track it via the singleton.
class _SchedulerProxy:
    def __init__(self, instance):
        self._instance = instance

    def __bool__(self):
        return self._instance._scheduler is not None

    def __eq__(self, other):
        return self._instance._scheduler == other


# Some tests do `assert tp._scheduler is None` — the cleanest way
# to preserve that semantic is to mirror the attribute on assignment.
def _refresh_scheduler_alias():
    """Updates the module-level `_scheduler` alias to match the
    singleton's internal handle. Called by start/stop wrappers."""
    global _scheduler
    _scheduler = _instance._scheduler


_scheduler = _instance._scheduler


# ── Module-level delegating functions ────────────────────────────
def compute_next_interval_seconds(rng=None) -> float:
    return _instance.compute_next_interval_seconds(rng)


def compute_raw_state(telemetry: dict, now=None) -> str:
    return _instance.compute_raw_state(telemetry, now)


def evaluate_state_transition(
    prior_state: str, prior_consecutive: int, raw_state: str,
) -> tuple[str, int, bool]:
    return _instance.evaluate_state_transition(
        prior_state, prior_consecutive, raw_state,
    )


def get_prewarmer_telemetry() -> dict:
    return _instance.get_telemetry()


def get_health_state() -> dict:
    return _instance.get_health_state()


async def run_prewarm_cycle() -> dict:
    """Backward-compat wrapper. Translates the neutral
    `item_count` / `no_fresh_items` keys back to legacy
    `zone_count` / `no_fresh_readings` so existing tests pass."""
    result = await _instance.run_cycle()
    if "item_count" in result:
        result["zone_count"] = result.pop("item_count")
    if result.get("status") == "no_fresh_items":
        result["status"] = "no_fresh_readings"
    return result


def start_tomtom_prewarm_scheduler() -> None:
    _instance.start()
    _refresh_scheduler_alias()


def stop_tomtom_prewarm_scheduler() -> None:
    _instance.stop()
    _refresh_scheduler_alias()


# ── Patchable emit shim ──────────────────────────────────────────
def _emit_tomtom_health_delta(prior_state: str, new_state: str,
                              telemetry: dict) -> None:
    """Canonical broadcast for tomtom_health transitions. Kept as
    a module-level function for test monkeypatching (the base
    class's `emit_health_transition` looks this up at call time).

    REL-09: also forwards `* → degraded` and `degraded → healthy`
    transitions to Sentry with a stable fingerprint
    (`tomtom-degraded`) so a streak of outages groups into one
    issue. All other transitions are no-ops on the Sentry side."""
    _instance.default_emit_health_delta(prior_state, new_state, telemetry)
    try:
        from app.services.external_signals.tomtom_sentry import (
            report_health_transition,
        )
        report_health_transition(prior_state, new_state, telemetry)
    except Exception:  # pragma: no cover — telemetry must never raise
        pass


__all__ = [
    "TomTomPrewarmer",
    "JITTER_BASE_S", "JITTER_RANGE_S",
    "TELEMETRY_NAMESPACE", "TELEMETRY_KEY", "TELEMETRY_TTL_S",
    "HISTORY_WINDOW", "STATE_KEY",
    "STATE_HEALTHY", "STATE_STALE", "STATE_DEGRADED", "STATE_UNKNOWN",
    "STATE_DISABLED",
    "HEALTHY_MAX_AGE_S", "STALE_MAX_AGE_S",
    "FAILURE_RATE_THRESHOLD", "RECOVERY_READS_REQUIRED",
    "is_provider_enabled",
    "compute_next_interval_seconds", "compute_raw_state",
    "evaluate_state_transition",
    "run_prewarm_cycle", "get_prewarmer_telemetry", "get_health_state",
    "start_tomtom_prewarm_scheduler", "stop_tomtom_prewarm_scheduler",
]
