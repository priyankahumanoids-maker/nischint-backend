"""NISCH-011 — Forecast Divergence Engine.

Measures disagreement across the three NISCH-010 forecasters
(EWMA, Bayesian, Prophet stub). High disagreement signals:

  * environmental instability the operator should see
  * model uncertainty → fused-risk confidence DAMPENING

Locked invariant (per product brief):
  Divergence DAMPENS the fused risk; it never amplifies and is
  never an independent alert trigger. This file owns the math
  that enforces that contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev
from typing import Iterable


# Max stddev we expect across three forecaster votes that all live
# in [0, 1]. Above 0.3 → models are wildly disagreeing.
_NORMALISER = 0.3


@dataclass
class DivergenceResult:
    index: float            # [0, 1] — 0 = perfect agreement
    confidence_weight: float  # [0, 1] — 1.0 = full trust
    contributing_votes: int


def compute_divergence(
    forecast_risks: Iterable[float],
) -> DivergenceResult:
    """Convert a set of forecaster risks into a divergence index
    and the resulting confidence weight applied downstream.

    Locked semantics:
      * < 2 votes → no divergence signal; confidence_weight=1.0,
        index=0. (Can't measure disagreement with one opinion.)
      * normalised stddev → index ∈ [0, 1].
      * confidence_weight = 1 - index (so divergence DROPS the
        weight, never raises it). Floored at 0.2 so even a
        completely disagreeing fleet still contributes 20 % of
        its raw signal — operators still see SOMETHING."""
    votes = [float(x) for x in forecast_risks
             if x is not None]
    n = len(votes)
    if n < 2:
        return DivergenceResult(
            index=0.0, confidence_weight=1.0, contributing_votes=n,
        )
    sd = pstdev(votes)
    index = max(0.0, min(1.0, sd / _NORMALISER))
    weight = max(0.2, 1.0 - index)
    return DivergenceResult(
        index=index, confidence_weight=weight, contributing_votes=n,
    )


__all__ = [
    "DivergenceResult", "compute_divergence",
]
