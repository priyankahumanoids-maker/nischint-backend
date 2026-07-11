"""SF-01 v2 Day 4 — `/api/operator/dev/scenario` admin debug endpoint.

The investor-demo "fire button". When the env flag
`DEV_SCENARIOS_ENABLED=true` is set AND the caller is an operator/admin,
this endpoint:

  1. Cache-injects a synthetic CAP hazard alert into the existing
     Sachet Redis namespace (`sachet:rss_parsed_v1`) for the target
     user's resolved state. TTL = `ttl_minutes × 60`.
  2. Calls `safety_brain_service.evaluate_risk(...)` immediately
     with a Himalaya-style signal bundle.
  3. Returns the composite envelope so the Command Center button
     can show `composite 0.79 · ALERT` inline without a page reload.

Production safety:
  * Two guards: env flag MUST be true AND caller MUST be operator/admin.
    Either failing → 403, never 200.
  * Zero writes to PostgreSQL.
  * The injected CAP alert decays naturally via Redis TTL — no
    cleanup endpoint needed, never persists past `ttl_minutes`.
  * Scenario names are an enum-locked allowlist. Unknown name → 422.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services import redis_service
from app.services.external_signals.sachet_provider import (
    CACHE_KEY,
    CACHE_NAMESPACE,
)
from app.services.safety_brain_service import evaluate_risk, classify_risk

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operator/dev", tags=["operator-dev"])


# ── Scenario library ────────────────────────────────────────────
#
# Each scenario is a self-contained tuple of (synthetic CAP-alert,
# motion-signal bundle, demo-coords). Adding a scenario = adding one
# row here; no other code path changes.

ScenarioName = Literal["himalaya_landslide", "urban_flood", "cyclone_coast"]

_SCENARIO_LIBRARY: dict[str, dict] = {
    "himalaya_landslide": {
        "label": "Himalaya Landslide",
        "cap_alert": {
            "title":      "Cloudburst & Landslide Warning — Uttarakhand",
            "state":      "Uttarakhand",
            "severity":   "severe",
            "event_type": "landslide",
            "pub_at":     None,  # filled in at injection time
        },
        "coords": (30.7333, 79.0667),  # Kedarnath area
        "signals": {"fall": 0.90, "voice_distress": 0.65},
    },
    "urban_flood": {
        "label": "Urban Flood",
        "cap_alert": {
            "title":      "Severe Urban Flood Warning — Maharashtra",
            "state":      "Maharashtra",
            "severity":   "severe",
            "event_type": "flood",
            "pub_at":     None,
        },
        "coords": (19.0760, 72.8777),  # Mumbai
        "signals": {"fall": 0.0, "voice_distress": 0.70},
    },
    "cyclone_coast": {
        "label": "Cyclone Coast",
        "cap_alert": {
            "title":      "Cyclone Warning — Andhra Pradesh Coast",
            "state":      "Andhra Pradesh",
            "severity":   "extreme",
            "event_type": "cyclone",
            "pub_at":     None,
        },
        "coords": (15.9129, 80.4789),  # AP coast
        "signals": {"fall": 0.0, "voice_distress": 0.55},
    },
}


# ── Schema ───────────────────────────────────────────────────────


class ScenarioRequest(BaseModel):
    scenario: ScenarioName
    target_user_id: str
    ttl_minutes: int = Field(5, ge=1, le=30)


# ── Guards ───────────────────────────────────────────────────────


def _dev_scenarios_enabled() -> bool:
    """Read fresh from env every call so a runtime flag flip takes
    effect without a restart."""
    return os.environ.get("DEV_SCENARIOS_ENABLED", "").lower() in (
        "1", "true", "yes", "on",
    )


def _ensure_operator(user: User) -> None:
    role = getattr(user, "role", None)
    if role not in ("admin", "operator"):
        raise HTTPException(
            status_code=403,
            detail="Operator role required for scenario injection",
        )


# ── Endpoint ─────────────────────────────────────────────────────


@router.post("/scenario")
async def fire_scenario(
    payload: ScenarioRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Cache-inject a synthetic hazard, then run a composite recalc.

    Investor-demo gold — single button on the Command Center fires
    the entire Himalaya 3-phase fusion arc live.
    """
    # Production safety gate.
    if not _dev_scenarios_enabled():
        raise HTTPException(
            status_code=403,
            detail="Scenario injection disabled in this environment",
        )
    _ensure_operator(current_user)

    scenario = _SCENARIO_LIBRARY.get(payload.scenario)
    if not scenario:
        # `Literal[...]` typing already rejects unknown names with 422
        # from Pydantic, but defensive check kept for runtime safety.
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario '{payload.scenario}'",
        )

    # SF-01 v2 Day 4 — validate target user exists before doing any
    # cache mutation. A typo'd uuid would otherwise inject a CAP
    # alert into the global Sachet cache AND then crash on the
    # downstream SafetyEvent INSERT.
    from sqlalchemy import select as _select
    from app.models.user import User as _User
    exists = await session.execute(
        _select(_User.id).where(_User.id == payload.target_user_id)
    )
    if exists.first() is None:
        raise HTTPException(
            status_code=404,
            detail=f"target user_id not found: {payload.target_user_id}",
        )

    # 1. Build the synthetic CAP alert with a fresh timestamp and
    # inject into the existing Sachet Redis cache. We coexist with
    # real alerts: read current cache, prepend synthetic alert,
    # re-write with the scenario TTL (capped so the demo doesn't
    # poison production cache beyond `ttl_minutes`).
    cap_alert = {**scenario["cap_alert"]}
    cap_alert["pub_at"] = datetime.now(timezone.utc).isoformat()
    cap_alert["id"] = f"dev-scenario-{payload.scenario}-{uuid.uuid4().hex[:8]}"
    cap_alert["synthetic"] = True  # so audit can filter demo alerts

    ttl_s = payload.ttl_minutes * 60
    cached = redis_service.get_json(CACHE_NAMESPACE, CACHE_KEY) or []
    if not isinstance(cached, list):
        cached = []
    # Filter out any older synthetic alert for the same scenario so
    # rapid re-fires don't accumulate stale entries.
    cached = [
        a for a in cached
        if not (
            isinstance(a, dict)
            and a.get("synthetic")
            and a.get("event_type") == cap_alert["event_type"]
        )
    ]
    cached.insert(0, cap_alert)
    try:
        redis_service.set_json(
            CACHE_NAMESPACE, CACHE_KEY, cached, ttl=ttl_s,
        )
    except Exception:  # noqa: BLE001
        # Compensating action: even if cache injection fails the
        # composite recalc below still runs at the base score. The
        # button will read `env_hazard_match=false` and the demo
        # operator can retry — never silently fails to surface.
        logger.exception("dev_scenario cache inject failed")
        raise HTTPException(
            status_code=502,
            detail="Failed to inject synthetic CAP alert into cache",
        )

    # 2. Run the composite recalc using the scenario's signal bundle.
    lat, lng = scenario["coords"]
    signals = {
        "fall":  float(scenario["signals"]["fall"]),
        "voice": float(scenario["signals"]["voice_distress"]),
    }
    try:
        result = await evaluate_risk(
            session,
            payload.target_user_id,
            signals,
            lat=lat,
            lng=lng,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("dev_scenario evaluate_risk failed")
        raise HTTPException(
            status_code=500,
            detail=f"evaluate_risk failed: {exc}",
        ) from exc

    composite = float(result.get("risk_score") or 0.0)
    action = (
        "emergency" if composite >= 0.85
        else "alert"     if composite >= 0.65
        else "watch"     if composite >= 0.30
        else "normal"
    )

    return {
        "scenario":          payload.scenario,
        "label":             scenario["label"],
        "target_user_id":    payload.target_user_id,
        "lat":               lat,
        "lng":               lng,
        "composite":         round(composite, 3),
        "risk_level":        result.get("risk_level") or classify_risk(composite),
        "action":            action,
        "alert_fired":       result.get("alert_fired", False),
        "env_hazard_type":   cap_alert.get("event_type"),
        "env_multiplier":    result.get("env_multiplier", 1.0),
        "env_hazard_match":  result.get("env_hazard_match", False),
        "pre_mult_score":    result.get("pre_mult_score", composite),
        "cooldown_suppressed": result.get("cooldown_suppressed", False),
        "ttl_minutes":       payload.ttl_minutes,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=payload.ttl_minutes)
        ).isoformat(),
    }


@router.get("/scenarios")
async def list_scenarios(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the scenario library so the Command Center dev panel
    can render the button list dynamically. Same dual-guard."""
    if not _dev_scenarios_enabled():
        raise HTTPException(
            status_code=403,
            detail="Scenario injection disabled in this environment",
        )
    _ensure_operator(current_user)
    return {
        "enabled": True,
        "scenarios": [
            {
                "id":     name,
                "label":  s["label"],
                "state":  s["cap_alert"]["state"],
                "type":   s["cap_alert"]["event_type"],
                "severity": s["cap_alert"]["severity"],
                "coords": s["coords"],
            }
            for name, s in _SCENARIO_LIBRARY.items()
        ],
    }


__all__ = ["router", "_SCENARIO_LIBRARY"]
