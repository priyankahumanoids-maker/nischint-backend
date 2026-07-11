"""NISCH-011 — Locked behavioural taxonomy.

5-value enum. Strict — any writer that constructs an
`anomaly` row MUST use one of these constants, never a raw
string. The detector's classifier returns one of these and
nothing else; the test suite locks that contract.

Severity ladder (locked, used by `severity_rank()`):

    baseline                  0
    drift                     1
    irregular                 2
    elevated_behavioral_risk  3
    critical_behavioral_shift 4

Higher = more anomalous. `critical_behavioral_shift` is the ONLY
class that — when corroborated by zone risk — is permitted to
influence dispatch weighting. All other classes are observational.
"""
from __future__ import annotations

from enum import Enum


class DeviationClass(str, Enum):
    BASELINE = "baseline"
    DRIFT = "drift"
    IRREGULAR = "irregular"
    ELEVATED = "elevated_behavioral_risk"
    CRITICAL = "critical_behavioral_shift"


# Frozen for fast membership tests in the writer boundary.
ALLOWED_DEVIATION_CLASSES: frozenset[str] = frozenset(
    {c.value for c in DeviationClass}
)


_RANK: dict[str, int] = {
    DeviationClass.BASELINE.value:  0,
    DeviationClass.DRIFT.value:     1,
    DeviationClass.IRREGULAR.value: 2,
    DeviationClass.ELEVATED.value:  3,
    DeviationClass.CRITICAL.value:  4,
}


def severity_rank(deviation_class: str) -> int:
    """Lookup that defaults to 0 for unknowns. Defence in depth —
    a stringly-typed row that slipped past the writer boundary
    should sort to baseline (least anomalous) rather than mask
    as something stronger."""
    return _RANK.get(deviation_class, 0)


def classify_from_z(
    z_score: float,
    *,
    drift_threshold: float = 1.5,
    irregular_threshold: float = 2.0,
    elevated_threshold: float = 2.5,
    critical_threshold: float = 3.5,
) -> str:
    """Deterministic |z| → class mapping. Locked at fixed
    thresholds; bumping any of these must bump
    `ANOMALY_PIPELINE_VERSION`.

    Boundaries are inclusive on the upper side so the operator UI
    can describe a `z=2.5` reading as `elevated`, not as
    `irregular`."""
    az = abs(float(z_score))
    if az >= critical_threshold:
        return DeviationClass.CRITICAL.value
    if az >= elevated_threshold:
        return DeviationClass.ELEVATED.value
    if az >= irregular_threshold:
        return DeviationClass.IRREGULAR.value
    if az >= drift_threshold:
        return DeviationClass.DRIFT.value
    return DeviationClass.BASELINE.value


__all__ = [
    "DeviationClass",
    "ALLOWED_DEVIATION_CLASSES",
    "severity_rank",
    "classify_from_z",
]
