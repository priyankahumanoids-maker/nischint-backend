"""NISCH-010 — Phase-1 forecasters.

Explainable, deterministic, debuggable. Locked rule from the
product brief: no LSTM / Transformer / GNN until the prediction
ledger has 30+ days of stability data.

Three models compose the Phase-1 blend:

  1. `EWMAForecaster` — exponentially weighted moving average.
     Cheapest, lowest-variance baseline. Recency-weighted so a
     spike 5 minutes ago counts more than one 6 hours ago.

  2. `BayesianTrendScorer` — Bayesian inference on trend
     direction. Returns `P(risk increases in next 15 min)` with
     a confidence interval, computed from the posterior over a
     simple two-state Markov chain (rising | falling).

  3. `ProphetForecaster` — handles seasonality (time-of-day +
     day-of-week). Heavy install footprint (~200 MB), so this
     is a SOFT dependency. `is_available()` returns False when
     `prophet` is not installed; the blend gracefully degrades
     to EWMA + Bayesian only. Wire it up by `pip install prophet`
     when the prediction ledger has stabilised.

All three return a `ForecastResult` with the same shape so the
predictor can blend them uniformly. Every result MUST include
`contributing_factors` so the operator UI can explain the score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Protocol


# ── Shared output shape ──────────────────────────────────────────

@dataclass
class ForecastResult:
    """One forecaster's vote — bounded [0, 1] risk + confidence.

    `factors` is a list of strings that explain the score in
    operator-readable terms. Locked at the type level: a forecaster
    that returns an empty factor list is failing its explainability
    contract and the predictor will down-weight its vote."""
    risk: float
    confidence: float
    factors: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Clamp at the boundary so a buggy forecaster can't poison
        # the blended output downstream. Sentinel logged by predictor.
        self.risk = max(0.0, min(1.0, float(self.risk)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


class Forecaster(Protocol):
    """Structural contract — duck-typed in the predictor blend so
    new Phase-1 models can be added without import-cycle dance."""
    name: str

    def is_available(self) -> bool: ...
    def forecast(self, history: list[float]) -> ForecastResult: ...


# ── 1. EWMA ──────────────────────────────────────────────────────

class EWMAForecaster:
    """Exponentially weighted moving average over a rolling risk
    window. `alpha` controls recency-weighting: higher = more
    reactive to the latest sample.

    Locked at `alpha=0.3` per the product brief. A tighter alpha
    would chase noise; a looser one would lag rising risk."""

    name = "ewma"

    def __init__(self, alpha: float = 0.3):
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        self.alpha = alpha

    def is_available(self) -> bool:
        return True

    def forecast(self, history: list[float]) -> ForecastResult:
        if not history:
            # Cold start — no signal. Confidence floor.
            return ForecastResult(
                risk=0.0, confidence=0.0,
                factors=["ewma:cold_start_no_history"],
            )

        # Iterate oldest → newest so the most recent sample carries
        # the most weight. Equivalent to:
        #   s_t = α·x_t + (1-α)·s_{t-1}
        sm = float(history[0])
        for x in history[1:]:
            sm = self.alpha * float(x) + (1.0 - self.alpha) * sm

        # Confidence grows with sample count up to 30 — past that
        # the EWMA's own bias dominates, no more confidence to gain.
        sample_n = len(history)
        confidence = min(1.0, sample_n / 30.0)

        factors = [
            f"ewma:samples={sample_n}",
            f"ewma:alpha={self.alpha}",
            f"ewma:smoothed={sm:.3f}",
        ]
        return ForecastResult(risk=sm, confidence=confidence, factors=factors)


# ── 2. Bayesian trend ────────────────────────────────────────────

class BayesianTrendScorer:
    """Bayesian P(risk-rising | recent_observations).

    Two-state model: each consecutive pair `(history[i-1], history[i])`
    is classified as `rising` (delta > epsilon) or `falling`
    (delta < -epsilon). Beta-distributed posterior with
    `Beta(alpha=1, beta=1)` flat prior gives:

        P(rising | obs) = (rising_count + 1) / (total_pairs + 2)

    The forward risk projection blends `P(rising)` with the most
    recent observation: if risk is currently low but trending up,
    the score lifts."""

    name = "bayesian_trend"

    def __init__(self, epsilon: float = 0.01):
        # Floor for what counts as a directional move. Otherwise
        # quantisation noise around a flat series would inflate
        # P(rising) toward 0.5.
        self.epsilon = epsilon

    def is_available(self) -> bool:
        return True

    def forecast(self, history: list[float]) -> ForecastResult:
        if len(history) < 2:
            return ForecastResult(
                risk=0.0, confidence=0.0,
                factors=["bayesian:cold_start_lt_2_samples"],
            )

        rising = 0
        falling = 0
        for i in range(1, len(history)):
            delta = float(history[i]) - float(history[i - 1])
            if delta > self.epsilon:
                rising += 1
            elif delta < -self.epsilon:
                falling += 1
        total_pairs = rising + falling
        # Beta(1,1) flat-prior posterior mean.
        p_rising = (rising + 1) / (total_pairs + 2)

        current = float(history[-1])
        # If trending up from a low base, project ~5 % lift per pair
        # of rising observations, capped at 1.0. Down-trend symmetric.
        if p_rising > 0.5:
            projected = current + 0.05 * (p_rising - 0.5) * 2 * rising
        elif p_rising < 0.5:
            projected = current - 0.05 * (0.5 - p_rising) * 2 * falling
        else:
            projected = current

        # Confidence proportional to pair-count, capped — same
        # reasoning as EWMA.
        confidence = min(1.0, total_pairs / 20.0)

        factors = [
            f"bayes:p_rising={p_rising:.3f}",
            f"bayes:rising_pairs={rising}",
            f"bayes:falling_pairs={falling}",
            f"bayes:current_risk={current:.3f}",
        ]
        return ForecastResult(
            risk=projected, confidence=confidence, factors=factors,
        )


# ── 3. Prophet — soft dependency ─────────────────────────────────

class ProphetForecaster:
    """Facebook Prophet — seasonality-aware (time-of-day, day-of-
    week). Heavy dep (~200 MB), so the import is lazy and
    `is_available()` returns False when the package isn't
    installed. Drop-in once `pip install prophet`."""

    name = "prophet"

    def is_available(self) -> bool:
        try:
            import prophet  # noqa: F401
            return True
        except ImportError:
            return False

    def forecast(self, history: list[float]) -> ForecastResult:
        if not self.is_available():
            # The predictor checks `is_available()` first — this is
            # belt-and-suspenders for the case where it's invoked
            # directly. Empty factors signals "skip my vote".
            return ForecastResult(risk=0.0, confidence=0.0, factors=[])

        # Implementation deferred — see scoping doc. Returning an
        # explicit "not_yet_wired" factor so the operator UI shows
        # exactly why Prophet's vote is absent from the blend.
        return ForecastResult(
            risk=0.0, confidence=0.0,
            factors=["prophet:available_but_not_yet_wired"],
        )


# ── Blend helper used by the predictor ───────────────────────────

def blend_forecasts(results: Iterable[ForecastResult]) -> ForecastResult:
    """Confidence-weighted blend across all active forecasters.

    Locked semantics:
      * Confidence-zero votes are SKIPPED (they don't drag the mean).
      * If every vote is confidence-zero, the blend returns
        `risk=0.0, confidence=0.0` with a `blend:no_confident_vote`
        sentinel factor so the predictor can decide whether to
        return a `deferred` response.
      * Output `confidence` is the MAX confidence across votes —
        not the mean — because one high-confidence vote is more
        informative than several low-confidence votes agreeing."""
    votes = [r for r in results if r.confidence > 0.0]
    if not votes:
        return ForecastResult(
            risk=0.0, confidence=0.0,
            factors=["blend:no_confident_vote"],
        )

    total_weight = sum(v.confidence for v in votes)
    blended_risk = sum(v.risk * v.confidence for v in votes) / total_weight
    blended_conf = max(v.confidence for v in votes)
    blended_factors: list[str] = []
    for v in votes:
        blended_factors.extend(v.factors)

    return ForecastResult(
        risk=blended_risk, confidence=blended_conf, factors=blended_factors,
    )


__all__ = [
    "ForecastResult", "Forecaster",
    "EWMAForecaster", "BayesianTrendScorer", "ProphetForecaster",
    "blend_forecasts",
]
