"""NISCH-012.1 — TomTom Flow Segment Data provider.

API: TomTom Traffic Flow Segment Data v4. Returns instantaneous
congestion per coordinate sample, comparing the current speed to
the free-flow baseline of that road. We sample a fixed set of
urban points (one per monitored zone) and translate the
(speed / free-flow speed) ratio into the same severity grid the
rest of the External Signal Layer already uses.

Locked invariants (driven by tests):
  * **Cache-preservation** — identical to Sachet: an empty or
    failed fetch leaves the cache key untouched.
  * **Disabled when key absent** — `is_enabled()` returns False if
    `TOMTOM_API_KEY` is missing, so the registry never registers
    the provider, the scheduler never wakes the prewarmer, and the
    monitoring endpoint can surface `{state: "disabled"}`.
  * **Fail-quiet** — every HTTP path is wrapped; no exception ever
    escapes to the alert hot-path.
  * **Same envelope shape** as Sachet: each emitted ExternalSignal
    carries `factors=["tomtom_<severity>", "zone:<zone_slug>"]`.

Cost discipline:
  * One HTTPS request per zone per 5-min cycle (≈ 8 per cycle).
  * Hard timeout `1.0 s` per request well under the registry's
    `PROVIDER_TIMEOUT_S = 1.5` so even a global outage cannot
    block the alert hot-path.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.services import redis_service
from app.services.external_signals import (
    ExternalSignal, ExternalSignalProvider,
)

logger = logging.getLogger(__name__)


# ── Tunables (locked by tests) ────────────────────────────────────
TOMTOM_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData/"
    "absolute/10/json"
)
CACHE_NAMESPACE = "tomtom"
CACHE_KEY = "flow_by_zone_v1"
CACHE_TTL_S = 600            # 10-min Redis cache (prewarmer fires ~5 min)
SIGNAL_TTL_S = 900           # 15-min decay on emitted signal
HTTP_TIMEOUT_S = 1.0         # under PROVIDER_TIMEOUT_S = 1.5

# Congestion ratio → CAP-aligned severity buckets. The thresholds
# are tuned for Indian urban arterials where 30 % degradation is
# still business-as-usual; only ≥ 50 % shows up as actionable.
SEVERITY_RISK: dict[str, float] = {
    "extreme":  0.90,        # > 80 % degradation — gridlock
    "severe":   0.70,        # 60-80 % degradation
    "moderate": 0.45,        # 30-60 % degradation
    "minor":    0.20,        # < 30 % degradation
}


# Eight monitored urban zones — one Flow Segment probe each. Picked
# to overlap the Sachet bounding boxes so a single coordinate
# resolves through both providers without ambiguity. Each entry is
# (zone, lat, lng).
MONITORED_POINTS: tuple[tuple[str, float, float], ...] = (
    ("Mumbai",      19.0760, 72.8777),
    ("Delhi",       28.6139, 77.2090),
    ("Bengaluru",   12.9716, 77.5946),
    ("Hyderabad",   17.3850, 78.4867),
    ("Chennai",     13.0827, 80.2707),
    ("Kolkata",     22.5726, 88.3639),
    ("Pune",        18.5204, 73.8567),
    ("Ahmedabad",   23.0225, 72.5714),
)


# ── Pure helpers (unit-tested) ────────────────────────────────────
def severity_from_ratio(ratio: float) -> str:
    """ratio = (free_flow - current) / free_flow, clamped to [0,1].
    Higher ratio = more degraded. Locked mapping."""
    if ratio is None:
        return "minor"
    r = max(0.0, min(1.0, float(ratio)))
    if r > 0.80:
        return "extreme"
    if r > 0.60:
        return "severe"
    if r > 0.30:
        return "moderate"
    return "minor"


def parse_flow_segment(payload: dict | None) -> Optional[dict]:
    """Extract the few fields we care about from a Flow Segment
    response. Returns None on any shape mismatch — fail-quiet."""
    if not isinstance(payload, dict):
        return None
    fsd = payload.get("flowSegmentData")
    if not isinstance(fsd, dict):
        return None
    try:
        current = float(fsd.get("currentSpeed"))
        freeflow = float(fsd.get("freeFlowSpeed"))
    except (TypeError, ValueError):
        return None
    if freeflow <= 0:
        return None
    ratio = max(0.0, (freeflow - current) / freeflow)
    return {
        "current_speed":   current,
        "free_flow_speed": freeflow,
        "ratio":           round(ratio, 4),
        "severity":        severity_from_ratio(ratio),
        "confidence":      float(fsd.get("confidence") or 0.0),
        "road_closure":    bool(fsd.get("roadClosure", False)),
        "frc":             fsd.get("frc"),
    }


# ── HTTP layer ────────────────────────────────────────────────────
def _api_key() -> str:
    return os.environ.get("TOMTOM_API_KEY", "").strip()


async def _fetch_one(client: httpx.AsyncClient,
                     zone: str, lat: float, lng: float) -> Optional[dict]:
    """Single zone probe. Always returns Optional, never raises.

    REL-09 fan-out: every non-200 / exception path forwards to
    `tomtom_sentry.report_fetch_failure` with `zone` as an extra tag
    so operators can tell whether one city is flapping vs a global
    TomTom outage. Telemetry must NEVER raise into the caller."""
    import time as _time
    t0 = _time.monotonic()
    try:
        resp = await client.get(
            TOMTOM_FLOW_URL,
            params={
                "point": f"{lat},{lng}",
                "unit":  "KMPH",
                "key":   _api_key(),
            },
            headers={"User-Agent": "nischint-safety/1.0"},
        )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (_time.monotonic() - t0) * 1000.0
        logger.warning("[TOMTOM] zone=%s fetch failed: %r", zone, e)
        try:
            from app.services.external_signals.tomtom_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=None,
                upstream_url=TOMTOM_FLOW_URL,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=repr(e)[:280],
                zone=zone,
            )
        except Exception:  # pragma: no cover — never break the fetch
            pass
        return None
    elapsed_ms = (_time.monotonic() - t0) * 1000.0
    if resp.status_code != 200:
        logger.warning("[TOMTOM] zone=%s HTTP %s", zone, resp.status_code)
        try:
            from app.services.external_signals.tomtom_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=resp.status_code,
                upstream_url=TOMTOM_FLOW_URL,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=None,
                zone=zone,
            )
        except Exception:
            pass
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    parsed = parse_flow_segment(body)
    if parsed is None:
        return None
    parsed["zone"] = zone
    parsed["lat"] = lat
    parsed["lng"] = lng
    return parsed


async def fetch_all_zones() -> list[dict]:
    """Probe every monitored zone in parallel. Returns the union of
    successful results (possibly fewer than `MONITORED_POINTS`).
    NEVER raises — caller treats empty list as "no signal here".

    Partial-failure handling matters: if 6 of 8 zones succeed we
    still want the cache refreshed with those 6. The prewarmer is
    the only layer that enforces "don't overwrite a healthy cache
    with an empty result"; here we just collect what we can."""
    if not _api_key():
        return []
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            results = await asyncio.gather(
                *[_fetch_one(client, z, lat, lng)
                  for z, lat, lng in MONITORED_POINTS],
                return_exceptions=False,
            )
        out = [r for r in results if isinstance(r, dict)]
    except Exception as e:  # noqa: BLE001
        logger.warning("[TOMTOM] batch fetch failed: %r", e)
        return []
    return out


