"""NISCH-011.1 — Operator Trust Calibration Layer ("Twin Trust Tile").

Pure-function trust evaluator. Synthesises existing observability
signals (NO new telemetry sources) into a single 3-state verdict
plus a reason-code taxonomy and trend direction.

ARCHITECTURAL CONTRACT (locked at module scope):

  * Trust state NEVER affects dispatch routing. The function
    `evaluate_trust(...)` and the endpoint that serves it are
    operator observability only. Tested by
    `test_dispatch_unaffected_by_trust_tile`.

  * Telemetry gaps NEVER auto-trigger LOW_TRUST. Missing inputs
    degrade to MEDIUM_TRUST with reason `telemetry_unavailable`.
    Tested by `test_telemetry_gaps_default_to_medium_trust`.

  * Divergence dampens confidence; it can DROP trust from HIGH
    to MEDIUM/LOW but can NEVER raise trust above the level
    indicated by other inputs. Tested by
    `test_divergence_cannot_elevate_trust`.

  * Warmup gate: MAE/precision-derived signals are IGNORED
    until `reconciled_predictions ≥ MAE_WARMUP_RECONCILED`. Locked
    at 168 (7 days × 24 reconciled/day). Below the gate, those
    inputs are treated as "unavailable" rather than "bad".

Locked thresholds (these define the trust decision matrix):

  | Input                          | HIGH ok          | MEDIUM red flag   | LOW red flag           |
  |--------------------------------|------------------|-------------------|------------------------|
  | forecast_divergence_index      | < 0.20           | 0.20 – 0.50       | ≥ 0.50                 |
  | reconciliation_lag_s           | < 3600           | 3600 – 14 400     | ≥ 14 400 (4 h)         |
  | critical_precision (gated)     | ≥ 0.70           | 0.50 – 0.70       | < 0.50                 |
  | false_escalation_rate (gated)  | < 0.10           | 0.10 – 0.25       | ≥ 0.25                 |
  | dlq_fallback_depth             | < 100            | 100 – 500         | ≥ 500                  |
  | unresolved_predictions         | < 100            | 100 – 500         | ≥ 500                  |

Any LOW red flag → LOW_TRUST. Any MEDIUM red flag → MEDIUM_TRUST.
All inputs in HIGH band AND warmup satisfied → HIGH_TRUST.

This precedence ordering is locked: LOW > MEDIUM > HIGH (worst
wins). A future PR that flips precedence MUST also change the
test suite — surfacing in CI.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Locked constants ─────────────────────────────────────────────

# Warmup gate (168 reconciled predictions = 7 days × 24/day).
# Below this, MAE-derived signals are treated as unavailable.
MAE_WARMUP_RECONCILED = 168

# Divergence bands.
DIVERGENCE_HIGH_OK = 0.20
DIVERGENCE_MEDIUM_RED = 0.50

# Reconciliation lag (seconds).
RECONCILIATION_LAG_HIGH_OK_S = 3600        # 1 h
RECONCILIATION_LAG_MEDIUM_RED_S = 14_400   # 4 h

# Critical precision bands.
PRECISION_HIGH_OK = 0.70
PRECISION_MEDIUM_RED = 0.50

# False escalation bands.
FALSE_ESCALATION_HIGH_OK = 0.10
FALSE_ESCALATION_MEDIUM_RED = 0.25

# DLQ fallback frequency.
DLQ_HIGH_OK = 100
DLQ_MEDIUM_RED = 500

# NISCH-012 — Motion-telemetry freshness band. MEDIUM red flag
# only — stale motion telemetry is observational, not a critical
# breach. Locked threshold: 30 min since last 60-s window.
MOTION_FRESHNESS_MEDIUM_RED_S = 1800

# Unresolved prediction count.
UNRESOLVED_HIGH_OK = 100
UNRESOLVED_MEDIUM_RED = 500


# ── Public enums ─────────────────────────────────────────────────

class TrustLevel(str, Enum):
    HIGH = "HIGH_TRUST"
    MEDIUM = "MEDIUM_TRUST"
    LOW = "LOW_TRUST"


class TrendDirection(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DEGRADING = "degrading"


# Locked reason-code taxonomy. Frozenset so a future PR adding a
# code surfaces in tests.
class ReasonCode(str, Enum):
    ALL_HEALTHY = "all_healthy"
    DIVERGENCE_ELEVATED = "divergence_elevated"
    INSUFFICIENT_RECONCILIATION_WINDOW = "insufficient_reconciliation_window"
    DELAYED_LEDGER_CONVERGENCE = "delayed_ledger_convergence"
    DLQ_FALLBACK_SPIKE = "dlq_fallback_spike"
    PREDICTION_PRECISION_DEGRADED = "prediction_precision_degraded"
    FALSE_ESCALATION_SPIKE = "false_escalation_spike"
    UNRESOLVED_BACKLOG = "unresolved_backlog"
    TELEMETRY_UNAVAILABLE = "telemetry_unavailable"
    # NISCH-012 — continuous motion-telemetry freshness signal.
    # Surfaces when no motion upload has landed in the last 30 min
    # (locked threshold). Severity = MEDIUM; never alone-pushes LOW.
    MOTION_TELEMETRY_STALE = "motion_telemetry_stale"


ALLOWED_REASON_CODES: frozenset[str] = frozenset(
    c.value for c in ReasonCode
)


# ── Result shape ─────────────────────────────────────────────────

@dataclass
class TrustResult:
    level: str
    reason_codes: list[str] = field(default_factory=list)
    trend: str = TrendDirection.STABLE.value
    inputs: dict = field(default_factory=dict)
    warmup_satisfied: bool = False


def _level_severity(level: str) -> int:
    """LOW > MEDIUM > HIGH (worst wins). Locked precedence.

    Also doubles as the severity ladder for `severity_delta`:
    `delta = new - old`, so HIGH → LOW (0 → 2) = +2 (worse),
    LOW → HIGH (2 → 0) = -2 (better). Zero means no change."""
    return {
        TrustLevel.LOW.value:    2,
        TrustLevel.MEDIUM.value: 1,
        TrustLevel.HIGH.value:   0,
    }.get(level, 1)


def severity_delta(*, current_level: str, previous_level: str | None) -> int:
    """Signed integer transition magnitude. Frontend tiles use this
    to animate transitions without parsing strings.

    Locked contract:
      * positive = worsening (HIGH→MEDIUM = +1, HIGH→LOW = +2)
      * negative = improving (LOW→HIGH = -2)
      * 0 = no change, OR no previous level (first call)
      * unknown level defaults to MEDIUM-rank so `severity_delta`
        gracefully reports 0 instead of raising."""
    if previous_level is None:
        return 0
    return _level_severity(current_level) - _level_severity(previous_level)


def _worse_of(a: str, b: str) -> str:
    return a if _level_severity(a) >= _level_severity(b) else b


def evaluate_trust(
    *,
    divergence_index: Optional[float],
    reconciliation_lag_s: Optional[float],
    reconciled_predictions: Optional[int],
    critical_precision: Optional[float],
    false_escalation_rate: Optional[float],
    dlq_depth: Optional[int],
    unresolved_count: Optional[int],
    motion_signal_freshness_s: Optional[float] = None,
) -> TrustResult:
    """Pure-function trust evaluator. Deterministic — same inputs
    always produce the same output.

    Fail-safe contract (locked by `test_telemetry_gaps_default_*`):
      * If EVERY non-warmup input is None → MEDIUM_TRUST with
        `telemetry_unavailable`. Never LOW.
      * If SOME inputs are None → those signals contribute neither
        red nor green flags; the verdict reflects only the
        signals we did receive.

    Warmup gate (locked by `test_warmup_gate_enforced_*`):
      * `critical_precision` and `false_escalation_rate` are
        IGNORED until `reconciled_predictions ≥ 168`. Below the
        gate, the verdict carries `insufficient_reconciliation_window`
        as a MEDIUM signal (never LOW)."""
    inputs = {
        "divergence_index":         divergence_index,
        "reconciliation_lag_s":     reconciliation_lag_s,
        "reconciled_predictions":   reconciled_predictions,
        "critical_precision":       critical_precision,
        "false_escalation_rate":    false_escalation_rate,
        "dlq_depth":                dlq_depth,
        "unresolved_count":         unresolved_count,
        "motion_signal_freshness_s": motion_signal_freshness_s,
    }

    # Count signals that actually arrived (excluding the warmup
    # counter — that's a meta-input).
    received = sum(
        1 for k, v in inputs.items()
        if k != "reconciled_predictions" and v is not None
    )
    if received == 0:
        logger.info(
            "trust_telemetry_unavailable",
            extra={"event": "trust_telemetry_unavailable"},
        )
        return TrustResult(
            level=TrustLevel.MEDIUM.value,
            reason_codes=[ReasonCode.TELEMETRY_UNAVAILABLE.value],
            inputs=inputs,
        )

    warmup_satisfied = (
        reconciled_predictions is not None
        and int(reconciled_predictions) >= MAE_WARMUP_RECONCILED
    )

    verdict = TrustLevel.HIGH.value
    reasons: list[str] = []

    # ── divergence ────────────────────────────────────────────
    if divergence_index is not None:
        if float(divergence_index) >= DIVERGENCE_MEDIUM_RED:
            verdict = _worse_of(verdict, TrustLevel.LOW.value)
            reasons.append(ReasonCode.DIVERGENCE_ELEVATED.value)
        elif float(divergence_index) >= DIVERGENCE_HIGH_OK:
            verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
            reasons.append(ReasonCode.DIVERGENCE_ELEVATED.value)

    # ── reconciliation lag ────────────────────────────────────
    if reconciliation_lag_s is not None:
        lag = float(reconciliation_lag_s)
        if lag >= RECONCILIATION_LAG_MEDIUM_RED_S:
            verdict = _worse_of(verdict, TrustLevel.LOW.value)
            reasons.append(ReasonCode.DELAYED_LEDGER_CONVERGENCE.value)
        elif lag >= RECONCILIATION_LAG_HIGH_OK_S:
            verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
            reasons.append(ReasonCode.DELAYED_LEDGER_CONVERGENCE.value)

    # ── warmup gate ───────────────────────────────────────────
    if not warmup_satisfied:
        # Insufficient reconciled data — MAE-derived signals are
        # treated as unavailable. Verdict pinned at MEDIUM at most;
        # cannot become LOW just from being warm-starting.
        verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
        reasons.append(ReasonCode.INSUFFICIENT_RECONCILIATION_WINDOW.value)
    else:
        # ── critical precision ───────────────────────────────
        if critical_precision is not None:
            cp = float(critical_precision)
            if cp < PRECISION_MEDIUM_RED:
                verdict = _worse_of(verdict, TrustLevel.LOW.value)
                reasons.append(ReasonCode.PREDICTION_PRECISION_DEGRADED.value)
            elif cp < PRECISION_HIGH_OK:
                verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
                reasons.append(ReasonCode.PREDICTION_PRECISION_DEGRADED.value)

        # ── false escalation rate ────────────────────────────
        if false_escalation_rate is not None:
            fe = float(false_escalation_rate)
            if fe >= FALSE_ESCALATION_MEDIUM_RED:
                verdict = _worse_of(verdict, TrustLevel.LOW.value)
                reasons.append(ReasonCode.FALSE_ESCALATION_SPIKE.value)
            elif fe >= FALSE_ESCALATION_HIGH_OK:
                verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
                reasons.append(ReasonCode.FALSE_ESCALATION_SPIKE.value)

    # ── DLQ depth ─────────────────────────────────────────────
    if dlq_depth is not None:
        d = int(dlq_depth)
        if d >= DLQ_MEDIUM_RED:
            verdict = _worse_of(verdict, TrustLevel.LOW.value)
            reasons.append(ReasonCode.DLQ_FALLBACK_SPIKE.value)
        elif d >= DLQ_HIGH_OK:
            verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
            reasons.append(ReasonCode.DLQ_FALLBACK_SPIKE.value)

    # ── unresolved predictions ───────────────────────────────
    if unresolved_count is not None:
        u = int(unresolved_count)
        if u >= UNRESOLVED_MEDIUM_RED:
            verdict = _worse_of(verdict, TrustLevel.LOW.value)
            reasons.append(ReasonCode.UNRESOLVED_BACKLOG.value)
        elif u >= UNRESOLVED_HIGH_OK:
            verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
            reasons.append(ReasonCode.UNRESOLVED_BACKLOG.value)

    # ── motion telemetry freshness (NISCH-012) ───────────────
    # Stale motion telemetry is observational — surfaces as MEDIUM
    # only, NEVER LOW. The Risk Engine can fall back to GPS-only
    # behaviour without the continuous motion dimension.
    if motion_signal_freshness_s is not None:
        if float(motion_signal_freshness_s) >= MOTION_FRESHNESS_MEDIUM_RED_S:
            verdict = _worse_of(verdict, TrustLevel.MEDIUM.value)
            reasons.append(ReasonCode.MOTION_TELEMETRY_STALE.value)

    if not reasons:
        reasons = [ReasonCode.ALL_HEALTHY.value]

    # Dedup while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    return TrustResult(
        level=verdict,
        reason_codes=deduped,
        inputs=inputs,
        warmup_satisfied=warmup_satisfied,
    )


def derive_trend(
    *, current_level: str, previous_level: Optional[str],
) -> str:
    """Trend = comparison of current vs cached previous level.
    Pure function; the API endpoint owns the caching."""
    if previous_level is None or previous_level not in (
        TrustLevel.HIGH.value, TrustLevel.MEDIUM.value, TrustLevel.LOW.value,
    ):
        return TrendDirection.STABLE.value
    cur = _level_severity(current_level)
    prev = _level_severity(previous_level)
    if cur < prev:
        return TrendDirection.IMPROVING.value
    if cur > prev:
        return TrendDirection.DEGRADING.value
    return TrendDirection.STABLE.value


__all__ = [
    "TrustLevel", "TrendDirection", "ReasonCode",
    "ALLOWED_REASON_CODES",
    "TrustResult",
    "evaluate_trust", "derive_trend", "severity_delta",
    # Thresholds (exported for tests + admin tooling)
    "MAE_WARMUP_RECONCILED",
    "DIVERGENCE_HIGH_OK", "DIVERGENCE_MEDIUM_RED",
    "RECONCILIATION_LAG_HIGH_OK_S", "RECONCILIATION_LAG_MEDIUM_RED_S",
    "PRECISION_HIGH_OK", "PRECISION_MEDIUM_RED",
    "FALSE_ESCALATION_HIGH_OK", "FALSE_ESCALATION_MEDIUM_RED",
    "DLQ_HIGH_OK", "DLQ_MEDIUM_RED",
    "UNRESOLVED_HIGH_OK", "UNRESOLVED_MEDIUM_RED",
    "MOTION_FRESHNESS_MEDIUM_RED_S",
]
