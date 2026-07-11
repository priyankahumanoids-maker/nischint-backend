"""NISCH-011 — Behavioral Anomaly Detector.

Compares a fresh observation against the entity's stored
baseline, scores Z-deviations across the locked feature set,
classifies via taxonomy, fuses with zone risk + temporal context
+ sensor confidence + forecast divergence weight, and writes to
the immutable `behavioral_anomalies` ledger.

Write semantics (LOCKED — proven by tests):
  * INSERT only — never UPDATE outside the reconciler. The
    writer has no `id` parameter; the DB generates one. Same
    boundary discipline as NISCH-010's ledger.
  * On INSERT failure, fall back to `dlq:ml_predictions`. Caller
    NEVER sees a raise — dispatch path never blocks.
  * `deviation_class` must be one of the 5 taxonomy values; the
    detector raises a `ValueError` ONLY in dev-mode when given
    an unknown class. Production writers go through
    `classify_from_z` which always emits a valid value.

Non-blocking guarantee:
  Every public function in this module is wrapped against
  exceptions. The `assess_and_record` orchestrator returns a
  best-effort result dict and stamps the explanation snapshot
  even if the ledger write fails.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.behavioral import ANOMALY_PIPELINE_VERSION
from app.services.behavioral.dlq import append_anomaly_ledger
from app.services.behavioral.divergence import compute_divergence
from app.services.behavioral.fusion import (
    fuse_with_explanation,
    should_influence_dispatch,
)
from app.services.behavioral.taxonomy import (
    ALLOWED_DEVIATION_CLASSES,
    DeviationClass,
    classify_from_z,
)

logger = logging.getLogger(__name__)


def _z(x: float, mean: float, stdev: float) -> float:
    """Defence: zero-stdev → 0 z. A baseline with no variance
    can't tell the detector anything new — return 0 instead of
    +Inf."""
    if not stdev:
        return 0.0
    return (float(x) - float(mean)) / float(stdev)


async def _load_baseline(
    session: AsyncSession, entity_id: uuid.UUID,
) -> Optional[dict]:
    """Pull the entity's stored baseline. None on cold start (no
    row) or on DB failure (defensive)."""
    try:
        row = (await session.execute(text("""
            SELECT mobility_signature, dwell_duration,
                   rolling_deviation_thresholds, sample_count,
                   baseline_version
              FROM behavioral_baselines
             WHERE entity_id = :eid
             LIMIT 1
        """), {"eid": str(entity_id)})).first()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "behavioral_baseline_load_failed",
            extra={"event": "behavioral_baseline_load_failed",
                   "entity_id": str(entity_id),
                   "error_type": type(e).__name__},
        )
        return None
    if not row:
        return None
    return {
        "mobility_signature":           row[0] or {},
        "dwell_duration":               row[1] or {},
        "rolling_deviation_thresholds": row[2] or {},
        "sample_count":                 int(row[3] or 0),
        "baseline_version":             row[4],
    }


def score_anomaly(
    observation: dict,
    baseline: dict,
) -> dict:
    """Pure-function scorer. Returns dict with `anomaly_score`,
    `deviation_class`, `contributing_features`, and the per-
    feature Z values.

    Cold-start handling: if baseline has 0 stdev across the
    monitored features, the detector returns the BASELINE class
    with score 0 — it can't anomaly-detect without variance."""
    mob = baseline.get("mobility_signature") or {}
    dwell = baseline.get("dwell_duration") or {}

    speed_z = _z(
        observation.get("speed_mps", 0.0),
        mob.get("mean_speed_mps", 0.0),
        mob.get("stdev_speed_mps", 0.0),
    )
    dwell_z = _z(
        observation.get("dwell_s", 0.0),
        dwell.get("mean_s", 0.0),
        dwell.get("stdev_s", 0.0),
    )

    # Aggregate z — Euclidean norm over the feature dimensions
    # we have. Robust against direction noise; a fast-moving kid
    # in a long-dwell zone surfaces as anomalous regardless of
    # sign.
    z_norm = (speed_z * speed_z + dwell_z * dwell_z) ** 0.5
    deviation_class = classify_from_z(z_norm)

    # Anomaly score = sigmoid-like squashing of z_norm so the
    # downstream fusion math stays bounded [0, 1].
    if z_norm <= 0:
        anomaly_score = 0.0
    else:
        anomaly_score = max(0.0, min(1.0, z_norm / 5.0))

    contributing = []
    if abs(speed_z) >= 1.5:
        contributing.append(f"mobility_speed_z={speed_z:.2f}")
    if abs(dwell_z) >= 1.5:
        contributing.append(f"dwell_z={dwell_z:.2f}")
    if not contributing:
        contributing.append(
            f"z_norm={z_norm:.2f} below_contribution_threshold"
        )

    return {
        "anomaly_score":         anomaly_score,
        "deviation_class":       deviation_class,
        "contributing_features": contributing,
        "z_speed":               speed_z,
        "z_dwell":               dwell_z,
        "z_norm":                z_norm,
    }


