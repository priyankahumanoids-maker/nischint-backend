"""NISCH-010 — Predictor orchestrator.

Wires the Phase-1 forecasters into a single `predict()` call,
writes the result to the `risk_predictions` ledger, and exposes
the snapshot to the operator UI. The ledger row is authoritative
— callers read predictions back from the table, not from in-
memory state, so a process restart never loses a prediction.

Feature build:
  * 30-day risk history per zone, hourly buckets — sourced from
    `safety_incidents` aggregated by `zone_id + hour_bucket`.
  * Current external-signal modifier from `fetch_all_signals`
    (Phase 2 — placeholder factor only in Phase 1).

Feature hash:
  Every prediction stores SHA-256 of the feature vector so a
  future model rollback / replay can regenerate the exact same
  inputs deterministically. Reproducibility lock.

Derived classification:
  `prediction_class` ∈ {stable, rising, volatile, critical_escalation}
  is derived from (predicted_risk, volatility, trend slope) at
  predict-time and persisted alongside the prediction so reports
  never have to recompute it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk_prediction import RiskPrediction
from app.services.risk_prediction import MODEL_VERSION, PIPELINE_VERSION
from app.services.risk_prediction.forecasters import (
    BayesianTrendScorer, EWMAForecaster, ProphetForecaster,
    blend_forecasts,
)

logger = logging.getLogger(__name__)

# Locked at the operational constants surface for visibility.
ZONE_HISTORY_DAYS = 30
ZONE_HISTORY_BUCKET_MIN = 60   # 1-hour buckets
PREDICTION_HORIZONS_MIN = (15, 60)
MIN_HISTORY_FOR_CONFIDENT = 5  # below this, return deferred shape

# Classification thresholds — locked so reports stay comparable
# across deploys. Any change here should bump
# `PIPELINE_VERSION` so historical accuracy reports can group by
# the algorithm that produced them.
CRITICAL_RISK_THRESHOLD = 0.75
HIGH_VOLATILITY_THRESHOLD = 0.15
RISING_SLOPE_THRESHOLD = 0.02


# Cached forecaster instances — pure-Python objects, safe to
# share across coroutines. Avoids re-allocating on every call.
_EWMA = EWMAForecaster(alpha=0.3)
_BAYES = BayesianTrendScorer(epsilon=0.01)
_PROPHET = ProphetForecaster()


def _feature_hash(features: dict) -> str:
    """SHA-256 over a canonical JSON of the feature dict. Locks
    reproducibility for future model rollback / replay analysis."""
    payload = json.dumps(features, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _trend_slope(history: list[float], tail: int = 5) -> float:
    """Average per-sample slope across the last `tail` samples.
    Positive = trending up, negative = trending down."""
    if len(history) < 2:
        return 0.0
    window = history[-tail:] if len(history) >= tail else history
    diffs = [window[i] - window[i - 1] for i in range(1, len(window))]
    return sum(diffs) / max(1, len(diffs))


def classify_prediction(
    predicted_risk: float, volatility: float, slope: float,
) -> str:
    """Derive `prediction_class` from the blended forecast +
    volatility + trend slope. Locked at module scope so tests can
    pin every quadrant of the truth table.

    Ordering matters: `critical_escalation` wins over `volatile`
    (a critical zone that's also volatile is reported as
    critical), and `volatile` wins over `rising` (because high
    volatility carries more operator information than direction
    alone)."""
    if predicted_risk >= CRITICAL_RISK_THRESHOLD:
        return "critical_escalation"
    if volatility >= HIGH_VOLATILITY_THRESHOLD:
        return "volatile"
    if slope >= RISING_SLOPE_THRESHOLD:
        return "rising"
    return "stable"


async def _zone_risk_history(
    session: AsyncSession,
    zone_id: Optional[uuid.UUID],
    days: int = ZONE_HISTORY_DAYS,
) -> list[float]:
    """Fetch hourly-bucketed risk history for a zone over the last
    `days` days. Returns oldest → newest so the forecasters see a
    chronological sequence."""
    if zone_id is None:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    q = text("""
        SELECT date_trunc('hour', created_at) AS bucket,
               AVG(confidence)::float            AS avg_risk
          FROM safety_incidents
         WHERE created_at >= :cutoff
           AND (external_signals->>'zone_id') = :zone_id
         GROUP BY bucket
         ORDER BY bucket ASC
    """)
    try:
        rows = (await session.execute(
            q, {"cutoff": cutoff, "zone_id": str(zone_id)},
        )).all()
        return [float(r[1] or 0.0) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "zone_risk_history_query_failed",
            extra={"event": "zone_risk_history_query_failed",
                   "zone_id": str(zone_id),
                   "error_type": type(e).__name__},
        )
        return []


async def predict(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    subject_type: str = "zone",
    zone_id: Optional[uuid.UUID] = None,
    prediction_window_min: int = 15,
    persist: bool = True,
    history_override: Optional[list[float]] = None,
) -> dict:
    """Run one forecast cycle and (optionally) persist to ledger.

    Returns a dict matching the public API shape — same keys
    surfaced by `GET /api/risk/predict`. Persistence is a flag so
    the prewarmer can warm caches without polluting the ledger
    during startup."""
    if prediction_window_min not in PREDICTION_HORIZONS_MIN:
        raise ValueError(
            f"prediction_window_min must be one of "
            f"{PREDICTION_HORIZONS_MIN}, got {prediction_window_min}"
        )

    started = time.monotonic()
    if history_override is not None:
        history = list(history_override)
    else:
        history = await _zone_risk_history(session, zone_id)

    ewma = _EWMA.forecast(history)
    bayes = _BAYES.forecast(history)
    forecasts = [ewma, bayes]
    if _PROPHET.is_available():
        forecasts.append(_PROPHET.forecast(history))
    blend = blend_forecasts(forecasts)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=prediction_window_min)

    # Volatility — population stddev of the recent window. Surfaced
    # so the operator UI / alert pipeline can amplify confidence
    # when the zone is "fast-changing" not just "high-risk".
    volatility = 0.0
    if len(history) >= 2:
        mean = sum(history) / len(history)
        var = sum((x - mean) ** 2 for x in history) / len(history)
        volatility = var ** 0.5
    slope = _trend_slope(history)

    prediction_class = classify_prediction(blend.risk, volatility, slope)

    history_tail = history[-10:]
    context_snapshot = {
        "history_len":  len(history),
        "history_tail": history_tail,
        "volatility":   round(volatility, 6),
        "trend_slope":  round(slope, 6),
        "model_version": MODEL_VERSION,
        "pipeline_version": PIPELINE_VERSION,
    }
    h = _feature_hash(context_snapshot)
    latency_ms = round((time.monotonic() - started) * 1000.0, 2)

    # Structured log carries everything the operator panel + future
    # debug-replay surface need. Locked field list per the
    # observability spec.
    logger.info(
        "risk_prediction_computed",
        extra={
            "event": "risk_prediction_computed",
            "model_version": MODEL_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "feature_hash": h,
            "subject_id": str(subject_id),
            "subject_type": subject_type,
            "zone_id": str(zone_id) if zone_id else None,
            "prediction_class": prediction_class,
            "confidence_score": blend.confidence,
            "predicted_risk": blend.risk,
            "latency_ms": latency_ms,
            "window_min": prediction_window_min,
        },
    )

    # When EVERY forecaster returned confidence 0 (cold start, no
    # history at all), surface a `deferred` shape — same idiom as
    # the RAG-generation timeout. Don't persist.
    if blend.confidence == 0.0:
        return {
            "status":              "deferred",
            "retryable":           True,
            "reason":              "insufficient_history",
            "subject_id":          str(subject_id),
            "subject_type":        subject_type,
            "zone_id":             str(zone_id) if zone_id else None,
            "prediction_window_min": prediction_window_min,
            "contributing_factors": blend.factors,
            "model_version":       MODEL_VERSION,
            "pipeline_version":    PIPELINE_VERSION,
            "prediction_class":    prediction_class,
            "latency_ms":          latency_ms,
            "predicted_at":        now.isoformat(),
        }

    row = None
    if persist:
        try:
            row = RiskPrediction(
                subject_id=subject_id,
                subject_type=subject_type,
                zone_id=zone_id,
                prediction_window_min=prediction_window_min,
                predicted_risk=blend.risk,
                confidence_score=blend.confidence,
                prediction_class=prediction_class,
                contributing_factors=blend.factors,
                prediction_context_snapshot=context_snapshot,
                model_version=MODEL_VERSION,
                feature_hash=h,
                prediction_pipeline_version=PIPELINE_VERSION,
                window_expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.warning(
                "risk_prediction_persist_failed",
                extra={"event": "risk_prediction_persist_failed",
                       "subject_id": str(subject_id),
                       "error_type": type(e).__name__},
            )

    return {
        "status":                "ok",
        "subject_id":            str(subject_id),
        "subject_type":          subject_type,
        "zone_id":               str(zone_id) if zone_id else None,
        "prediction_window_min": prediction_window_min,
        "risk_probability":      blend.risk,
        "zone_volatility":       volatility,
        "trend_slope":           slope,
        "confidence_score":      blend.confidence,
        "prediction_class":      prediction_class,
        "contributing_factors":  blend.factors,
        "model_version":         MODEL_VERSION,
        "pipeline_version":      PIPELINE_VERSION,
        "feature_hash":          h,
        "latency_ms":            latency_ms,
        "predicted_at":          now.isoformat(),
        "window_expires_at":     expires_at.isoformat(),
        "prediction_id":         str(row.id) if row else None,
    }


async def forecast_zone_24h(
    session: AsyncSession,
    zone_id: uuid.UUID,
) -> dict:
    """24 h hourly risk forecast — runs EWMA + Bayesian forward,
    one hour at a time, using the simulated risk as the next
    history sample. Cheap (pure-Python), no DB hits beyond the
    initial history fetch."""
    history = await _zone_risk_history(session, zone_id)
    if not history:
        return {
            "status":   "deferred",
            "retryable": True,
            "reason":   "insufficient_history",
            "zone_id":  str(zone_id),
            "model_version": MODEL_VERSION,
            "pipeline_version": PIPELINE_VERSION,
        }

    rolling = list(history)
    hourly: list[dict] = []
    now = datetime.now(timezone.utc)
    for hour in range(1, 25):
        ewma = _EWMA.forecast(rolling)
        bayes = _BAYES.forecast(rolling)
        b = blend_forecasts([ewma, bayes])
        bucket_ts = now + timedelta(hours=hour)
        hourly.append({
            "hour":     hour,
            "ts":       bucket_ts.isoformat(),
            "predicted_risk":   b.risk,
            "confidence":       b.confidence,
        })
        # Project forward by appending the just-predicted value so
        # the EWMA smoothing carries momentum into the next hour.
        rolling.append(b.risk)

    return {
        "status":   "ok",
        "zone_id":  str(zone_id),
        "model_version": MODEL_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "hourly":   hourly,
        "generated_at": now.isoformat(),
    }


async def prediction_accuracy(
    session: AsyncSession,
    subject_id: uuid.UUID,
    *,
    since: Optional[datetime] = None,
) -> dict:
    """Aggregate accuracy stats for a subject's reconciled
    predictions. Driven by the index `idx_rp_accuracy` so it stays
    cheap even at scale."""
    since = since or (datetime.now(timezone.utc) - timedelta(days=7))
    q = text("""
        SELECT COUNT(*)                                AS reconciled_n,
               AVG(ABS(delta))::float                  AS mae,
               AVG(delta)::float                       AS mean_bias,
               AVG(CASE WHEN ABS(delta) < 0.1 THEN 1.0 ELSE 0.0 END)::float AS within_10pct
          FROM risk_predictions
         WHERE subject_id = :sid
           AND predicted_at >= :since
           AND delta IS NOT NULL
    """)
    row = (await session.execute(q, {"sid": str(subject_id), "since": since})).first()
    return {
        "subject_id":  str(subject_id),
        "since":       since.isoformat(),
        "reconciled_n": int(row[0] or 0),
        "mae":         float(row[1] or 0.0),
        "mean_bias":   float(row[2] or 0.0),
        "within_10pct": float(row[3] or 0.0),
        "model_version": MODEL_VERSION,
        "pipeline_version": PIPELINE_VERSION,
    }


__all__ = [
    "predict", "forecast_zone_24h", "prediction_accuracy",
    "classify_prediction",
    "MODEL_VERSION", "PIPELINE_VERSION", "PREDICTION_HORIZONS_MIN",
    "CRITICAL_RISK_THRESHOLD", "HIGH_VOLATILITY_THRESHOLD",
    "RISING_SLOPE_THRESHOLD",
]
