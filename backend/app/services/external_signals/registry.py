"""NISCH-012.0 — Provider registry + parallel fetcher.

Owns:
  * The list of registered providers (only WeatherProvider in 12.0).
  * The hard-timeout fan-out (`PROVIDER_TIMEOUT_S = 1.5`).
  * The fail-quiet boundary — any single provider raising or timing
    out becomes a logged drop, never propagates.

The alert pipeline calls ONE function: `fetch_all_signals(lat, lng)`.
Worst-case latency budget on the alert hot-path is bounded at
`PROVIDER_TIMEOUT_S` because all providers run concurrently.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.services.external_signals import (
    PROVIDER_TIMEOUT_S, ExternalSignal, ExternalSignalProvider,
)
from app.services.external_signals.sachet_provider import SachetSignalProvider
from app.services.external_signals.tomtom_provider import TomTomSignalProvider
from app.services.external_signals.news_provider import NewsSignalProvider
from app.services.external_signals.weather import WeatherProvider
from app.services.external_signals.owm_alerts_provider import OWMAlertsSignalProvider

logger = logging.getLogger(__name__)


# Single canonical list. Adding a provider in a later phase = one line
# here + one new module file. No other changes.
#
# `NewsSignalProvider` short-circuits internally via `is_enabled()`
# when `EXTERNAL_SIGNAL_NEWS_ENABLED` is not set — the registry
# stays unconditional so flipping the flag is a no-restart change.
#
# `OWMAlertsSignalProvider` is the OneCall 3.0 severe-alert channel
# (REL-09). SACHET stays primary/authoritative for India; OWM is
# additive (same fan-out shape as TomTom / News). NO priority
# inversion — both providers' signals blend through
# `apply_external_modifiers` exactly like every other supplementary
# source.
_PROVIDERS: list[ExternalSignalProvider] = [
    WeatherProvider(),
    SachetSignalProvider(),
    TomTomSignalProvider(),
    NewsSignalProvider(),
    OWMAlertsSignalProvider(),
]


async def _safe_fetch(
    provider: ExternalSignalProvider,
    lat: float, lng: float,
    when: Optional[datetime] = None,
) -> Optional[ExternalSignal]:
    """Wrap `_fetch_unsafe()` in:
      1. Hard timeout (PROVIDER_TIMEOUT_S)
      2. Exception swallow (logs at debug; alert path never sees it)
      3. is_enabled() short-circuit (no log noise for absent keys)
    """
    if not provider.is_enabled():
        return None
    try:
        return await asyncio.wait_for(
            provider._fetch_unsafe(lat, lng, when),
            timeout=PROVIDER_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[EXTERNAL_SIGNAL] %s timed out after %.1fs at (%.3f,%.3f)",
            provider.name, PROVIDER_TIMEOUT_S, lat, lng,
        )
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[EXTERNAL_SIGNAL] %s raised at (%.3f,%.3f): %r",
            provider.name, lat, lng, e,
        )
        return None


async def fetch_all_signals(
    lat: float, lng: float,
    when: Optional[datetime] = None,
) -> list[ExternalSignal]:
    """Concurrent fan-out across every enabled provider.

    Empty list when nothing has anything to say. Never raises."""
    if lat is None or lng is None:
        return []
    coros = [_safe_fetch(p, lat, lng, when) for p in _PROVIDERS]
    if not coros:
        return []
    results = await asyncio.gather(*coros, return_exceptions=False)
    return [r for r in results if r is not None]


# Test-only seam: lets `tests/` swap the registry list without
# monkeypatching internals.
def _set_providers_for_test(providers: list[ExternalSignalProvider]) -> None:
    global _PROVIDERS
    _PROVIDERS = list(providers)


def _reset_providers_to_default() -> None:
    global _PROVIDERS
    _PROVIDERS = [
        WeatherProvider(),
        SachetSignalProvider(),
        TomTomSignalProvider(),
        NewsSignalProvider(),
        OWMAlertsSignalProvider(),
    ]


__all__ = [
    "fetch_all_signals",
    "_set_providers_for_test",
    "_reset_providers_to_default",
]
