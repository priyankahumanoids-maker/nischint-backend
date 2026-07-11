"""SF-01 v2 Day 3 — GET /api/env/hazards?lat&lng&radius_km wrapper.

Public per-coord query for the env-hazard layer. The mobile client
polls this every 5 min for the hazard-zone overlay; operator dashboards
use it for the "show hazards near user X" UI tile.

Read-only. No new write path. Reuses the same Sachet/NDMA cache and
OpenWeather snapshot the safety brain already consumes — zero new
backend dependency.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.models.user import User
from app.services.env_hazard_matcher import match_env_hazards

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/env", tags=["environment"])


@router.get("/hazards")
async def get_env_hazards(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lng: float = Query(..., ge=-180.0, le=180.0),
    radius_km: float = Query(5.0, ge=0.1, le=50.0),
    _: User = Depends(get_current_user),  # auth-gated
) -> dict:
    """Return active hazards near (lat,lng) within `radius_km`.

    `radius_km` is accepted for API symmetry with the sprint spec but
    is currently used only as a metadata field — the underlying
    Sachet/NDMA match is state-bbox-based (PostGIS polygon-radius
    matching deferred to SF-02). Callers can use the returned
    `state` to scope their UI without an extra request.
    """
    # Best-effort weather snapshot to capture forming red-flag events
    # the NDMA RSS hasn't picked up yet. Same path used by the safety
    # brain composite recalc — guaranteed-cheap (cached).
    weather = None
    try:
        from app.services.weather_service import get_weather
        weather = await get_weather(lat, lng)
    except Exception:  # noqa: BLE001
        weather = None

    try:
        env = await match_env_hazards(lat, lng, weather=weather)
    except Exception as exc:  # noqa: BLE001
        logger.exception("env/hazards match failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="env_hazard_lookup_failed",
        ) from exc

    return {
        "lat":         lat,
        "lng":         lng,
        "radius_km":   radius_km,
        "state":       env["state"],
        "matched":     env["matched"],
        "hazards":     env["hazards"],
        "strongest":   env["strongest"],
        # `multiplier` is the same number the safety brain would
        # apply for an alert at this point — clients can preview
        # what an incident here would score.
        "multiplier":  env["multiplier"],
    }


__all__ = ["router"]
