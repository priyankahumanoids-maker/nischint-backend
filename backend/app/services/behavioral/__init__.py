"""NISCH-011 — Behavioral Baseline + Digital Twin engine.

Public surface:
  * `taxonomy.DeviationClass` — locked 5-value enum
  * `temporal.TemporalMemory` — 5/30-min Redis + 6/24h Postgres
  * `baseline.BehavioralBaselineBuilder` — 14-day learner
  * `detector.BehavioralAnomalyDetector` — Z-score detector
  * `divergence.ForecastDivergenceEngine` — disagreement → confidence
  * `fusion.FusionEngine` — fused_risk = anomaly × zone × temporal
    × sensor_confidence, dampened by divergence
  * `prewarmer.BehavioralBaselinePrewarmer` — 1h cadence
  * `dlq.append_anomaly_ledger` — fail-safe append-only DLQ

Phase 1 locked rule (per product brief, see ROADMAP.md):
  * No transformers, no LSTMs, no autonomous retraining.
  * Detector emits anomalies; ONLY `critical_behavioral_shift`
    WITH corroborating zone risk influences dispatch weighting.
"""

# 14-day window — locked. Bumped only when the learner algorithm
# changes (e.g. switches to weighted decay or Kalman smoothing).
BASELINE_VERSION = "behavioral-baseline-2026.02.1"

# Anomaly detection pipeline version. Independent of the baseline
# learner. Bumped when feature composition or Z-score thresholds
# change.
ANOMALY_PIPELINE_VERSION = "behavioral-anomaly-2026.02.1"

# Reconciler version — distinct so historical reports group by
# the reconciliation algorithm that produced their state.
ANOMALY_RECONCILIATION_VERSION = "behavioral-reconcile-2026.02.1"

__all__ = [
    "BASELINE_VERSION",
    "ANOMALY_PIPELINE_VERSION",
    "ANOMALY_RECONCILIATION_VERSION",
]