async def get_flow_cached() -> list[dict]:
    """Cache HIT → return immediately. Cache MISS → fetch upstream
    and persist ONLY on a non-empty response (transient outage must
    not poison the cache with [])."""
    cached = redis_service.get_json(CACHE_NAMESPACE, CACHE_KEY)
    if isinstance(cached, list):
        return cached
    fresh = await fetch_all_zones()
    if fresh:
        redis_service.set_json(
            CACHE_NAMESPACE, CACHE_KEY, fresh, ttl=CACHE_TTL_S,
        )
    return fresh


# ── Provider ─────────────────────────────────────────────────────
class TomTomSignalProvider(ExternalSignalProvider):
    """Wires TomTom Flow into the External Signal Layer.

    Looks up the cached zone reading whose lat/lng is closest to
    the incident location — within a hard 0.5° radius (≈ 55 km).
    Beyond that distance we return None (no signal), keeping the
    provider explicit about its coverage envelope."""

    name = "tomtom"
    MAX_ZONE_DELTA_DEG = 0.5

    def is_enabled(self) -> bool:
        return bool(_api_key())

    def _nearest_zone(self, lat: float, lng: float,
                      readings: list[dict]) -> Optional[dict]:
        best = None
        best_d2 = None
        for r in readings:
            try:
                dlat = float(r["lat"]) - lat
                dlng = float(r["lng"]) - lng
            except Exception:
                continue
            d2 = dlat * dlat + dlng * dlng
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best = r
        if best is None or best_d2 is None:
            return None
        if best_d2 > self.MAX_ZONE_DELTA_DEG * self.MAX_ZONE_DELTA_DEG:
            return None
        return best

    async def _fetch_unsafe(
        self, lat: float, lng: float,
        when: Optional[datetime] = None,
    ) -> Optional[ExternalSignal]:
        if not self.is_enabled():
            return None
        readings = await get_flow_cached()
        if not readings:
            return None
        match = self._nearest_zone(lat, lng, readings)
        if not match:
            return None
        severity = match.get("severity") or "minor"
        risk = SEVERITY_RISK.get(severity, 0.20)
        if risk <= 0:
            return None
        zone = (match.get("zone") or "unknown").lower().replace(" ", "_")
        factors = [
            f"tomtom_{severity}",
            f"zone:{zone}",
            f"ratio:{match.get('ratio', 0.0):.2f}",
        ]
        if match.get("road_closure"):
            factors.append("road_closure")
        return ExternalSignal(
            provider=self.name,
            signal_type=f"traffic_{severity}",
            risk_0_1=float(risk),
            factors=factors,
            confidence=float(match.get("confidence") or 0.85),
            fetched_at=datetime.now(timezone.utc),
            ttl_s=SIGNAL_TTL_S,
            raw_url=None,
        )


__all__ = [
    "TOMTOM_FLOW_URL",
    "CACHE_NAMESPACE", "CACHE_KEY", "CACHE_TTL_S",
    "SIGNAL_TTL_S", "HTTP_TIMEOUT_S",
    "SEVERITY_RISK", "MONITORED_POINTS",
    "TomTomSignalProvider",
    "fetch_all_zones",
    "get_flow_cached",
    "parse_flow_segment",
    "severity_from_ratio",
]
