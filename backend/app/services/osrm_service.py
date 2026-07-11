# OSRM Service Layer — Self-hosted routing with Redis cache
#
# Provides route generation via local OSRM server with Redis caching.
# Falls back to public OSRM if local is unavailable.
#
# Redis keys: nischint:route:{hash} (TTL 1800s / 30 min)

import hashlib
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.redis_service import set_json, get_json

logger = logging.getLogger(__name__)

ROUTE_CACHE_TTL = 1800  # 30 minutes

PUBLIC_OSRM = "https://router.project-osrm.org"


def _get_osrm_url() -> str:
    return settings.osrm_url or PUBLIC_OSRM


def _route_cache_key(coords_str: str, profile: str, alternatives: int) -> str:
    raw = f"{profile}:{coords_str}:{alternatives}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


async def get_route(
    start_lng: float, start_lat: float,
    end_lng: float, end_lat: float,
    profile: str = "driving",
    alternatives: int = 3,
    overview: str = "full",
    geometries: str = "geojson",
    steps: bool = False,
) -> dict[str, Any]:
    """
    Get route(s) from OSRM. Checks Redis cache first.
    Returns raw OSRM response dict.
    """
    coords_str = f"{start_lng},{start_lat};{end_lng},{end_lat}"
    cache_key = _route_cache_key(coords_str, profile, alternatives)

    # Try Redis cache
    cached = get_json("route", cache_key)
    if cached:
        cached["_cache"] = "hit"
        return cached

    # Build OSRM URL
    base = _get_osrm_url()
    url = f"{base}/route/v1/{profile}/{coords_str}"
    params = {
        "overview": overview,
        "geometries": geometries,
        "alternatives": str(alternatives).lower() if alternatives <= 1 else str(alternatives),
        "steps": str(steps).lower(),
    }

    start = time.time()
    result: dict = {}

    # Try local OSRM first
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            result = resp.json()
            result["_source"] = "self-hosted"
            result["_latency_ms"] = round((time.time() - start) * 1000)
            logger.info(f"OSRM route [{coords_str}]: {result['_latency_ms']}ms (self-hosted)")
    except Exception as e:
        logger.warning(f"Local OSRM failed: {e}, falling back to public")
        # Fallback to public OSRM
        try:
            fallback_url = f"{PUBLIC_OSRM}/route/v1/{profile}/{coords_str}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(fallback_url, params=params)
                resp.raise_for_status()
                result = resp.json()
                result["_source"] = "public-fallback"
                result["_latency_ms"] = round((time.time() - start) * 1000)
                logger.info(f"OSRM route [{coords_str}]: {result['_latency_ms']}ms (public fallback)")
        except Exception as e2:
            logger.error(f"Both OSRM sources failed: {e2}")
            return {"code": "Error", "message": str(e2), "_source": "error"}

    # Cache successful response
    if result.get("code") == "Ok":
        result["_cache"] = "miss"
        set_json("route", cache_key, result, ttl=ROUTE_CACHE_TTL)

    return result


async def get_table(
    coordinates: list[tuple[float, float]],
    profile: str = "driving",
) -> dict[str, Any]:
    """
    Get distance/duration table from OSRM for multiple coordinates.
    Used for patrol routing and multi-point analysis.
    """
    coords_str = ";".join(f"{lng},{lat}" for lat, lng in coordinates)

    base = _get_osrm_url()
    url = f"{base}/table/v1/{profile}/{coords_str}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        # Fallback
        try:
            url = f"{PUBLIC_OSRM}/table/v1/{profile}/{coords_str}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
        except Exception as e2:
            logger.error(f"OSRM table failed: {e2}")
            return {"code": "Error", "message": str(e2)}


async def get_nearest(
    lng: float, lat: float,
    number: int = 1,
    profile: str = "driving",
) -> dict[str, Any]:
    """Get nearest road point to given coordinates."""
    base = _get_osrm_url()
    url = f"{base}/nearest/v1/{profile}/{lng},{lat}"
    params = {"number": number}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        try:
            url = f"{PUBLIC_OSRM}/nearest/v1/{profile}/{lng},{lat}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            return {"code": "Error", "message": str(e)}


def get_status() -> dict:
    """Return OSRM service status."""
    import requests as req
    base = _get_osrm_url()
    is_local = base != PUBLIC_OSRM

    try:
        resp = req.get(f"{base}/route/v1/driving/77.5946,12.9716;77.6245,12.9352?overview=false", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return {
            "osrm": "connected",
            "source": "self-hosted" if is_local else "public",
            "url": base,
            "test_route": "ok" if data.get("code") == "Ok" else "failed",
        }
    except Exception as e:
        return {
            "osrm": "error",
            "source": "self-hosted" if is_local else "public",
            "url": base,
            "error": str(e),
        }
