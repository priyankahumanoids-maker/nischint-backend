"""NISCH-012 — Motion features ingestion endpoint.

`POST /api/sensors/motion/features` — batched motion telemetry
upload from the mobile `motionTelemetryService`.

Locked contracts:
  1. Append-only. Idempotent via UNIQUE `idempotency_key` (device|
     window_started_at). A retried upload silently collapses to
     the existing row (no error, no duplicate).
  2. Best-effort persistence — any partial-batch failure logs +
     returns 207 with per-row status; the mobile uploader retries
     only the failed rows next cycle.
  3. Activity class validated at the writer boundary against the
     locked 5-value enum.
  4. NEVER blocks the dispatch pipeline. This endpoint is purely
     ingestion; nothing reads-then-writes during request handling.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.motion_features import (
    ALLOWED_ACTIVITY_CLASSES, TELEMETRY_PIPELINE_VERSION,
)
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/sensors/motion", tags=["motion-telemetry"],
)


# ── Schemas ──────────────────────────────────────────────────────


class MotionWindow(BaseModel):
    """One 60-second feature window. Exactly what the mobile
    edge processor extracts before batching."""
    window_started_at:  datetime
    window_duration_s:  int   = Field(default=60, ge=10, le=300)
    accel_mean_g:       float = Field(..., ge=0.0, le=20.0)
    accel_stddev_g:     float = Field(..., ge=0.0, le=20.0)
    accel_peak_g:       float = Field(..., ge=0.0, le=50.0)
    gyro_variance:      float = Field(..., ge=0.0, le=1000.0)
    activity_class:     str
    sample_count:       int   = Field(..., ge=1, le=10_000)
    sample_rate_hz:     float = Field(..., ge=0.1, le=200.0)
    device_context:     Optional[dict] = None

    @field_validator("activity_class")
    @classmethod
    def _validate_activity_class(cls, v: str) -> str:
        # Writer-boundary lock — only the 5 enum values allowed.
        # Mirrors the taxonomy lock in NISCH-011's deviation_class.
        if v not in ALLOWED_ACTIVITY_CLASSES:
            raise ValueError(
                f"activity_class={v!r} not in "
                f"{sorted(ALLOWED_ACTIVITY_CLASSES)}"
            )
        return v


class MotionFeaturesBatch(BaseModel):
    """Top-level batch payload. Bounded to 12 windows = 1 hour
    of 60-s windows. Larger batches indicate a misconfigured
    uploader; reject early."""
    device_id: str = Field(..., min_length=1, max_length=120)
    windows:   List[MotionWindow] = Field(..., min_length=1, max_length=12)


# ── Endpoint ─────────────────────────────────────────────────────


@router.post("/features")
async def ingest_motion_features(
    payload: MotionFeaturesBatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Append-only ingestion of a batch of 60-s motion windows.
    Returns a per-window status list so the mobile uploader knows
    exactly which windows persisted and which to retry.

    Idempotency: `device_id|window_started_at` is UNIQUE — a row
    that already exists is reported `status=duplicate` and the
    uploader can drop it from its retry queue."""
    user_id = current_user.id
    # Per-window persistence — ON CONFLICT DO NOTHING makes each
    # statement idempotent without needing a transaction-wide
    # rollback if one row collides.
    results: list[dict] = []
    for w in payload.windows:
        idem = f"{payload.device_id}|{w.window_started_at.isoformat()}"
        try:
            row = (await session.execute(text("""
                INSERT INTO motion_features
                  (entity_id, window_started_at, window_duration_s,
                   accel_mean_g, accel_stddev_g, accel_peak_g,
                   gyro_variance, activity_class,
                   sample_count, sample_rate_hz,
                   telemetry_pipeline_version, device_context,
                   idempotency_key, uploaded_at)
                VALUES
                  (:eid, :ws, :wd,
                   :am, :as_, :ap,
                   :gv, :ac,
                   :sc, :sr,
                   :pv, CAST(:ctx AS JSONB),
                   :idem, now())
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
            """), {
                "eid":  str(user_id),
                "ws":   w.window_started_at,
                "wd":   w.window_duration_s,
                "am":   w.accel_mean_g,
                "as_":  w.accel_stddev_g,
                "ap":   w.accel_peak_g,
                "gv":   w.gyro_variance,
                "ac":   w.activity_class,
                "sc":   w.sample_count,
                "sr":   w.sample_rate_hz,
                "pv":   TELEMETRY_PIPELINE_VERSION,
                "ctx":  _json(w.device_context),
                "idem": idem,
            })).first()
            if row:
                results.append({
                    "window_started_at": w.window_started_at.isoformat(),
                    "status": "inserted",
                    "id":     str(row[0]),
                })
            else:
                # Idempotency-key collision — duplicate retry.
                # Not an error; uploader can drop from its queue.
                results.append({
                    "window_started_at": w.window_started_at.isoformat(),
                    "status": "duplicate",
                })
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            logger.warning(
                "motion_features_window_persist_failed",
                extra={"event":      "motion_features_window_persist_failed",
                       "entity_id":  str(user_id),
                       "idem":       idem,
                       "error_type": type(e).__name__},
            )
            results.append({
                "window_started_at": w.window_started_at.isoformat(),
                "status": "failed",
                "retryable": True,
            })

    try:
        await session.commit()
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        logger.warning(
            "motion_features_batch_commit_failed",
            extra={"event": "motion_features_batch_commit_failed",
                   "error_type": type(e).__name__},
        )

    inserted_n = sum(1 for r in results if r["status"] == "inserted")
    duplicate_n = sum(1 for r in results if r["status"] == "duplicate")
    failed_n = sum(1 for r in results if r["status"] == "failed")
    logger.info(
        "motion_features_batch_ingested",
        extra={
            "event":      "motion_features_batch_ingested",
            "entity_id":  str(user_id),
            "device_id":  payload.device_id,
            "inserted":   inserted_n,
            "duplicate":  duplicate_n,
            "failed":     failed_n,
            "pipeline_version": TELEMETRY_PIPELINE_VERSION,
        },
    )

    return {
        "status":     "ok" if failed_n == 0 else "partial",
        "inserted":   inserted_n,
        "duplicate":  duplicate_n,
        "failed":     failed_n,
        "results":    results,
        "telemetry_pipeline_version": TELEMETRY_PIPELINE_VERSION,
    }


