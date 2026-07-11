"""NISCH-010 — Reconciler.

Backfills `actual_outcome`, `delta`, and `outcome_resolution_version`
on rows whose `window_expires_at` has passed. Without this job the
ledger is write-only and the accuracy column never populates.

Strict scope: the reconciler does NOT modify `predicted_risk` —
that's the immutable historical record. It only fills the
retrospective columns and timestamps `outcome_recorded_at`.

Outcome model (deterministic, Phase 1):
  Outcome ∈ [0, 1] is a weighted blend of five signals from the
  prediction window:

    severity_weight       — average normalized severity rank
    escalation_weight     — average `escalation_level` (0..3)
    acknowledgement_weight— ack rate (operator-confirmed incidents)
    incident_density      — bounded count of incidents in the window
    dispatch_weight       — presence of emergency dispatch (extra)

  Each weight contributes to the final outcome score with a fixed
  coefficient set; changing those coefficients MUST bump
  `OUTCOME_RESOLUTION_VERSION` so reports stay comparable across
  versions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.risk_prediction import OUTCOME_RESOLUTION_VERSION

logger = logging.getLogger(__name__)


# Severity ladder — `info` carries zero accuracy weight, `critical`
# carries full weight. Lookups default to 0.0 so an unknown value
# never injects noise into the outcome score.
_SEVERITY_RANK: dict[str, float] = {
    "info":     0.0,
    "low":      0.25,
    "medium":   0.5,
    "high":     0.75,
    "critical": 1.0,
}


def compute_outcome(
    *,
    avg_severity_rank: float,
    avg_escalation: float,
    ack_rate: float,
    incident_density: float,
    dispatch_present: float,
) -> float:
    """Deterministic outcome computation. Pure function — covered
    by `test_risk_prediction.py::test_compute_outcome_*` so the
    coefficient set is locked in CI."""
    score = (
        0.35 * avg_severity_rank
        + 0.20 * min(1.0, avg_escalation / 3.0)
        + 0.20 * ack_rate
        + 0.15 * min(1.0, incident_density / 5.0)
        + 0.10 * dispatch_present
    )
    return max(0.0, min(1.0, score))


async def _window_signals(
    session: AsyncSession,
    *,
    zone_id,
    start: datetime,
    end: datetime,
) -> dict:
    """Aggregate the five outcome inputs over the prediction
    window. Best-effort — returns zeros on query failure so
    reconciliation degrades gracefully rather than blocking."""
    try:
        row = (await session.execute(text("""
            SELECT
                COUNT(*)::int                                 AS n,
                COUNT(*) FILTER (WHERE severity='critical')::int AS crit_n,
                COUNT(*) FILTER (WHERE severity='high')::int     AS high_n,
                COUNT(*) FILTER (WHERE severity='medium')::int   AS med_n,
                COUNT(*) FILTER (WHERE severity='low')::int      AS low_n,
                COUNT(*) FILTER (WHERE severity='info')::int     AS info_n,
                COALESCE(AVG(escalation_level), 0)::float        AS avg_esc,
                COUNT(*) FILTER (WHERE acknowledged_at IS NOT NULL)::int AS ack_n,
                COUNT(*) FILTER (WHERE extra ? 'emergency_dispatch')::int AS disp_n
              FROM safety_incidents
             WHERE created_at >= :start
               AND created_at <= :end
               AND (:zone IS NULL OR external_signals->>'zone_id' = :zone)
        """), {
            "start": start, "end": end,
            "zone":  str(zone_id) if zone_id else None,
        })).first()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "reconciler_window_query_failed",
            extra={"event": "reconciler_window_query_failed",
                   "error_type": type(e).__name__},
        )
        return {
            "n": 0, "avg_severity_rank": 0.0, "avg_escalation": 0.0,
            "ack_rate": 0.0, "incident_density": 0.0,
            "dispatch_present": 0.0,
        }

    n = int(row[0] or 0)
    if n == 0:
        return {
            "n": 0, "avg_severity_rank": 0.0, "avg_escalation": 0.0,
            "ack_rate": 0.0, "incident_density": 0.0,
            "dispatch_present": 0.0,
        }
    severity_sum = (
        _SEVERITY_RANK["critical"] * int(row[1] or 0)
        + _SEVERITY_RANK["high"]   * int(row[2] or 0)
        + _SEVERITY_RANK["medium"] * int(row[3] or 0)
        + _SEVERITY_RANK["low"]    * int(row[4] or 0)
        + _SEVERITY_RANK["info"]   * int(row[5] or 0)
    )
    return {
        "n":                  n,
        "avg_severity_rank":  severity_sum / n,
        "avg_escalation":     float(row[6] or 0.0),
        "ack_rate":           float(row[7] or 0) / n,
        "incident_density":   float(n),
        "dispatch_present":   1.0 if int(row[8] or 0) > 0 else 0.0,
    }


async def reconcile_outcomes(
    session: AsyncSession, *, batch_size: int = 100,
) -> dict:
    """Walks up-to `batch_size` pending rows whose
    `window_expires_at` has passed and fills their outcome.

    Pending = `actual_outcome IS NULL AND window_expires_at <= now`.
    Partial index `idx_rp_pending_outcome` keeps this O(pending).
    """
    now = datetime.now(timezone.utc)

    pending = (await session.execute(text("""
        SELECT id, subject_id, zone_id, predicted_risk,
               predicted_at, window_expires_at
          FROM risk_predictions
         WHERE actual_outcome IS NULL
           AND window_expires_at <= :now
         ORDER BY window_expires_at ASC
         LIMIT :limit
    """), {"now": now, "limit": batch_size})).all()

    if not pending:
        return {"reconciled": 0, "batch_size": batch_size,
                "outcome_resolution_version": OUTCOME_RESOLUTION_VERSION}

    reconciled = 0
    for row in pending:
        (rp_id, _subject_id, zone_id, predicted_risk,
         predicted_at, expires_at) = row
        signals = await _window_signals(
            session, zone_id=zone_id,
            start=predicted_at, end=expires_at,
        )
        actual = compute_outcome(
            avg_severity_rank=signals["avg_severity_rank"],
            avg_escalation=signals["avg_escalation"],
            ack_rate=signals["ack_rate"],
            incident_density=signals["incident_density"],
            dispatch_present=signals["dispatch_present"],
        )
        delta = actual - float(predicted_risk)

        try:
            await session.execute(text("""
                UPDATE risk_predictions
                   SET actual_outcome             = :actual,
                       delta                      = :delta,
                       outcome_recorded_at        = :recorded,
                       outcome_resolution_version = :ov
                 WHERE id = :id
            """), {
                "actual": actual, "delta": delta,
                "recorded": now, "ov": OUTCOME_RESOLUTION_VERSION,
                "id": rp_id,
            })
            reconciled += 1
            logger.info(
                "risk_prediction_reconciled",
                extra={
                    "event": "risk_prediction_reconciled",
                    "prediction_id": str(rp_id),
                    "predicted_risk": float(predicted_risk),
                    "actual_outcome": actual,
                    "delta": delta,
                    "incident_count": signals["n"],
                    "outcome_resolution_version": OUTCOME_RESOLUTION_VERSION,
                },
            )
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.warning(
                "prediction_reconcile_row_failed",
                extra={"event": "prediction_reconcile_row_failed",
                       "prediction_id": str(rp_id),
                       "error_type": type(e).__name__},
            )
    try:
        await session.commit()
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        logger.warning(
            "prediction_reconcile_commit_failed",
            extra={"event": "prediction_reconcile_commit_failed",
                   "error_type": type(e).__name__},
        )
    logger.info(
        "prediction_reconcile_complete",
        extra={"event": "prediction_reconcile_complete",
               "reconciled": reconciled,
               "outcome_resolution_version": OUTCOME_RESOLUTION_VERSION},
    )
    return {
        "reconciled": reconciled,
        "batch_size": batch_size,
        "outcome_resolution_version": OUTCOME_RESOLUTION_VERSION,
    }


__all__ = ["reconcile_outcomes", "compute_outcome",
           "OUTCOME_RESOLUTION_VERSION"]
