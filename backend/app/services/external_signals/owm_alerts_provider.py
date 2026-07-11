"""REL-09 Step 2 — OpenWeatherMap OneCall 3.0 severe-alert provider.

A NEW upstream channel (the existing per-request `WeatherProvider`
in `weather.py` is deliberately untouched per the user's spec —
this module sits alongside, never replaces it).

Source of truth:
  * `https://api.openweathermap.org/data/3.0/onecall` — the paid
    OneCall 3.0 endpoint. The `alerts` array carries IMD / NDMA /
    OWM-curated severe weather alerts including tornado, cyclone,
    flood, thunderstorm, snowstorm, heat-wave, dust-storm.

Why a separate file from `weather.py`:
  * `weather.py` is on the alert HOT PATH — every safety risk
    evaluation hits it. We must not change its semantics.
  * OneCall 3.0 alerts run on a DIFFERENT cycle (15 min / 6 metros
    via a background prewarmer) and ADD to the registry as a
    supplementary signal sitting alongside SACHET (SACHET stays
    primary/authoritative; OWM is additive — same shape as the
    existing additive providers, NO priority inversion).

Defensive contracts (locked):
  * `is_enabled()` returns False when `OPENWEATHER_API_KEY` is unset
    — the registry never registers it, the scheduler never wakes
    the prewarmer.
  * 401 / 403 from OneCall 3.0 mean "key not activated for this
    tier yet". The user activates separately on the OWM dashboard.
    These responses log to Sentry as warnings (channel=onecall_alerts)
    and the cache is preserved → the existing per-request
    `WeatherProvider` keeps serving current-conditions risk.
  * 429 (quota) and 5xx (transient) → log to Sentry, preserve cache.
  * Any exception → fail-quiet, log to Sentry, return [].

Severity filter:
  * OWM alerts carry no canonical severity field; we infer from the
    `event` string + `tags` array using the SACHET-style keyword
    grid. Only `severity >= moderate` is surfaced. Minor headlines
    are dropped to avoid operator fatigue.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.services import redis_service
from app.services.external_signals import (
    ExternalSignal, ExternalSignalProvider,
)

logger = logging.getLogger(__name__)


# ── Tunables (locked) ────────────────────────────────────────────
ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"
CACHE_NAMESPACE = "owm_alerts"
CACHE_KEY = "alerts_by_metro_v1"
CACHE_TTL_S = 1800           # 30-min Redis cache — prewarmer fires every 15 min,
                             # 30 min keeps last-known state through one missed cycle
SIGNAL_TTL_S = 3600          # 1-hour decay on emitted signal (matches OWM's
                             # typical alert validity window)
HTTP_TIMEOUT_S = 2.0         # generous — prewarmer is background, not hot path
PREWARMER_TIMEOUT_S = 8.0    # outer budget for the prewarmer cycle

# 6 Indian metros — user-spec'd. Reused city slugs match
# `INDIAN_CITY_CENTROIDS` in news_provider for cross-system zone
# alignment. Coordinates are city-centre centroids.
METROS: tuple[tuple[str, float, float], ...] = (
    ("mumbai",    19.0760, 72.8777),
    ("delhi",     28.6139, 77.2090),
    ("bengaluru", 12.9716, 77.5946),
    ("chennai",   13.0827, 80.2707),
    ("hyderabad", 17.3850, 78.4867),
    ("kolkata",   22.5726, 88.3639),
)

# Maximum distance (km) from a metro centroid for a user's location
# to count as "in the metro's alert zone". 75 km matches the
# `NEWS_ZONE_RADIUS_KM` used by the news provider.
METRO_ZONE_RADIUS_KM = 75.0

SEVERITY_RISK: dict[str, float] = {
    "extreme":  0.95,
    "severe":   0.80,
    "moderate": 0.50,
    "minor":    0.30,
}

_SEVERITY_RANK: dict[str, int] = {
    "extreme":  4,
    "severe":   3,
    "moderate": 2,
    "minor":    1,
}

# Severity inference grid — mirrors the SACHET keyword grid so a
# single operator filter applies to BOTH NDMA RSS and OWM OneCall
# alerts. Order matters: most-actionable-first wins on multi-match.
_EXTREME_KEYWORDS: tuple[str, ...] = (
    "tornado", "cyclone", "tsunami", "extreme", "hurricane",
)
_SEVERE_KEYWORDS: tuple[str, ...] = (
    "severe", "heavy rain", "heatwave", "heat wave",
    "flood", "storm surge", "thunderstorm warning",
    "snow storm", "dust storm", "duststorm",
)
_MODERATE_KEYWORDS: tuple[str, ...] = (
    "thunderstorm", "lightning", "gusty wind",
    "moderate", "rain warning", "squall",
)


# ── Pure helpers (unit-tested) ────────────────────────────────────


def _api_key() -> str:
    """Read at request time so a hot-rotated key takes effect without
    a restart. Same env as the existing `WeatherProvider`."""
    return (os.environ.get("OPENWEATHER_API_KEY") or "").strip()


def infer_severity(event: str, tags: Optional[list[str]] = None) -> str:
    """Best-effort severity inference from the OWM alert `event` +
    `tags` array. Returns one of: extreme | severe | moderate | minor.

    OWM does not carry CAP severity in OneCall 3.0 — only an
    `event` headline string and a `tags` list. The keyword grid is
    duplicated from SACHET's `infer_severity` ON PURPOSE so a single
    Sentry filter against `severity_inferred` applies to both
    NDMA and OWM."""
    pieces = []
    if event:
        pieces.append(event.lower())
    for t in tags or []:
        if isinstance(t, str):
            pieces.append(t.lower())
    if not pieces:
        return "minor"
    blob = " ".join(pieces)
    for kw in _EXTREME_KEYWORDS:
        if kw in blob:
            return "extreme"
    for kw in _SEVERE_KEYWORDS:
        if kw in blob:
            return "severe"
    for kw in _MODERATE_KEYWORDS:
        if kw in blob:
            return "moderate"
    return "minor"


def parse_alerts(payload: dict | None, metro: str) -> list[dict]:
    """Project OneCall 3.0 `alerts[]` down to the canonical envelope
    every downstream consumer reads.

    Returns [] when:
      * payload shape is unexpected (fail-quiet contract)
      * the `alerts` array is missing / empty (no severe alerts)
      * every alert is below the moderate threshold (noise filter)
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("alerts") or []
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        event = (a.get("event") or "").strip()
        if not event:
            continue
        tags = a.get("tags") if isinstance(a.get("tags"), list) else []
        sev = infer_severity(event, tags)
        # Severity filter — user-spec'd `>= moderate`.
        if _SEVERITY_RANK.get(sev, 0) < _SEVERITY_RANK["moderate"]:
            continue
        out.append({
            "metro":         metro,
            "event":         event,
            "severity":      sev,
            "sender":        (a.get("sender_name") or "").strip() or None,
            "tags":          list(tags),
            "start":         a.get("start"),
            "end":           a.get("end"),
            "description":   (a.get("description") or "").strip()[:500] or None,
        })
    return out


