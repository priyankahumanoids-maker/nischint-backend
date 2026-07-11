"""NISCH-010 — Predictive Risk Engine package.

Public surface:
  * `predictor.predict(...)` — single-zone risk forecast
  * `predictor.forecast_zone_24h(...)` — 24 h hourly forecast
  * `forecasters` — Phase 1 model implementations
  * `prewarmer.RiskPredictionPrewarmer` — ProviderPrewarmer subclass
  * `reconciler.reconcile_outcomes(...)` — backfills `actual_outcome`

The whole engine is a Phase-1 build per the locked product policy:
explainable, deterministic, debuggable models only. Phase 2 (LSTM,
Temporal Transformers, GNNs) is gated on 30+ days of stable
prediction-ledger data.
"""

# Component model identifier. Bumped when a forecaster's
# math changes.
MODEL_VERSION = "phase1-ewma-bayes-2026.02"

# Orchestration / classification pipeline identifier. Bumped when
# the `predict()` flow, classification thresholds, or feature
# composition changes — independently of the underlying models.
PIPELINE_VERSION = "pipeline-2026.02.1"

# Reconciler identifier. Bumped when the outcome-resolution
# algorithm changes so historical accuracy reports stay grouped
# by the algorithm that produced them.
OUTCOME_RESOLUTION_VERSION = "outcome-2026.02.1"

__all__ = [
    "MODEL_VERSION", "PIPELINE_VERSION", "OUTCOME_RESOLUTION_VERSION",
]