# ── Internal read helper for the baseline learner + risk prewarmer
# (Layer 5 wiring). Kept in this module so any future signature
# change is colocated with the writer.


async def fetch_recent_motion_aggregate(
    session: AsyncSession,
    entity_id: uuid.UUID,
    *,
    since_hours: int = 24,
) -> Optional[dict]:
    """Aggregate the last N hours of motion windows for an
    entity. Returns None when the entity has no rows (cold start)
    so callers can branch on data availability."""
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    try:
        row = (await session.execute(text("""
            SELECT COUNT(*)::int                              AS n,
                   AVG(accel_mean_g)::float                   AS mean_g,
                   AVG(accel_stddev_g)::float                 AS stddev_g,
                   MAX(accel_peak_g)::float                   AS peak_g,
                   AVG(gyro_variance)::float                  AS gyro_var,
                   MAX(window_started_at)                     AS latest,
                   COUNT(*) FILTER (WHERE activity_class = 'stationary')::int AS n_stat,
                   COUNT(*) FILTER (WHERE activity_class = 'walking')::int    AS n_walk,
                   COUNT(*) FILTER (WHERE activity_class = 'running')::int    AS n_run,
                   COUNT(*) FILTER (WHERE activity_class = 'vehicle')::int    AS n_veh,
                   COUNT(*) FILTER (WHERE activity_class = 'anomalous')::int  AS n_anom
              FROM motion_features
             WHERE entity_id = :eid
               AND window_started_at >= :since
        """), {"eid": str(entity_id), "since": since})).first()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "motion_features_aggregate_query_failed",
            extra={"event": "motion_features_aggregate_query_failed",
                   "entity_id": str(entity_id),
                   "error_type": type(e).__name__},
        )
        return None
    if not row or not row[0]:
        return None
    return {
        "window_count":   int(row[0] or 0),
        "mean_g":         float(row[1] or 0.0),
        "stddev_g":       float(row[2] or 0.0),
        "peak_g":         float(row[3] or 0.0),
        "gyro_variance":  float(row[4] or 0.0),
        "latest_window":  row[5].isoformat() if row[5] else None,
        "activity_distribution": {
            "stationary": int(row[6] or 0),
            "walking":    int(row[7] or 0),
            "running":    int(row[8] or 0),
            "vehicle":    int(row[9] or 0),
            "anomalous":  int(row[10] or 0),
        },
        "telemetry_pipeline_version": TELEMETRY_PIPELINE_VERSION,
    }


def _json(obj) -> Optional[str]:
    if obj is None:
        return None
    import json
    return json.dumps(obj, default=str)


__all__ = ["router", "fetch_recent_motion_aggregate"]
