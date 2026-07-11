"""SF-01 v2 Day 2 — POST /api/signals/motion live-stream endpoint.

Lightweight, event-driven live-stream surface for motion signals from
the mobile client. Distinct from the 5-min batched ledger at
`POST /api/sensors/motion/features` (NISCH-012), which is kept as-is
for audit-trail / behavioural-baseline enrichment.

Contract:
  * Body: `{ user_id?, fall, voice_distress, lat, lng, timestamp }`
  * Writes the signal bundle to Redis at `motion:{user_id}:live`
    TTL 90s (slightly longer than the 30s emit cadence so a brief
    network glitch can't lose live state).
  * Triggers `safety_brain_service.evaluate_risk(...)` immediately
    — composite recalc happens on the request thread so a real
    Himalaya-style spike fires the alert pipeline in <1 second.
  * Auth: same JWT path as every other endpoint (`get_current_user`).
    `user_id` in the body is honoured ONLY for admin/operator
    callers (impersonation / test). All other callers operate on
    their own `current_user.id`.
  * NEVER blocks the dispatch pipeline. Any failure short of the
    auth/validation boundary returns a structured `{degraded: true}`
    payload so the mobile uploader knows to retry without crashing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services import redis_service
from app.services.safety_brain_service import (
    WEIGHTS, classify_risk, evaluate_risk,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/signals", tags=["safety-brain-signals"])


# ── Schemas ─────────────────────────────────────────────────────


class MotionSignalBundle(BaseModel):
    """One live snapshot of motion-derived safety signals."""
    user_id:         Optional[str] = None  # admin/operator only
    fall:            float = Field(0.0, ge=0.0, le=1.0)
    voice_distress:  float = Field(0.0, ge=0.0, le=1.0)
    lat:             float
    lng:             float
    timestamp:       Optional[datetime] = None


# ── Endpoint ────────────────────────────────────────────────────


@router.post("/motion")
async def ingest_motion_signal(
    payload: MotionSignalBundle,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Live-stream motion signals → Safety Brain composite recalc.

    Returns the computed risk shape so the mobile client can render
    its own local state without making a follow-up call.
    """
    # Resolve effective user. Non-admin callers can only push for
    # themselves — silently coerce. Admin/operator may push for any
    # user (used by `inject_himalaya_scenario.py`).
    target_user_id = str(current_user.id)
    if payload.user_id and current_user.role in ("admin", "operator"):
        target_user_id = payload.user_id
        # SF-01 v2 Day 4 — validate the impersonation target exists
        # in the users table. Without this, the env multiplier can
        # promote a "normal" score to "suspicious" which would then
        # attempt a SafetyEvent INSERT and hit the FK constraint.
        # Returning 404 surfaces the operator's typo cleanly.
        from sqlalchemy import select as _select
        from app.models.user import User as _User
        exists = await session.execute(
            _select(_User.id).where(_User.id == target_user_id)
        )
        if exists.first() is None:
            raise HTTPException(
                status_code=404,
                detail=f"target user_id not found: {target_user_id}",
            )

    ts = payload.timestamp or datetime.now(timezone.utc)
    bundle = {
        "fall":           round(float(payload.fall), 3),
        "voice_distress": round(float(payload.voice_distress), 3),
        "lat":            float(payload.lat),
        "lng":            float(payload.lng),
        "timestamp":      ts.isoformat(),
    }

    # Cache live snapshot. 90s TTL > 30s cadence prevents a single
    # missed POST from wiping live state. Failures are non-fatal —
    # the composite recalc below still runs from the request body.
    try:
        redis_service.set_json(
            "motion_live", target_user_id, bundle, ttl=90,
        )
    except Exception:  # noqa: BLE001
        # Compensating action: composite recalc still runs from the
        # in-memory bundle; UI may briefly read stale live state on
        # the next read until Redis recovers.
        logger.warning(
            "motion_signal_redis_cache_failed",
            extra={"event": "motion_signal_redis_cache_failed",
                   "user_id": target_user_id},
        )

    # Trigger composite recalc. Map the live-stream contract
    # (`fall`, `voice_distress`) onto the Safety Brain's locked
    # signal taxonomy (`fall`, `voice`).
    signals = {
        "fall":  bundle["fall"],
        "voice": bundle["voice_distress"],
    }
    try:
        result = await evaluate_risk(
            session, target_user_id, signals,
            lat=bundle["lat"], lng=bundle["lng"],
        )
    except Exception:  # noqa: BLE001
        # Compensating action: return a degraded payload so the
        # mobile uploader keeps trying without crashing. The
        # 5-min ledger still captures the same window.
        logger.exception(
            "motion_signal_evaluate_failed user=%s", target_user_id,
        )
        return {
            "degraded":    True,
            "user_id":     target_user_id,
            "received_at": ts.isoformat(),
        }

    score = float(result.get("risk_score") or 0.0)
    return {
        "user_id":          target_user_id,
        "received_at":      ts.isoformat(),
        "composite":        round(score, 3),
        "risk_level":       result.get("risk_level") or classify_risk(score),
        "primary_event":    result.get("primary_event"),
        "signal_weights":   WEIGHTS,
        "signal_bundle":    bundle,
        # SF-01 v2 Day 3 — surface env match so mobile/operator can
        # render the hazard chip immediately without an extra fetch.
        "env_hazard_match": result.get("env_hazard_match", False),
        "env_multiplier":   result.get("env_multiplier", 1.0),
        "env_strongest":    result.get("env_strongest"),
        "pre_mult_score":   result.get("pre_mult_score", score),
        "alert_fired":      result.get("alert_fired", score >= 0.65),
    }


__all__ = ["router"]
