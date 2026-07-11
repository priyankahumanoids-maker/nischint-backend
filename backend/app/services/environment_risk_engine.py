# Environmental Risk AI Engine
# Evaluates environmental hazards using OpenWeatherMap API
# (weather + air pollution) and converts them into safety signals.
#
# 5-factor model: heat index, air quality, rain risk, wind risk, UV risk
# Score range: 0 (safe) to 10 (extreme risk)
# Cache TTL: 30 minutes per location grid cell

import os
import logging
import httpx
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

OPENWEATHER_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
CACHE_TTL_MINUTES = 30

# Risk weights
W_HEAT = 0.30
W_AIR = 0.25
W_RAIN = 0.20
W_WIND = 0.15
W_UV = 0.10

# Cache: grid-cell key → (timestamp, data)
_weather_cache: dict[str, tuple[datetime, dict]] = {}
_air_cache: dict[str, tuple[datetime, dict]] = {}


def _grid_key(lat: float, lng: float) -> str:
    """Round to ~1km grid cells for caching."""
    return f"{round(lat, 2)},{round(lng, 2)}"


async def _fetch_weather(lat: float, lng: float) -> dict:
    """Fetch current weather from OpenWeatherMap with caching."""
    key = _grid_key(lat, lng)
    now = datetime.now(timezone.utc)
    if key in _weather_cache:
        ts, data = _weather_cache[key]
        if (now - ts).total_seconds() < CACHE_TTL_MINUTES * 60:
            return data

    if not OPENWEATHER_KEY:
        return _fallback_weather(lat, lng)

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"lat": lat, "lon": lng, "appid": OPENWEATHER_KEY, "units": "metric"},
            )
            resp.raise_for_status()
            data = resp.json()
            _weather_cache[key] = (now, data)
            return data
    except Exception as e:
        logger.warning(f"OpenWeather API error: {e}")
        return _fallback_weather(lat, lng)


