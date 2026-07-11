"""NISCH-011 — Fusion Engine.

`fused_risk = behavioral_anomaly × zone_risk × temporal_context
              × sensor_confidence`

then DAMPENED by the forecast-divergence confidence weight.

Locked invariants (per product brief, enforced by tests):

  1. Multiplicative fusion, not additive. A zone with high
     behavioural anomaly AND high zone risk fuses dramatically
     higher than either alone — the cross-product is the
     signal.
  2. `temporal_context` and `sensor_confidence` are bounded
     [0, 1] modulators. A 0 in either zeroes the fused output —
     reflects "no temporal coherence" or "sensors don't trust
     this signal" honestly.
  3. The divergence weight ONLY dampens — never amplifies.
     Locked by `fuse()` multiplying with `divergence_weight`
     after clamping it to [0, 1].
  4. `critical_behavioral_shift` WITHOUT corroborating zone
     risk DOES NOT influence dispatch — surfaced as
     `dispatch_influence=False` by `should_influence_dispatch()`.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.behavioral.taxonomy import DeviationClass


# Minimum zone-risk required before a CRITICAL behavioural shift
# is allowed to influence dispatch weighting. Locked per product
# brief — the corroborating-evidence gate.
DISPATCH_INFLUENCE_ZONE_RISK_THRESHOLD = 0.6


@dataclass
class FusionResult:
    fused_risk: float
    dispatch_influence: bool
    components: dict


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def fuse(
    *,
    behavioral_anomaly: float,
    zone_risk: float,
    temporal_context: float = 1.0,
    sensor_confidence: float = 1.0,
    divergence_weight: float = 1.0,
) -> float:
    """Deterministic fused-risk math. Pure function — tests can
    pin every quadrant of the lattice."""
    ba = _clamp01(behavioral_anomaly)
    zr = _clamp01(zone_risk)
    tc = _clamp01(temporal_context)
    sc = _clamp01(sensor_confidence)
    dw = _clamp01(divergence_weight)
    return ba * zr * tc * sc * dw


def should_influence_dispatch(
    *,
    deviation_class: str,
    zone_risk: float,
    zone_risk_threshold: float = DISPATCH_INFLUENCE_ZONE_RISK_THRESHOLD,
) -> bool:
    """Gate for whether the anomaly is allowed to influence
    dispatch weighting. ONLY `critical_behavioral_shift` AND
    zone_risk ≥ threshold passes.

    This is the locked safety contract — a single test asserts
    it for every taxonomy value × zone-risk band combination."""
    if deviation_class != DeviationClass.CRITICAL.value:
        return False
    return float(zone_risk) >= float(zone_risk_threshold)


def fuse_with_explanation(
    *,
    behavioral_anomaly: float,
    zone_risk: float,
    deviation_class: str,
    temporal_context: float = 1.0,
    sensor_confidence: float = 1.0,
    divergence_weight: float = 1.0,
) -> FusionResult:
    """Convenience wrapper — returns the fused number, the
    dispatch-influence verdict, and the component breakdown so
    the operator UI / explanation_snapshot can reproduce the
    arithmetic."""
    fused = fuse(
        behavioral_anomaly=behavioral_anomaly,
        zone_risk=zone_risk,
        temporal_context=temporal_context,
        sensor_confidence=sensor_confidence,
        divergence_weight=divergence_weight,
    )
    influence = should_influence_dispatch(
        deviation_class=deviation_class, zone_risk=zone_risk,
    )
    return FusionResult(
        fused_risk=fused,
        dispatch_influence=influence,
        components={
            "behavioral_anomaly": _clamp01(behavioral_anomaly),
            "zone_risk":          _clamp01(zone_risk),
            "temporal_context":   _clamp01(temporal_context),
            "sensor_confidence":  _clamp01(sensor_confidence),
            "divergence_weight":  _clamp01(divergence_weight),
            "deviation_class":    deviation_class,
        },
    )


__all__ = [
    "FusionResult", "fuse", "fuse_with_explanation",
    "should_influence_dispatch",
    "DISPATCH_INFLUENCE_ZONE_RISK_THRESHOLD",
]
