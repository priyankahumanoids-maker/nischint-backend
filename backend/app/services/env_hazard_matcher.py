"""SF-01 v2 Day 3 — Phase 3 env hazard matcher.

Looks up whether a given (lat, lng) falls into any active NDMA / Sachet
hazard zone OR any OpenWeather red-flag (severe-weather) area. Returns
a structured `EnvHazardMatch` the safety brain can consume:

  * `matched`: bool — true when at least one active hazard overlaps
  * `multiplier`: float — `ENV_HAZARD_MULTIPLIER` if matched, else 1.0
  * `hazards`: list[dict] — each hazard's source / severity / type
  * `strongest`: dict | None — single highest-severity hazard
  * `state`: str | None — resolved Indian state (for telemetry)

State-box matching is the v1 implementation (PostGIS deferred to
SF-02). For Sachet/NDMA the state-box approach is accurate enough —
NDMA's RSS feed is itself state-scoped. For OpenWeather we re-use the
weather_service red-flag classifier.

Read-only. Never raises — degrades silently to `matched=False` on
any provider failure so the safety brain's composite recalc never
blocks on Phase 3 hiccups.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services.external_signals.sachet_provider import (
    SEVERITY_RISK,
    get_alerts_cached,
    pick_strongest,
    resolve_state,
    resolve_state_async,
)

logger = logging.getLogger(__name__)


# Locked at the safety_brain_service value via re-export — kept here
# so this module is self-describing.
ENV_HAZARD_MULTIPLIER = 1.30

# OpenWeather red-flag thresholds — when reached, treated as a hazard
# match even if NDMA has not issued an alert yet. Conservative bounds
# so we don't over-fire on a windy afternoon.
WEATHER_RED_FLAG_WIND_KMH = 60.0
WEATHER_RED_FLAG_RAIN_MM_3H = 50.0
WEATHER_RED_FLAG_TEMP_C_HIGH = 45.0
WEATHER_RED_FLAG_TEMP_C_LOW = 2.0


async def _match_sachet(lat: float, lng: float) -> list[dict]:
    """Return Sachet alerts active for the resolved state, or []."""
    state = await resolve_state_async(lat, lng)
    if not state:
        return []
    try:
        alerts = await get_alerts_cached()
    except Exception:  # noqa: BLE001
        logger.debug("env_hazard sachet fetch failed", exc_info=True)
        return []
    state_alerts = [a for a in alerts if a.get("state") == state]
    return state_alerts


def _match_weather_red_flag(weather: Optional[dict]) -> Optional[dict]:
    """Convert a weather snapshot into a hazard dict if any
    threshold is breached. None otherwise."""
    if not weather:
        return None
    wind  = float(weather.get("wind_kmh") or 0.0)
    rain  = float(weather.get("rain_3h_mm") or weather.get("rain_mm") or 0.0)
    temp  = float(weather.get("temp_c") or weather.get("temperature") or 20.0)
    triggers = []
    if wind >= WEATHER_RED_FLAG_WIND_KMH:
        triggers.append(("wind", "severe", SEVERITY_RISK["severe"]))
    if rain >= WEATHER_RED_FLAG_RAIN_MM_3H:
        triggers.append(("rain", "severe", SEVERITY_RISK["severe"]))
    if temp >= WEATHER_RED_FLAG_TEMP_C_HIGH:
        triggers.append(("heatwave", "moderate", SEVERITY_RISK["moderate"]))
    if temp <= WEATHER_RED_FLAG_TEMP_C_LOW:
        triggers.append(("coldwave", "moderate", SEVERITY_RISK["moderate"]))
    if not triggers:
        return None
    kind, sev, risk = max(triggers, key=lambda t: t[2])
    return {
        "source":   "openweather",
        "type":     kind,
        "severity": sev,
        "risk":     risk,
        "title":    f"{kind} red flag",
    }


async def match_env_hazards(
    lat: Optional[float],
    lng: Optional[float],
    weather: Optional[dict] = None,
) -> dict:
    """Return the EnvHazardMatch envelope for a (lat,lng) ± weather."""
    if lat is None or lng is None:
        return {
            "matched": False,
            "multiplier": 1.0,
            "hazards": [],
            "strongest": None,
            "state": None,
        }
    state = await resolve_state_async(lat, lng)
    hazards: list[dict] = []

    # 1. NDMA / Sachet polygon-ish match (state bbox v1).
    sachet_hits = await _match_sachet(lat, lng)
    for h in sachet_hits:
        hazards.append({
            "source":   "ndma_sachet",
            "type":     (h.get("event_type") or "alert").lower(),
            "severity": (h.get("severity") or "unknown").lower(),
            "risk":     SEVERITY_RISK.get(
                (h.get("severity") or "unknown").lower(), 0.3,
            ),
            "title":    h.get("title"),
        })

    # 2. OpenWeather red-flag check — independent of NDMA so a
    # forming storm fires even if the CAP feed hasn't caught up.
    weather_match = _match_weather_red_flag(weather)
    if weather_match:
        hazards.append(weather_match)

    # 3. Strongest = highest risk number.
    strongest = max(hazards, key=lambda h: h["risk"]) if hazards else None

    return {
        "matched":    bool(hazards),
        "multiplier": ENV_HAZARD_MULTIPLIER if hazards else 1.0,
        "hazards":    hazards,
        "strongest":  strongest,
        "state":      state,
    }


__all__ = [
    "match_env_hazards",
    "ENV_HAZARD_MULTIPLIER",
    "WEATHER_RED_FLAG_WIND_KMH",
    "WEATHER_RED_FLAG_RAIN_MM_3H",
    "WEATHER_RED_FLAG_TEMP_C_HIGH",
    "WEATHER_RED_FLAG_TEMP_C_LOW",
]
# Re-exported for `pick_strongest` test parity.
_ = pick_strongest  # noqa: F841