def pick_strongest(alerts: list[dict]) -> Optional[dict]:
    """Highest-severity alert in the list, or None."""
    if not alerts:
        return None
    sorted_ = sorted(
        alerts,
        key=lambda a: -_SEVERITY_RANK.get(a.get("severity", "minor"), 0),
    )
    return sorted_[0]


def _haversine_km(lat1: float, lng1: float,
                  lat2: float, lng2: float) -> float:
    """Plain haversine for the 75 km zone radius check."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def nearest_metro(lat: float, lng: float,
                  radius_km: float = METRO_ZONE_RADIUS_KM,
                  ) -> Optional[str]:
    """Return the closest metro slug within `radius_km`, else None."""
    if lat is None or lng is None:
        return None
    best_slug: Optional[str] = None
    best_dist = radius_km
    for slug, mlat, mlng in METROS:
        d = _haversine_km(lat, lng, mlat, mlng)
        if d <= best_dist:
            best_dist = d
            best_slug = slug
    return best_slug


# ── HTTP layer ────────────────────────────────────────────────────


async def _fetch_one(client: httpx.AsyncClient,
                     metro: str, lat: float, lng: float) -> Optional[list[dict]]:
    """Single metro probe. Returns:
      * `[]`   → 200 with no alerts (success, no signal).
      * `list` → 200 with ≥1 alert at moderate+ severity.
      * `None` → fetch failed (401/403/429/5xx/exception). Caller
        treats None as "preserve cache, don't widen the merge".

    Defensive on 401/403 (OneCall 3.0 not activated yet on the
    OWM dashboard) — Sentry warning + None return, cache preserved.
    """
    import time as _time
    t0 = _time.monotonic()
    try:
        resp = await client.get(
            ONECALL_URL,
            params={
                "lat":     f"{lat}",
                "lon":     f"{lng}",
                "exclude": "minutely,hourly,daily",
                "units":   "metric",
                "appid":   _api_key(),
            },
            headers={"User-Agent": "nischint-safety/1.0"},
        )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (_time.monotonic() - t0) * 1000.0
        logger.warning("[OWM_ALERTS] metro=%s fetch failed: %r", metro, e)
        try:
            from app.services.external_signals.weather_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=None,
                upstream_url=ONECALL_URL,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=repr(e)[:280],
                channel="onecall_alerts",
                metro=metro,
            )
        except Exception:  # pragma: no cover
            pass
        return None
    elapsed_ms = (_time.monotonic() - t0) * 1000.0
    if resp.status_code != 200:
        # 401/403 = OneCall 3.0 tier not activated yet. Defensive,
        # not a system failure. Warning-only + cache preserved.
        logger.warning(
            "[OWM_ALERTS] metro=%s HTTP %s rt=%.1fms",
            metro, resp.status_code, elapsed_ms,
        )
        try:
            from app.services.external_signals.weather_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=resp.status_code,
                upstream_url=ONECALL_URL,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=None,
                channel="onecall_alerts",
                metro=metro,
            )
        except Exception:
            pass
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    return parse_alerts(body, metro)


async def fetch_all_metros() -> dict[str, list[dict]]:
    """Probe every monitored metro in parallel. Returns a dict
    keyed by metro slug. A metro key is present ONLY when the
    fetch succeeded (200 OK) — failed metros are dropped from the
    returned dict so the cache merge can preserve their last-known
    state. NEVER raises.

    When `OPENWEATHER_API_KEY` is unset → returns {} (caller treats
    empty dict as "no signal here", same as a clean 200/zero-alerts
    response across the board)."""
    if not _api_key():
        return {}
    out: dict[str, list[dict]] = {}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            results = await asyncio.gather(
                *[_fetch_one(client, metro, lat, lng)
                  for metro, lat, lng in METROS],
                return_exceptions=False,
            )
        for (metro, _lat, _lng), result in zip(METROS, results):
            if result is None:
                # Fetch failed — DO NOT widen the dict. The cache
                # merge step preserves the prior entry for this metro.
                continue
            out[metro] = list(result)
    except Exception as e:  # noqa: BLE001
        logger.warning("[OWM_ALERTS] batch fetch failed: %r", e)
        return {}
    return out


def _merge_with_cached(
    fresh: dict[str, list[dict]],
    cached: dict[str, list[dict]] | None,
) -> dict[str, list[dict]]:
    """Cache-preservation merge:
      * For every metro present in `fresh` → use the fresh value
        (including empty list = "metro succeeded, no alerts").
      * For every metro missing from `fresh` but present in `cached`
        → carry forward the cached value.
      * Net result: a transient failure for ONE metro does not
        erase the global alert picture.
    """
    base = dict(cached or {})
    for metro, alerts in fresh.items():
        base[metro] = alerts
    # Drop any keys that aren't in the canonical metro list
    # (defends against an old cache shape with extra keys).
    valid_keys = {slug for slug, _, _ in METROS}
    return {k: v for k, v in base.items() if k in valid_keys}


async def get_alerts_cached() -> dict[str, list[dict]]:
    """Read the Redis cache. Returns {} when the cache is cold."""
    cached = redis_service.get_json(CACHE_NAMESPACE, CACHE_KEY)
    if isinstance(cached, dict):
        return cached
    return {}


# ── Provider ─────────────────────────────────────────────────────


class OWMAlertsSignalProvider(ExternalSignalProvider):
    """Wires OWM OneCall 3.0 severe alerts into the External Signal
    Layer as a SUPPLEMENTARY signal alongside SACHET.

    SACHET stays the primary regulatory/authoritative source (CAP-XML
    + NDMA curation). OWM is additive — same envelope shape as the
    existing TomTom / News providers. The registry's `fetch_all_signals`
    fan-out runs both concurrently and `apply_external_modifiers`
    already handles multi-provider additive blending. NO priority
    inversion.

    Confidence intentionally lower than SACHET (0.75 vs 0.85) so
    when both providers fire on the same event, SACHET's signal
    dominates the blended risk score.
    """

    name = "weather_alerts"          # distinct from `weather` (current conditions)
    PROVIDER_CONFIDENCE = 0.75

    def is_enabled(self) -> bool:
        return bool(_api_key())

    async def _fetch_unsafe(
        self, lat: float, lng: float,
        when: Optional[datetime] = None,
    ) -> Optional[ExternalSignal]:
        metro = nearest_metro(lat, lng)
        if not metro:
            # User is not within 75 km of any monitored metro — no
            # signal here (consistent with the news provider's
            # behaviour outside known zones).
            return None
        cache = await get_alerts_cached()
        alerts = cache.get(metro) if isinstance(cache, dict) else None
        if not alerts:
            return None
        match = pick_strongest(alerts)
        if not match:
            return None
        severity = match.get("severity") or "moderate"
        risk = SEVERITY_RISK.get(severity, 0.30)
        if risk <= 0:
            return None
        factors = [
            f"owm_alert_{severity}",
            f"metro:{metro}",
            f"event:{(match.get('event') or 'unknown').lower().replace(' ', '_')[:48]}",
        ]
        sender = match.get("sender")
        if sender:
            factors.append(f"sender:{sender.lower().replace(' ', '_')[:48]}")
        return ExternalSignal(
            provider=self.name,
            signal_type=f"owm_{severity}",
            risk_0_1=float(risk),
            factors=factors,
            confidence=self.PROVIDER_CONFIDENCE,
            fetched_at=datetime.now(timezone.utc),
            ttl_s=SIGNAL_TTL_S,
            raw_url=None,
        )


__all__ = [
    "ONECALL_URL",
    "CACHE_NAMESPACE", "CACHE_KEY", "CACHE_TTL_S",
    "SIGNAL_TTL_S", "HTTP_TIMEOUT_S", "PREWARMER_TIMEOUT_S",
    "METROS", "METRO_ZONE_RADIUS_KM",
    "SEVERITY_RISK",
    "infer_severity",
    "parse_alerts",
    "pick_strongest",
    "nearest_metro",
    "fetch_all_metros",
    "get_alerts_cached",
    "_merge_with_cached",
    "OWMAlertsSignalProvider",
]
