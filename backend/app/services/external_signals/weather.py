"""NISCH-012.0 — Weather provider adapter.

Wraps the existing `weather_service` (OpenWeather + Redis cache, 10-min
TTL) into the `ExternalSignalProvider` contract. Zero new HTTP code.

Maps `compute_weather_risk(weather)` → `ExternalSignal`:
  * `risk_0_1` = the float that risk function already returns
  * `factors`  = the same factor list, propagated verbatim
  * `signal_type` is derived from the dominant factor (or "weather"
    if no individual factor crossed)
  * `ttl_s` = 600 (matches the OpenWeather cache TTL — beyond this
    the consumer should consider the data stale)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from app.services import weather_service
from app.services.external_signals import (
    ExternalSignal, ExternalSignalProvider,
)


WEATHER_TTL_S = 600  # match weather_service.REDIS_TTL_SECONDS


def _signal_type_from_factors(factors: list[str]) -> str:
    """Pick a single dominant signal_type from the factor list.

    Order is severity-first — when multiple factors fire we want the
    audit trail to show the *most actionable* one as the headline."""
    priority = [
        "tornado", "thunderstorm", "freezing_rain",
        "heavy_snow", "very_low_visibility", "heavy_rain",
        "squall", "extreme_heat", "high_wind",
        "low_visibility", "extreme_cold",
    ]
    for p in priority:
        if p in factors:
            return p
    return "weather"


class WeatherProvider(ExternalSignalProvider):
    name = "weather"

    def is_enabled(self) -> bool:
        # Same env path the underlying service uses.
        if os.environ.get("OPENWEATHER_API_KEY"):
            return True
        try:
            from app.core.config import settings
            return bool(getattr(settings, "openweather_api_key", ""))
        except Exception:
            return False

    async def _fetch_unsafe(
        self, lat: float, lng: float,
        when: Optional[datetime] = None,
    ) -> Optional[ExternalSignal]:
        weather = await weather_service.get_weather(lat, lng)
        if not weather or weather.get("source") != "openweather":
            # `unavailable` source (no key, timeout, http err, etc.) is
            # a real "no signal" answer, not an exception.
            return None
        risk, factors = weather_service.compute_weather_risk(weather)
        if risk <= 0:
            return None
        return ExternalSignal(
            provider=self.name,
            signal_type=_signal_type_from_factors(factors),
            risk_0_1=float(risk),
            factors=list(factors),
            confidence=0.90,  # OpenWeather current conditions are reliable
            fetched_at=datetime.now(timezone.utc),
            ttl_s=WEATHER_TTL_S,
            raw_url=None,     # weather has no per-event linkback URL
        )


__all__ = ["WeatherProvider", "WEATHER_TTL_S"]
