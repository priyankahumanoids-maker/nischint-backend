"""NISCH-010 — Predictive Risk API.

Four endpoints per the Phase-1 surface lock:

  GET /api/risk/predict
  GET /api/risk/zones/{zone_id}/forecast
  GET /api/risk/predictions/{subject_id}/accuracy
  GET /api/risk/route          (501 Not Implemented — Phase 2 stub)

All endpoints are non-blocking (async OpenAI's lesson learned)
and return a stable shape — `status: "ok" | "deferred"` so the
caller can branch without parsing error messages. Aligned with
the DLQ-architecture "compensating action exists" rule.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.services.risk_prediction.predictor import (
    forecast_zone_24h, prediction_accuracy, predict,
)

router = APIRouter(prefix="/risk", tags=["risk-prediction"])


@router.get("/predict")
async def get_predict(
    lat: float = Query(..., description="Subject latitude"),
    lng: float = Query(..., description="Subject longitude"),
    window_min: int = Query(15, description="Prediction horizon: 15 or 60"),
    zone_id: Optional[str] = Query(
        None, description="Optional explicit zone UUID; falls back to lat/lng",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Single-shot prediction for the zone containing `(lat, lng)`.

    Returns the RiskPrediction shape on success, or
    `{"status": "deferred", "retryable": true, "reason": ...}` when
    the history is too thin for a confident forecast. Same idiom
    as the RAG-generation timeout path."""
    z_uuid: Optional[uuid.UUID] = None
    if zone_id:
        try:
            z_uuid = uuid.UUID(zone_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid zone_id UUID")

    # `subject_id` for a zone forecast is the zone itself. When no
    # zone is identified, mint a deterministic UUID from (lat, lng)
    # so repeated calls for the same coordinates land on the same
    # ledger row stream — supports per-coordinate accuracy analysis.
    subject_id = z_uuid or uuid.uuid5(
        uuid.NAMESPACE_DNS, f"latlng:{lat:.4f},{lng:.4f}",
    )

    return await predict(
        session,
        subject_id=subject_id,
        subject_type="zone",
        zone_id=z_uuid,
        prediction_window_min=window_min,
    )


@router.get("/zones/{zone_id}/forecast")
async def get_zone_forecast(
    zone_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """24 h hourly forecast for a zone."""
    try:
        z_uuid = uuid.UUID(zone_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid zone_id UUID")
    return await forecast_zone_24h(session, z_uuid)


@router.get("/predictions/{subject_id}/accuracy")
async def get_prediction_accuracy(
    subject_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Ledger-driven accuracy stats: reconciled-count, MAE, mean
    bias, within-10 % rate. Window defaults to last 7 days."""
    try:
        s_uuid = uuid.UUID(subject_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid subject_id UUID")
    return await prediction_accuracy(session, s_uuid)


@router.get("/route")
async def get_route_risk() -> dict:
    """Safe Route Engine — Phase 2 surface. Locked at 501 so the
    API contract is complete but the implementation gates on the
    routing-engine integration."""
    raise HTTPException(
        status_code=501,
        detail={
            "status":   "not_implemented",
            "phase":    "2",
            "tracking": "NISCH-007 predictive routing layer",
        },
    )
