"""NISCH-011.2 — Operator Trust Badge surface.

The thinnest possible projection of `evaluate_trust(...)` — three
public fields:

  * `level`   ∈ {HIGH_TRUST, MEDIUM_TRUST, LOW_TRUST}
  * `color`   ∈ {green, yellow, red}
  * `reason`  ∈ locked reason-code taxonomy

Purpose: a cheap surface for 5–15 s polling by:
  * operator dashboards
  * mobile widgets
  * external status pages
  * future SOC panels

LOCKED CONTRACTS (per the locked product brief, all tested):

  1. Endpoint NEVER influences dispatch. No imports from this
     module into `safety_incident_engine.py` or `alert_trigger.py`.
     The cross-module audit test in test_behavioral_trust.py
     remains green.

  2. Any failure path → MEDIUM_TRUST + yellow + telemetry_unavailable.
     NEVER LOW_TRUST. The whole module is wrapped in a single
     top-level try/except in `build_badge`.

  3. The shape is exactly three fields. No raw metrics. No
     anomaly payloads. No PII. Locks the operator-facing contract.

  4. Reason priority is locked here — the badge picks ONE code
     from the evaluator's `reason_codes` list using the priority
     ladder below. Operators see the most actionable signal first.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Locked level → color mapping. The three-color contract is the
# entire public-facing API of this layer.
_LEVEL_COLOR: dict[str, str] = {
    "HIGH_TRUST":   "green",
    "MEDIUM_TRUST": "yellow",
    "LOW_TRUST":    "red",
}


# Reason-priority ladder (highest first). Picked to surface the
# MOST OPERATIONALLY ACTIONABLE signal — the operator should see
# "delayed reconciliation" over "elevated divergence" because the
# former is acute, the latter chronic.
#
# Changing this ladder is a public-contract change; the test
# `test_badge_reason_priority_ladder` locks the exact ordering.
REASON_PRIORITY: tuple[str, ...] = (
    # System-wide telemetry blackout — worst possible state.
    "telemetry_unavailable",
    # Data loss is happening NOW (compensating action firing).
    "dlq_fallback_spike",
    # Reconciliation pipeline broken — accuracy reports go stale.
    "delayed_ledger_convergence",
    # Model is misbehaving on the critical path.
    "false_escalation_spike",
    # Model accuracy down (gated, so only seen post-warmup).
    "prediction_precision_degraded",
    # Forecasters disagree — environmental volatility signal.
    "divergence_elevated",
    # Queue growing — latent capacity / reconciliation issue.
    "unresolved_backlog",
    # Continuous motion stream gone stale — Risk Engine loses the
    # Motion term of the fusion formula. Falls back to GPS-only.
    "motion_telemetry_stale",
    # Warm-up state (cold-start ledger).
    "insufficient_reconciliation_window",
    # All good — no red flags whatsoever.
    "all_healthy",
)


def pick_priority_reason(reason_codes: list[str] | None) -> str:
    """Walk REASON_PRIORITY and return the first reason that
    appears in the evaluator's output. Empty / unknown input →
    `telemetry_unavailable` (fail-safe)."""
    if not reason_codes:
        return "telemetry_unavailable"
    s = set(reason_codes)
    for r in REASON_PRIORITY:
        if r in s:
            return r
    # Unknown code defaulted up to telemetry_unavailable to keep
    # fail-safe semantics consistent.
    return "telemetry_unavailable"


def level_to_color(level: str) -> str:
    """Deterministic level → color. Unknown levels default to
    `yellow` (the MEDIUM color) — same fail-safe direction as the
    rest of the trust layer."""
    return _LEVEL_COLOR.get(level, "yellow")


# Sentinel fail-safe badge. Returned from `build_badge_fallback`
# in every degradation path so callers never branch on shape.
FALLBACK_BADGE: dict[str, str] = {
    "level":  "MEDIUM_TRUST",
    "color":  "yellow",
    "reason": "telemetry_unavailable",
}


def build_badge_fallback() -> dict[str, str]:
    """Always-safe badge shape. Pure function — no I/O. Used by
    `get_badge()` on every failure path."""
    return dict(FALLBACK_BADGE)


# Redis cache key — distinct from the `:trust:prev_level` key
# used by the full trust endpoint for trend derivation.
_BADGE_CACHE_KEY = "nischint:behavioral:trust:badge"
BADGE_CACHE_TTL_S = 10              # 5–15 s band per the spec


def _cache_read() -> Optional[dict[str, str]]:
    """Best-effort cache read. Returns None on any Redis failure
    so the caller falls through to live evaluation."""
    try:
        from app.services import redis_service
        r = redis_service._get_client()
        if r is None:
            return None
        raw = r.get(_BADGE_CACHE_KEY)
        if not raw:
            return None
        import json
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        decoded = json.loads(raw)
        # Defensive shape check — never return a partial badge.
        if {"level", "color", "reason"} <= set(decoded):
            return {k: decoded[k] for k in ("level", "color", "reason")}
        return None
    except Exception:  # noqa: BLE001
        return None


def _cache_write(badge: dict[str, str]) -> None:
    """Best-effort cache write. Failure is a no-op — the badge
    will be live-computed on the next call."""
    try:
        from app.services import redis_service
        import json
        r = redis_service._get_client()
        if r is None:
            return
        r.set(
            _BADGE_CACHE_KEY,
            json.dumps(badge, separators=(",", ":")),
            ex=BADGE_CACHE_TTL_S,
        )
    except Exception:  # noqa: BLE001
        return


__all__ = [
    "REASON_PRIORITY",
    "FALLBACK_BADGE",
    "BADGE_CACHE_TTL_S",
    "pick_priority_reason",
    "level_to_color",
    "build_badge_fallback",
    "_cache_read",
    "_cache_write",
]
