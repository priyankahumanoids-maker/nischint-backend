# Weather Service — Phase 4
#
# Wraps the OpenWeather Current Weather API. Provides:
#   - get_weather(lat, lng): real condition / temperature / wind / rain / visibility
#   - compute_weather_risk(weather): pure-function 0..1 risk + factor list
#
# Cached per ~1km grid in Redis (10-min TTL) so we never burn the free tier
# (60 req/min) on a busy fleet, and so multiple users in the same area share
# one upstream call.

import logging
import os
from typing import Optional

import httpx

from app.services import redis_service

logger = logging.getLogger(__name__)

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
REDIS_NAMESPACE = "weather"
REDIS_TTL_SECONDS = 600  # 10 minutes
HTTP_TIMEOUT = 4.0       # don't slow down the safety hot-path

# Risk thresholds — tuned conservatively to surface only meaningful weather risk.
# Output is bounded 0..1 and added to other environment factors.
RAIN_HEAVY_MM = 2.5     # > 2.5mm/h current rain → +0.20
VIS_LOW_M = 1500        # < 1.5km visibility → +0.30
VIS_VERY_LOW_M = 500    # < 500m → +0.50
WIND_HIGH_KMH = 50      # > 50km/h → +0.20
TEMP_EXTREME_LOW_C = 4  # < 4°C → +0.10 (heat/cold stress for vulnerable users)
TEMP_EXTREME_HIGH_C = 42  # > 42°C → +0.15

# Severe weather condition IDs from OpenWeather:
# https://openweathermap.org/weather-conditions
SEVERE_CONDITION_GROUPS = {
    "thunderstorm": "Thunderstorm — visibility & travel hazard",
    "tornado": "Tornado warning",
    "squall": "Squall — sudden wind",
}
SEVERE_CONDITION_ID_RANGES = [
    (200, 232, "thunderstorm", 0.40),  # All thunderstorm IDs
    (502, 504, "heavy_rain", 0.30),    # Heavy / extreme / very heavy rain
    (511, 511, "freezing_rain", 0.35), # Ice on roads
    (602, 602, "heavy_snow", 0.30),
    (771, 771, "squall", 0.35),
    (781, 781, "tornado", 0.95),       # Effectively maxes out the signal
]


def _cache_key(lat: float, lng: float) -> str:
    """Round to ~1km grid (3 decimals ≈ 110m, 2 decimals ≈ 1.1km)."""
    return f"{round(lat, 2)}_{round(lng, 2)}"


async def get_weather(
    lat: float,
    lng: float,
    *,
    timeout_s: float = HTTP_TIMEOUT,
) -> Optional[dict]:
    """
    Fetch current weather for (lat, lng). Returns a normalized dict on
    success, None when the provider key is missing or the request fails.

    `timeout_s` defaults to the hot-path budget (`HTTP_TIMEOUT = 4.0 s`).
    Background callers (fleet grid refresh) override to a generous
    budget so they don't time out simultaneously and poison the cache —
    same operational reflex shipped for the Sachet pre-warmer.
    """
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        try:
            from app.core.config import settings
            api_key = settings.openweather_api_key
        except Exception:
            api_key = ""
    if not api_key:
        return {"source": "unavailable", "error": "no_api_key"}

    cached = redis_service.get_json(REDIS_NAMESPACE, _cache_key(lat, lng))
    if cached:
        cached["from_cache"] = True
        return cached

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(
                OPENWEATHER_URL,
                params={"lat": lat, "lon": lng, "appid": api_key, "units": "metric"},
            )
        if resp.status_code != 200:
            logger.warning("[WEATHER] OpenWeather returned %s for (%.2f,%.2f)", resp.status_code, lat, lng)
            return {"source": "unavailable", "error": f"http_{resp.status_code}"}
        raw = resp.json()
    except httpx.TimeoutException:
        logger.warning("[WEATHER] timeout for (%.2f,%.2f)", lat, lng)
        return {"source": "unavailable", "error": "timeout"}
    except Exception as e:
        logger.warning("[WEATHER] fetch failed for (%.2f,%.2f): %s", lat, lng, e)
        return {"source": "unavailable", "error": "fetch_failed"}

    weather_arr = raw.get("weather") or []
    main = (weather_arr[0] or {}) if weather_arr else {}
    main_block = raw.get("main") or {}
    wind_block = raw.get("wind") or {}
    rain_block = raw.get("rain") or {}
    snow_block = raw.get("snow") or {}

    normalized = {
        "source": "openweather",
        "from_cache": False,
        "condition_id": main.get("id"),
        "condition": (main.get("main") or "").lower(),  # e.g. "clear", "rain", "thunderstorm"
        "description": main.get("description"),         # human readable
        "icon": main.get("icon"),
        "temp_c": main_block.get("temp"),
        "feels_like_c": main_block.get("feels_like"),
        "humidity_pct": main_block.get("humidity"),
        "visibility_m": raw.get("visibility"),
        "wind_kmh": round((wind_block.get("speed") or 0) * 3.6, 1),
        "wind_gust_kmh": round((wind_block.get("gust") or 0) * 3.6, 1) if wind_block.get("gust") else None,
        "rain_1h_mm": rain_block.get("1h") or 0.0,
        "snow_1h_mm": snow_block.get("1h") or 0.0,
        "city_name": raw.get("name"),
    }

    redis_service.set_json(REDIS_NAMESPACE, _cache_key(lat, lng), normalized, ttl=REDIS_TTL_SECONDS)
    return normalized


def compute_weather_risk(weather: Optional[dict]) -> tuple[float, list[str]]:
    """
    Pure function: maps a normalized weather payload to (risk_score, factors).
    Returns (0.0, []) when no weather is available.
    """
    if not weather or weather.get("source") != "openweather":
        return 0.0, []

    factors: list[str] = []
    score = 0.0

    cid = weather.get("condition_id") or 0
    for lo, hi, factor, contribution in SEVERE_CONDITION_ID_RANGES:
        if lo <= cid <= hi:
            score = max(score, contribution)
            if factor not in factors:
                factors.append(factor)
            break  # only one severe-condition group at a time

    rain = float(weather.get("rain_1h_mm") or 0)
    if rain >= RAIN_HEAVY_MM and "heavy_rain" not in factors:
        score += 0.20
        factors.append("heavy_rain")

    vis = weather.get("visibility_m")
    if isinstance(vis, (int, float)):
        if vis < VIS_VERY_LOW_M:
            score += 0.50
            factors.append("very_low_visibility")
        elif vis < VIS_LOW_M:
            score += 0.30
            factors.append("low_visibility")

    wind = float(weather.get("wind_kmh") or 0)
    if wind >= WIND_HIGH_KMH:
        score += 0.20
        factors.append("high_wind")

    temp = weather.get("temp_c")
    if isinstance(temp, (int, float)):
        if temp < TEMP_EXTREME_LOW_C:
            score += 0.10
            factors.append("extreme_cold")
        elif temp > TEMP_EXTREME_HIGH_C:
            score += 0.15
            factors.append("extreme_heat")

    return round(min(score, 1.0), 3), factors