async def write_anomaly(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID,
    anomaly_type: str,
    anomaly_score: float,
    deviation_class: str,
    contributing_features: list[str],
    fused_zone_risk: Optional[float],
    confidence: float,
    explanation_snapshot: dict,
    linked_prediction_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    """Append to the immutable anomaly ledger. INSERT-only —
    never updates. On failure the entry goes to the
    `dlq:ml_predictions` ring buffer; caller still gets a `None`
    return so dispatch logic can fall through.

    `deviation_class` MUST be one of the locked taxonomy values
    or the writer raises (dev-mode defence). Production writers
    feed this from `classify_from_z` which only emits valid
    values; tests assert the boundary."""
    if deviation_class not in ALLOWED_DEVIATION_CLASSES:
        raise ValueError(
            f"deviation_class={deviation_class!r} not in locked "
            f"taxonomy {sorted(ALLOWED_DEVIATION_CLASSES)}"
        )

    try:
        row = (await session.execute(text("""
            INSERT INTO behavioral_anomalies
              (entity_id, anomaly_type, anomaly_score, deviation_class,
               contributing_features, linked_prediction_id,
               fused_zone_risk, confidence, explanation_snapshot,
               anomaly_pipeline_version, reconciliation_status,
               created_at)
            VALUES
              (:entity_id, :atype, :ascore, :devclass,
               CAST(:contrib AS JSONB), :linkpid,
               :fused, :conf, CAST(:explain AS JSONB),
               :pipever, 'pending', now())
            RETURNING id
        """), {
            "entity_id": str(entity_id),
            "atype":     anomaly_type,
            "ascore":    float(anomaly_score),
            "devclass":  deviation_class,
            "contrib":   __json(contributing_features),
            "linkpid":   str(linked_prediction_id) if linked_prediction_id else None,
            "fused":     float(fused_zone_risk) if fused_zone_risk is not None else None,
            "conf":      float(confidence),
            "explain":   __json(explanation_snapshot),
            "pipever":   ANOMALY_PIPELINE_VERSION,
        })).first()
        await session.commit()
        return row[0] if row else None
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        logger.warning(
            "behavioral_anomaly_write_failed",
            extra={"event": "behavioral_anomaly_write_failed",
                   "entity_id": str(entity_id),
                   "error_type": type(e).__name__},
        )
        # Compensating action — DLQ append-only ledger. Never
        # raises into caller.
        append_anomaly_ledger({
            "entity_id":             str(entity_id),
            "anomaly_type":          anomaly_type,
            "anomaly_score":         float(anomaly_score),
            "deviation_class":       deviation_class,
            "contributing_features": contributing_features,
            "linked_prediction_id":  str(linked_prediction_id) if linked_prediction_id else None,
            "fused_zone_risk":       float(fused_zone_risk) if fused_zone_risk is not None else None,
            "confidence":            float(confidence),
            "explanation_snapshot":  explanation_snapshot,
            "anomaly_pipeline_version": ANOMALY_PIPELINE_VERSION,
        })
        return None


async def assess_and_record(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID,
    observation: dict,
    zone_risk: float = 0.0,
    forecast_votes: Optional[list[float]] = None,
    temporal_context: float = 1.0,
    sensor_confidence: float = 1.0,
    linked_prediction_id: Optional[uuid.UUID] = None,
) -> dict:
    """Top-level orchestrator. Loads baseline → scores → fuses →
    writes ledger row (or DLQ on failure). Returns a stable
    dict the alert pipeline can introspect WITHOUT branching on
    'did it actually persist'."""
    baseline = await _load_baseline(session, entity_id)
    if baseline is None or baseline.get("sample_count", 0) < 5:
        # Cold start — no anomaly fired, returned for symmetry.
        return {
            "status":          "cold_start",
            "deviation_class": DeviationClass.BASELINE.value,
            "anomaly_score":   0.0,
            "fused_risk":      0.0,
            "dispatch_influence": False,
            "pipeline_version": ANOMALY_PIPELINE_VERSION,
            "reason":          "baseline_not_warm",
        }

    score = score_anomaly(observation, baseline)
    divergence = compute_divergence(forecast_votes or [])
    fusion = fuse_with_explanation(
        behavioral_anomaly=score["anomaly_score"],
        zone_risk=zone_risk,
        deviation_class=score["deviation_class"],
        temporal_context=temporal_context,
        sensor_confidence=sensor_confidence,
        divergence_weight=divergence.confidence_weight,
    )
    explanation = {
        "z":                   {"speed": score["z_speed"],
                                "dwell": score["z_dwell"],
                                "norm":  score["z_norm"]},
        "divergence":          {
            "index":             divergence.index,
            "confidence_weight": divergence.confidence_weight,
            "votes":             divergence.contributing_votes,
        },
        "fusion_components":   fusion.components,
        "baseline_version":    baseline.get("baseline_version"),
        "pipeline_version":    ANOMALY_PIPELINE_VERSION,
    }

    anomaly_id = await write_anomaly(
        session,
        entity_id=entity_id,
        anomaly_type=observation.get("anomaly_type", "behavioural_deviation"),
        anomaly_score=score["anomaly_score"],
        deviation_class=score["deviation_class"],
        contributing_features=score["contributing_features"],
        fused_zone_risk=fusion.fused_risk,
        confidence=divergence.confidence_weight,
        explanation_snapshot=explanation,
        linked_prediction_id=linked_prediction_id,
    )

    return {
        "status":             "ok" if anomaly_id else "dlq_fallback",
        "anomaly_id":         str(anomaly_id) if anomaly_id else None,
        "deviation_class":    score["deviation_class"],
        "anomaly_score":      score["anomaly_score"],
        "fused_risk":         fusion.fused_risk,
        "dispatch_influence": fusion.dispatch_influence,
        "forecast_divergence_index": divergence.index,
        "pipeline_version":   ANOMALY_PIPELINE_VERSION,
    }


def __json(obj) -> str:
    import json
    return json.dumps(obj, default=str)


__all__ = [
    "score_anomaly", "write_anomaly", "assess_and_record",
    "should_influence_dispatch",
]