async def _fetch_air_quality(lat: float, lng: float) -> dict:
    """Fetch air pollution data from OpenWeatherMap with caching."""
    key = _grid_key(lat, lng)
    now = datetime.now(timezone.utc)
    if key in _air_cache:
        ts, data = _air_cache[key]
        if (now - ts).total_seconds() < CACHE_TTL_MINUTES * 60:
            return data

    if not OPENWEATHER_KEY:
        return _fallback_air()

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/2.5/air_pollution",
                params={"lat": lat, "lon": lng, "appid": OPENWEATHER_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
            _air_cache[key] = (now, data)
            return data
    except Exception as e:
        logger.warning(f"OpenWeather Air API error: {e}")
        return _fallback_air()


def _fallback_weather(lat, lng):
    """Realistic simulated weather based on location and time of day."""
    import hashlib
    # Deterministic but varied per location grid
    seed = int(hashlib.md5(f"{round(lat,1)},{round(lng,1)}".encode()).hexdigest()[:8], 16)
    hour = datetime.now(timezone.utc).hour

    # Base temp varies by latitude and hour
    base_temp = 30 - abs(lat - 12) * 0.5  # Warmer near equator
    if 22 <= hour or hour <= 5:
        base_temp -= 5
    elif 10 <= hour <= 15:
        base_temp += 3

    temp = round(base_temp + (seed % 10) - 5, 1)
    humidity = 40 + (seed % 40)
    wind = round(2 + (seed % 8) * 0.5, 1)
    clouds = (seed % 80)

    conditions = ["clear sky", "few clouds", "scattered clouds", "broken clouds", "overcast clouds"]
    condition = conditions[seed % len(conditions)]

    # Bangalore area name
    areas = ["Bangalore", "Koramangala", "Indiranagar", "Whitefield", "Electronic City",
             "Jayanagar", "HSR Layout", "Marathahalli", "Bellandur", "Hebbal"]
    area = areas[seed % len(areas)]

    rain_1h = 0
    if clouds > 60 and seed % 3 == 0:
        rain_1h = round((seed % 15) * 0.5, 1)
        condition = "light rain" if rain_1h < 3 else "moderate rain"

    return {
        "main": {"temp": temp, "feels_like": round(temp + 2 + humidity * 0.02, 1), "humidity": humidity},
        "wind": {"speed": wind, "gust": round(wind * 1.5, 1)},
        "weather": [{"main": condition.split()[0].capitalize(), "description": condition}],
        "rain": {"1h": rain_1h} if rain_1h > 0 else {},
        "clouds": {"all": clouds},
        "name": area,
    }


def _fallback_air():
    """Simulated air quality data for demo."""
    import hashlib
    seed = int(hashlib.md5(datetime.now(timezone.utc).strftime("%Y%m%d%H").encode()).hexdigest()[:8], 16)
    aqi = 2 + (seed % 3)  # 2-4
    pm25 = 15 + (seed % 60)
    pm10 = 30 + (seed % 80)
    return {"list": [{"main": {"aqi": aqi}, "components": {"pm2_5": pm25, "pm10": pm10, "no2": 20 + seed % 30, "o3": 40 + seed % 50}}]}


# ── Risk Scoring ──

def _compute_heat_risk(weather: dict) -> tuple[float, list[str]]:
    """Score 0-1 based on temperature and feels-like."""
    main = weather.get("main", {})
    temp = main.get("temp", 25)
    feels = main.get("feels_like", temp)
    humidity = main.get("humidity", 50)

    # Use feels-like as primary
    effective = max(temp, feels)
    factors = []

    if effective >= 42:
        score = 1.0
        factors.append(f"Extreme heat: {effective:.0f}°C (feels like)")
    elif effective >= 38:
        score = 0.8
        factors.append(f"Heatwave conditions: {effective:.0f}°C")
    elif effective >= 35:
        score = 0.6
        factors.append(f"High temperature: {effective:.0f}°C")
    elif effective >= 30:
        score = 0.3
        factors.append(f"Warm: {effective:.0f}°C")
    elif effective <= 5:
        score = 0.7
        factors.append(f"Cold conditions: {effective:.0f}°C")
    elif effective <= 10:
        score = 0.4
        factors.append(f"Cool: {effective:.0f}°C")
    else:
        score = 0.1

    if humidity >= 85:
        score = min(1.0, score + 0.15)
        factors.append(f"High humidity: {humidity}%")

    return score, factors


def _compute_air_risk(air: dict) -> tuple[float, list[str]]:
    """Score 0-1 based on AQI and pollutant levels."""
    items = air.get("list", [{}])
    if not items:
        return 0, []
    entry = items[0]
    aqi = entry.get("main", {}).get("aqi", 1)  # 1-5 scale
    comps = entry.get("components", {})
    pm25 = comps.get("pm2_5", 0)
    pm10 = comps.get("pm10", 0)

    factors = []
    # AQI: 1=Good, 2=Fair, 3=Moderate, 4=Poor, 5=Very Poor
    aqi_map = {1: 0.05, 2: 0.2, 3: 0.45, 4: 0.7, 5: 1.0}
    score = aqi_map.get(aqi, 0.3)

    aqi_labels = {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}
    if aqi >= 3:
        factors.append(f"AQI: {aqi_labels.get(aqi, '?')} (Level {aqi})")
    if pm25 > 50:
        factors.append(f"PM2.5: {pm25:.0f} µg/m³")
    if pm10 > 100:
        factors.append(f"PM10: {pm10:.0f} µg/m³")

    return score, factors


def _compute_rain_risk(weather: dict) -> tuple[float, list[str]]:
    """Score 0-1 based on precipitation."""
    rain = weather.get("rain", {})
    rain_1h = rain.get("1h", 0)
    rain_3h = rain.get("3h", 0)
    conditions = [w.get("main", "") for w in weather.get("weather", [])]
    factors = []

    if rain_1h > 20 or "Thunderstorm" in conditions:
        score = 1.0
        factors.append(f"Heavy rain/storm: {rain_1h:.1f} mm/h")
    elif rain_1h > 7:
        score = 0.7
        factors.append(f"Moderate rain: {rain_1h:.1f} mm/h")
    elif rain_1h > 2 or "Rain" in conditions or "Drizzle" in conditions:
        score = 0.4
        label = f"{rain_1h:.1f} mm/h" if rain_1h > 0 else "light"
        factors.append(f"Rain: {label}")
    elif rain_3h > 5:
        score = 0.3
        factors.append(f"Recent rain: {rain_3h:.1f} mm/3h")
    else:
        score = 0.0

    return score, factors


def _compute_wind_risk(weather: dict) -> tuple[float, list[str]]:
    """Score 0-1 based on wind speed (m/s)."""
    wind = weather.get("wind", {})
    speed = wind.get("speed", 0)
    gust = wind.get("gust", speed)
    factors = []

    effective = max(speed, gust)
    if effective >= 25:
        score = 1.0
        factors.append(f"Dangerous winds: {effective:.0f} m/s")
    elif effective >= 15:
        score = 0.7
        factors.append(f"Strong winds: {effective:.0f} m/s")
    elif effective >= 10:
        score = 0.4
        factors.append(f"Moderate winds: {effective:.0f} m/s")
    else:
        score = 0.1

    return score, factors


def _compute_uv_risk(weather: dict) -> tuple[float, list[str]]:
    """Estimate UV risk from cloud cover and time of day."""
    clouds = weather.get("clouds", {}).get("all", 50)
    now_hour = datetime.now(timezone.utc).hour
    factors = []

    # Peak UV hours 10-15
    if 10 <= now_hour <= 15:
        base_uv = 8 * (1 - clouds / 100 * 0.6)
    elif 8 <= now_hour <= 17:
        base_uv = 5 * (1 - clouds / 100 * 0.6)
    else:
        base_uv = 1

    if base_uv >= 8:
        score = 0.9
        factors.append(f"UV index extreme (~{base_uv:.0f})")
    elif base_uv >= 6:
        score = 0.6
        factors.append(f"High UV index (~{base_uv:.0f})")
    elif base_uv >= 3:
        score = 0.3
    else:
        score = 0.05

    return score, factors


# ── Main API ──

async def evaluate_environment_risk(lat: float, lng: float) -> dict:
    """Evaluate environmental risk for a location using live weather data."""
    weather = await _fetch_weather(lat, lng)
    air = await _fetch_air_quality(lat, lng)

    heat_score, heat_factors = _compute_heat_risk(weather)
    air_score, air_factors = _compute_air_risk(air)
    rain_score, rain_factors = _compute_rain_risk(weather)
    wind_score, wind_factors = _compute_wind_risk(weather)
    uv_score, uv_factors = _compute_uv_risk(weather)

    raw = (
        W_HEAT * heat_score
        + W_AIR * air_score
        + W_RAIN * rain_score
        + W_WIND * wind_score
        + W_UV * uv_score
    ) * 10.0
    env_score = round(min(10.0, max(0.0, raw)), 1)

    risk_level = (
        "Critical" if env_score >= 7
        else "High" if env_score >= 5
        else "Moderate" if env_score >= 3
        else "Safe"
    )

    all_factors = heat_factors + air_factors + rain_factors + wind_factors + uv_factors
    if not all_factors:
        all_factors = ["No significant environmental risks"]

    # Extract weather details
    main = weather.get("main", {})
    wind_data = weather.get("wind", {})
    air_entry = (air.get("list") or [{}])[0]
    aqi = air_entry.get("main", {}).get("aqi", 1)
    comps = air_entry.get("components", {})
    conditions = weather.get("weather", [{}])
    cond_desc = conditions[0].get("description", "clear") if conditions else "clear"

    # Recommendations
    recommendations = _generate_recommendations(
        env_score, heat_score, air_score, rain_score, wind_score, uv_score,
        main.get("temp", 25), aqi
    )

    return {
        "location": weather.get("name", f"({lat:.2f}, {lng:.2f})"),
        "latitude": lat,
        "longitude": lng,
        "environment_score": env_score,
        "risk_level": risk_level,
        "factors": all_factors,
        "recommendations": recommendations,
        "breakdown": {
            "heat_index": round(heat_score * 10, 1),
            "air_pollution": round(air_score * 10, 1),
            "rain_risk": round(rain_score * 10, 1),
            "wind_risk": round(wind_score * 10, 1),
            "uv_risk": round(uv_score * 10, 1),
        },
        "weather": {
            "temperature": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "humidity": main.get("humidity"),
            "condition": cond_desc,
            "wind_speed": wind_data.get("speed"),
            "wind_gust": wind_data.get("gust"),
            "clouds": weather.get("clouds", {}).get("all"),
            "rain_1h": weather.get("rain", {}).get("1h", 0),
        },
        "air_quality": {
            "aqi": aqi,
            "aqi_label": {1: "Good", 2: "Fair", 3: "Moderate", 4: "Poor", 5: "Very Poor"}.get(aqi, "Unknown"),
            "pm2_5": comps.get("pm2_5"),
            "pm10": comps.get("pm10"),
            "no2": comps.get("no2"),
            "o3": comps.get("o3"),
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_recommendations(
    env_score, heat, air, rain, wind, uv, temp, aqi
) -> list[str]:
    recs = []
    if heat >= 0.6:
        recs.append("Hydrate frequently and seek shade")
    if heat >= 0.8:
        recs.append("Avoid outdoor activity during peak hours")
    if air >= 0.5:
        recs.append("Wear a mask outdoors")
    if air >= 0.7:
        recs.append("Avoid outdoor activity — poor air quality")
    if rain >= 0.5:
        recs.append("Carry umbrella, avoid low-lying areas")
    if rain >= 0.8:
        recs.append("Seek shelter — heavy rain/storm")
    if wind >= 0.5:
        recs.append("Be cautious of strong winds")
    if uv >= 0.6:
        recs.append("Apply sunscreen, wear protective clothing")
    if temp <= 5:
        recs.append("Bundle up — risk of hypothermia")
    if not recs:
        recs.append("Conditions are favorable for outdoor activity")
    return recs


async def get_fleet_environment_status(session: AsyncSession) -> list[dict]:
    """Get environmental risk for all tracked devices (concurrent)."""
    import asyncio

    devices = (await session.execute(text("""
        SELECT dl.device_id, d.device_identifier, dl.latitude, dl.longitude
        FROM device_locations dl
        JOIN devices d ON dl.device_id = d.id
    """))).fetchall()

    async def _eval_device(dev):
        risk = await evaluate_environment_risk(dev.latitude, dev.longitude)
        return {
            "device_id": str(dev.device_id),
            "device_identifier": dev.device_identifier,
            "lat": dev.latitude,
            "lng": dev.longitude,
            "environment_score": risk["environment_score"],
            "risk_level": risk["risk_level"],
            "factors": risk["factors"][:3],
            "weather": risk["weather"],
            "air_quality": risk["air_quality"],
            "recommendations": risk["recommendations"][:2],
        }

    results = await asyncio.gather(*[_eval_device(d) for d in devices])
    results = sorted(results, key=lambda x: x["environment_score"], reverse=True)
    return results
