"""NISCH-012.3 — Sachet (NDMA) pre-warmer.

NOTE: In production (Emergent us-east-1 egress), expect this prewarmer
to settle in the `degraded` health state — NDMA enforces an Indian-IP
allow-list at the origin. This is documented as a known limitation in
`sachet_provider.py` and `/app/memory/KNOWN_LIMITATIONS.md`. The
operator dashboard's `degraded` indicator for SACHET is expected and
non-paging until a Mumbai-region proxy is deployed.

Thin subclass of `ProviderPrewarmer`. All cache-preservation,
hysteresis, telemetry, broadcast, and scheduler plumbing lives in
the base class — this file is now the per-provider configuration
plus a backward-compat module surface (module-level constants and
delegating functions) that pre-existing tests rely on.

Locked invariants (driven by tests, enforced by the base class):

  * Cache-preservation: empty / raised fetch → cache untouched.
  * Jitter: 4 min ± 45 s uniform (NOT the same as TomTom's 5 ± 60).
  * Telemetry: rolling last-10 attempts.
  * Health states: healthy / stale / degraded / unknown.
  * Asymmetric hysteresis: regress fast, recover after 3 clean reads.
  * SSE replay tail: transitions mirrored to
    `system_health_history.KNOWN_SOURCES["sachet_health"]`.
  * No DB writes — RELIABILITY_DEBT ratchet unaffected.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.external_signals import base_prewarmer as _base
from app.services.external_signals.base_prewarmer import (
    STATE_DEGRADED, STATE_HEALTHY, STATE_STALE, STATE_UNKNOWN,
    ProviderPrewarmer,
)
from app.services.external_signals.sachet_provider import (
    CACHE_KEY as _CACHE_KEY, CACHE_NAMESPACE as _CACHE_NAMESPACE,
    CACHE_TTL_S as _CACHE_TTL_S, PREWARMER_TIMEOUT_S, _fetch_feed_uncached,
)

logger = logging.getLogger(__name__)


class SachetPrewarmer(ProviderPrewarmer):
    name = "SACHET"
    cache_namespace = _CACHE_NAMESPACE
    cache_key = _CACHE_KEY
    cache_ttl_s = _CACHE_TTL_S
    telemetry_namespace = "sachet_prewarmer"
    history_source_name = "sachet_health"
    jitter_base_s = 240             # 4 min
    jitter_range_s = 45             # ±45 s
    scheduler_job_id = "sachet_prewarm_cycle"
    active_count_field = "active_alert_count"
    # Pre-warmer wall-clock budget — matches PREWARMER_TIMEOUT_S in
    # the provider. Exposed on telemetry so the chip can amber-flag
    # if NDMA's response time starts trending toward 80 % of this.
    fetch_timeout_s = 8.0

    async def fetch(self) -> list[dict]:
        # Pre-warmer is a background job — no hot-path budget. Pass
        # the generous 8 s timeout so NDMA's ~1.5 s response lands.
        result = await _fetch_feed_uncached(timeout_s=PREWARMER_TIMEOUT_S)
        return list(result) if result else []


# ══════════════════════════════════════════════════════════════════
# Module surface — backward-compat with all tests written against
# the previous module-level API.
# ══════════════════════════════════════════════════════════════════
_instance = SachetPrewarmer()

# Re-exported constants (legacy import path)
JITTER_BASE_S = SachetPrewarmer.jitter_base_s
JITTER_RANGE_S = SachetPrewarmer.jitter_range_s
TELEMETRY_NAMESPACE = SachetPrewarmer.telemetry_namespace
TELEMETRY_KEY = SachetPrewarmer.telemetry_key
TELEMETRY_TTL_S = SachetPrewarmer.telemetry_ttl_s
HISTORY_WINDOW = SachetPrewarmer.history_window

STATE_KEY = SachetPrewarmer.state_key

HEALTHY_MAX_AGE_S = SachetPrewarmer.healthy_max_age_s
STALE_MAX_AGE_S = SachetPrewarmer.stale_max_age_s
FAILURE_RATE_THRESHOLD = SachetPrewarmer.failure_rate_threshold
RECOVERY_READS_REQUIRED = SachetPrewarmer.recovery_reads_required

# Re-export so existing tests keep using the same names.
redis_service = _base.redis_service


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
    """Backward-compat wrapper. Rebrands the base class's neutral
    `item_count` / `no_fresh_items` to the legacy `alert_count` /
    `no_fresh_alerts` keys so existing tests pass unchanged."""
    result = await _instance.run_cycle()
    # Translate neutral field names back to legacy names.
    if "item_count" in result:
        result["alert_count"] = result.pop("item_count")
    if result.get("status") == "no_fresh_items":
        result["status"] = "no_fresh_alerts"
    return result


def start_sachet_prewarm_scheduler() -> None:
    _instance.start()


def stop_sachet_prewarm_scheduler() -> None:
    _instance.stop()


# ── Patchable emit shim ──────────────────────────────────────────
def _emit_sachet_health_delta(prior_state: str, new_state: str,
                              telemetry: dict) -> None:
    """Canonical broadcast for sachet_health transitions. Kept as
    a module-level function so tests can `monkeypatch.setattr(
    sp, "_emit_sachet_health_delta", fake)` and intercept the call
    — the base class's `emit_health_transition` looks this up at
    call time via `sys.modules`.

    REL-09: also forwards `* → degraded` and `degraded → healthy`
    transitions to Sentry with a stable fingerprint so a streak of
    outages groups into one issue (with hit-count + duration in the
    timeline). All other transitions are no-ops on the Sentry side.
    """
    _instance.default_emit_health_delta(prior_state, new_state, telemetry)
    try:
        from app.services.external_signals.sachet_sentry import (
            report_health_transition,
        )
        report_health_transition(prior_state, new_state, telemetry)
    except Exception:  # pragma: no cover — telemetry must never raise
        pass


# ── Test-only internals (kept for backward-compat imports) ───────
def _read_state() -> tuple[str, int]:
    return _instance._read_state()


# Exposed scheduler handle for tests that introspect liveness.
def _scheduler_handle():
    return _instance._scheduler


__all__ = [
    "SachetPrewarmer",
    "JITTER_BASE_S", "JITTER_RANGE_S",
    "TELEMETRY_NAMESPACE", "TELEMETRY_KEY", "TELEMETRY_TTL_S",
    "HISTORY_WINDOW", "STATE_KEY",
    "STATE_HEALTHY", "STATE_STALE", "STATE_DEGRADED", "STATE_UNKNOWN",
    "HEALTHY_MAX_AGE_S", "STALE_MAX_AGE_S",
    "FAILURE_RATE_THRESHOLD", "RECOVERY_READS_REQUIRED",
    "compute_next_interval_seconds", "compute_raw_state",
    "evaluate_state_transition",
    "run_prewarm_cycle", "get_prewarmer_telemetry", "get_health_state",
    "start_sachet_prewarm_scheduler", "stop_sachet_prewarm_scheduler",
]
