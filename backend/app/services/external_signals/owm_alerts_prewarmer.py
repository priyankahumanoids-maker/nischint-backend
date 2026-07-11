"""REL-09 Step 2 — OpenWeatherMap OneCall 3.0 severe-alert prewarmer.

15-minute polling cycle for 6 Indian metros (Mumbai, Delhi,
Bengaluru, Chennai, Hyderabad, Kolkata). Merges results into the
`owm_alerts/alerts_by_metro_v1` Redis cache with per-metro
cache-preservation: a transient failure for ONE metro does NOT
erase the other 5's last-known state.

Stays a thin subclass of `ProviderPrewarmer` — only `run_cycle` is
overridden, because the prewarmer's cache shape is dict-by-metro,
not the base class's flat list-of-items shape. Everything else
(jitter scheduling, telemetry, hysteresis, sentry transitions) is
inherited unchanged.

Locked invariants (driven by tests):
  * Provider-level disabled when `OPENWEATHER_API_KEY` is missing.
  * 15 min ± 60 s uniform jitter (INDEPENDENT of Sachet's 4 ± 45,
    TomTom's 5 ± 60, News's 15 ± 120).
  * Cache-preservation per metro (NOT global) so one bad metro
    doesn't wipe the other five.
  * `_emit_owm_alerts_health_delta` forwards `* → degraded` and
    `degraded → healthy` to Sentry with stable fingerprint
    `weather-degraded`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services import redis_service
from app.services.external_signals import base_prewarmer as _base
from app.services.external_signals.base_prewarmer import (
    STATE_DEGRADED, STATE_DISABLED, STATE_HEALTHY, STATE_STALE,
    STATE_UNKNOWN, ProviderPrewarmer,
)
from app.services.external_signals.owm_alerts_provider import (
    CACHE_KEY as _CACHE_KEY,
    CACHE_NAMESPACE as _CACHE_NAMESPACE,
    CACHE_TTL_S as _CACHE_TTL_S,
    METROS, PREWARMER_TIMEOUT_S,
    _merge_with_cached,
    fetch_all_metros,
    get_alerts_cached,
)

logger = logging.getLogger(__name__)


def is_provider_enabled() -> bool:
    """Single source of truth — usable from outside without
    instantiating the prewarmer."""
    import os
    return bool((os.environ.get("OPENWEATHER_API_KEY") or "").strip())


class OWMAlertsPrewarmer(ProviderPrewarmer):
    name = "OWM_ALERTS"
    cache_namespace = _CACHE_NAMESPACE
    cache_key = _CACHE_KEY
    cache_ttl_s = _CACHE_TTL_S
    telemetry_namespace = "owm_alerts_prewarmer"
    history_source_name = "weather_alerts_health"
    jitter_base_s = 900             # 15 min — user-spec'd
    jitter_range_s = 60             # ±60 s
    scheduler_job_id = "owm_alerts_prewarm_cycle"
    active_count_field = "active_alert_count"
    fetch_timeout_s = PREWARMER_TIMEOUT_S

    def is_enabled(self) -> bool:
        return is_provider_enabled()

    async def fetch(self) -> list[dict]:  # pragma: no cover — not used
        """Required by the base class signature but not used — we
        override `run_cycle` because the cache shape is
        dict-by-metro, not the base's flat list. Kept as a no-op
        for any external caller that might invoke it directly."""
        return []

    async def run_cycle(self) -> dict:
        """Custom cycle: dict-by-metro fetch + per-metro merge.

        Why this differs from the base class:
          * The base treats `fetch()`'s empty list as "cache
            untouched". For OWM alerts, an empty list could
            legitimately mean "all 6 metros responded with zero
            alerts" — we MUST persist that (otherwise the cache
            would never roll forward to clear stale alerts).
          * Per-metro merge: if 4/6 metros succeed, we persist
            those 4 fresh + carry-forward the other 2 from cache.
            The base class can't express this; the merge is owned
            by `owm_alerts_provider._merge_with_cached`.

        Contracts preserved from the base:
          * Telemetry recording via `_record_attempt`.
          * Health-state transitions via `_evaluate_and_persist_health`.
          * Never raises.
        """
        import time as _time

        if not self.is_enabled():
            return {"status": "disabled", "reason": "no_api_key"}

        raised = False
        t0 = _time.monotonic()
        try:
            fresh = await fetch_all_metros()
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s_PREWARMER] fetch raised: %r", self.name, e)
            fresh = {}
            raised = True
        latency_ms = (_time.monotonic() - t0) * 1000.0

        if fresh:
            # At least one metro succeeded → merge + persist.
            try:
                cached = await get_alerts_cached()
                merged = _merge_with_cached(fresh, cached or {})
                redis_service.set_json(
                    self.cache_namespace, self.cache_key,
                    merged, ttl=self.cache_ttl_s,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[%s_PREWARMER] cache write failed: %r",
                    self.name, e,
                )
                self._record_attempt(
                    success=False, item_count=0, latency_ms=latency_ms,
                )
                self._evaluate_and_persist_health()
                return {
                    "status": "cache_write_failed",
                    "metros_fresh": len(fresh),
                }
            # `item_count` for telemetry → total active alerts across
            # all metros (NOT the metro count). Operator chip reads
            # this as the "active alert count" badge.
            total_alerts = sum(len(v) for v in merged.values())
            self._record_attempt(
                success=True,
                item_count=total_alerts,
                latency_ms=latency_ms,
            )
            self._evaluate_and_persist_health()
            logger.info(
                "[%s_PREWARMER] cache refreshed metros_fresh=%d "
                "metros_total=%d active_alerts=%d latency_ms=%.0f",
                self.name, len(fresh), len(merged),
                total_alerts, latency_ms,
            )
            return {
                "status":         "success",
                "metros_fresh":   len(fresh),
                "metros_total":   len(merged),
                "active_alerts":  total_alerts,
                "item_count":     total_alerts,
            }

        # All 6 metros failed (or batch raised) — cache untouched.
        self._record_attempt(success=False, item_count=0, latency_ms=None)
        self._evaluate_and_persist_health()
        logger.info(
            "[%s_PREWARMER] cache preserved (all metros failed, raised=%s)",
            self.name, raised,
        )
        return {
            "status":  "no_fresh_items",
            "metros_fresh": 0,
            "raised":  raised,
        }


# ══════════════════════════════════════════════════════════════════
# Module surface — mirrors the pattern of the other prewarmers
# ══════════════════════════════════════════════════════════════════
_instance = OWMAlertsPrewarmer()

JITTER_BASE_S = OWMAlertsPrewarmer.jitter_base_s
JITTER_RANGE_S = OWMAlertsPrewarmer.jitter_range_s
TELEMETRY_NAMESPACE = OWMAlertsPrewarmer.telemetry_namespace
TELEMETRY_KEY = OWMAlertsPrewarmer.telemetry_key
TELEMETRY_TTL_S = OWMAlertsPrewarmer.telemetry_ttl_s
HISTORY_WINDOW = OWMAlertsPrewarmer.history_window
STATE_KEY = OWMAlertsPrewarmer.state_key

HEALTHY_MAX_AGE_S = OWMAlertsPrewarmer.healthy_max_age_s
STALE_MAX_AGE_S = OWMAlertsPrewarmer.stale_max_age_s
FAILURE_RATE_THRESHOLD = OWMAlertsPrewarmer.failure_rate_threshold
RECOVERY_READS_REQUIRED = OWMAlertsPrewarmer.recovery_reads_required


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
    base = _instance.get_telemetry()
    base["metros_covered"] = [slug for slug, _, _ in METROS]
    return base


def get_health_state() -> dict:
    return _instance.get_health_state()


async def run_prewarm_cycle() -> dict:
    return await _instance.run_cycle()


def start_owm_alerts_prewarm_scheduler() -> None:
    _instance.start()


def stop_owm_alerts_prewarm_scheduler() -> None:
    _instance.stop()


def _emit_owm_alerts_health_delta(prior_state: str, new_state: str,
                                  telemetry: dict) -> None:
    """Canonical broadcast for weather_alerts_health transitions.

    REL-09: forwards `* → degraded` and `degraded → healthy` to
    Sentry with the shared `weather-degraded` fingerprint so OWM
    OneCall alert outages group with any future current-conditions
    weather degradation."""
    _instance.default_emit_health_delta(prior_state, new_state, telemetry)
    try:
        from app.services.external_signals.weather_sentry import (
            report_health_transition,
        )
        report_health_transition(prior_state, new_state, telemetry)
    except Exception:  # pragma: no cover — telemetry must never raise
        pass


__all__ = [
    "OWMAlertsPrewarmer",
    "JITTER_BASE_S", "JITTER_RANGE_S",
    "TELEMETRY_NAMESPACE", "TELEMETRY_KEY", "TELEMETRY_TTL_S",
    "HISTORY_WINDOW", "STATE_KEY",
    "STATE_HEALTHY", "STATE_STALE", "STATE_DEGRADED",
    "STATE_UNKNOWN", "STATE_DISABLED",
    "HEALTHY_MAX_AGE_S", "STALE_MAX_AGE_S",
    "FAILURE_RATE_THRESHOLD", "RECOVERY_READS_REQUIRED",
    "is_provider_enabled",
    "compute_next_interval_seconds", "compute_raw_state",
    "evaluate_state_transition",
    "run_prewarm_cycle", "get_prewarmer_telemetry", "get_health_state",
    "start_owm_alerts_prewarm_scheduler",
    "stop_owm_alerts_prewarm_scheduler",
]
