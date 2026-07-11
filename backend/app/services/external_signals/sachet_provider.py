"""NISCH-012.3 — Sachet (NDMA) CAP-XML disaster feed provider.

Public, no API key. Polls India's official disaster alert RSS feed
(`rss_india.xml`) — the same source that backs sachet.ndma.gov.in.

────────────────────────────────────────────────────────────────────
KNOWN LIMITATION — IP whitelist (closed by REL-07):

`sachet.ndma.gov.in` restricts inbound traffic to Indian-origin IPs.
Local/Mumbai-based environments return HTTP 200; the Emergent
production backend (us-east-1) sees a near-100% failure rate (timeout
/ TCP-reset / 403). REL-07 ships a Cloudflare Worker
(`deploy/cloudflare-workers/sachet-proxy/`) that egresses from a CF
Indian colo. When the `SACHET_PROXY_URL` env var is set, every
NDMA HTTPS call is routed through the Worker; when unset the code
falls back to direct upstream (pre-REL-07 behaviour).

Until the Worker is deployed AND `SACHET_PROXY_URL` is set on the
production backend, the limitation in KNOWN_LIMITATIONS.md still
applies. The fix is *code-complete, deploy-pending*.

When the proxy is offline, behaviour is unchanged: SF-02 PostGIS env
hazard scoring runs independently and is the primary risk signal.
NDMA is *additive only* — when reachable it contributes a 0.30 – 0.95
severity bump via `apply_external_modifiers`; when blocked the
registry falls back silently (cache-preservation invariant +
hysteresis → `degraded` health state, no user-visible failure).
────────────────────────────────────────────────────────────────────

Rules (locked):
  * 5-minute Redis cache on the parsed feed (single HTTPS hop per
    region per 5min, regardless of how many incidents fire).
  * Sub-1.5s hard timeout enforced by the registry; we keep our own
    HTTP_TIMEOUT_S well under that so the Redis write still happens
    when the network is slow.
  * Coarse 8-state bounding-box reverse geocode — covers the
    cyclone/flood/heatwave-prone Indian states without needing an
    external geocoder. Locations outside those states return None
    (fail-quiet, no signal).
  * Severity → risk_0_1 mapping is deterministic and explainable
    (Extreme=0.95, Severe=0.80, Moderate=0.50, Minor=0.30).
  * `raw_url` is populated with the per-alert FetchXMLFile URL so
    operators can click through to the original CAP-XML alert.

Forensic linkback is the audit/UI's job (already handled by
`apply_external_modifiers`); we do NOT write extra event rows.
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

from app.services import redis_service
from app.services.external_signals import (
    ExternalSignal, ExternalSignalProvider,
)
logger = logging.getLogger(__name__)


# ── Tunables (locked by tests) ────────────────────────────────────
SACHET_UPSTREAM_HOST = "sachet.ndma.gov.in"
SACHET_RSS_PATH = "/cap_public_website/rss/rss_india.xml"
SACHET_RSS_URL = f"https://{SACHET_UPSTREAM_HOST}{SACHET_RSS_PATH}"


def _proxy_origin() -> Optional[str]:
    """REL-07 — Read `SACHET_PROXY_URL` at request time so the value
    can be flipped without a redeploy. Strips trailing slash so the
    join with the upstream path is deterministic.

    Returns None when the var is unset/empty → caller falls back to
    direct upstream (pre-REL-07 behaviour)."""
    raw = (os.environ.get("SACHET_PROXY_URL") or "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def effective_url(path: str = SACHET_RSS_PATH) -> str:
    """Resolve a SACHET upstream `path` to the actual URL to hit:
      • `SACHET_PROXY_URL` set → proxy origin + path
      • otherwise              → `https://sachet.ndma.gov.in` + path

    Centralised so every NDMA caller (RSS fetch, future FetchXMLFile
    follow-ups) automatically benefits from the proxy switch."""
    proxy = _proxy_origin()
    if not path.startswith("/"):
        path = "/" + path
    if proxy:
        return f"{proxy}{path}"
    return f"https://{SACHET_UPSTREAM_HOST}{path}"


CACHE_NAMESPACE = "sachet"
CACHE_KEY = "rss_parsed_v1"
CACHE_TTL_S = 300            # 5-minute Redis cache
SIGNAL_TTL_S = 1800          # 30-minute decay on emitted signal
HTTP_TIMEOUT_S = 1.0         # well under PROVIDER_TIMEOUT_S = 1.5 (hot path)
PREWARMER_TIMEOUT_S = 8.0    # generous budget for the background pre-warmer —
                             # no hot-path latency cap, and NDMA RSS routinely
                             # responds at 1.4–1.9 s with a 73 KB payload

# CAP severity → 0..1 risk contribution.
SEVERITY_RISK: dict[str, float] = {
    "extreme":  0.95,
    "severe":   0.80,
    "moderate": 0.50,
    "minor":    0.30,
    "unknown":  0.30,
}

_SEVERITY_RANK: dict[str, int] = {
    "extreme":  4,
    "severe":   3,
    "moderate": 2,
    "minor":    1,
    "unknown":  0,
}

# Indian state bounding boxes — coarse, cyclone/flood/heatwave belt.
# (lat_min, lat_max, lng_min, lng_max)
#
# Order matters: smaller / more southerly bboxes are evaluated first
# so a coordinate sitting in two overlapping rectangles resolves to
# the more specific state. The Karnataka–Kerala–Tamil Nadu corner is
# the most ambiguous; we keep the Western-Ghats boundary at 77.0°E
# so Kochi/Trivandrum land in Kerala and Coimbatore/Salem land in
# Tamil Nadu.
STATE_BBOX: dict[str, tuple[float, float, float, float]] = {
    "Kerala":         ( 8.20, 12.80, 74.80, 77.00),
    "Karnataka":      (11.50, 18.50, 74.00, 78.00),
    "Tamil Nadu":     ( 8.00, 13.60, 77.00, 80.30),
    "Andhra Pradesh": (12.60, 19.90, 77.00, 84.80),
    "Maharashtra":    (15.60, 22.00, 72.60, 80.50),
    "Gujarat":        (20.10, 24.70, 68.10, 74.50),
    "Odisha":         (17.70, 22.50, 81.40, 87.50),
    "West Bengal":    (21.50, 27.20, 85.80, 89.90),
    # SF-01 v2 Day 3 — Himalayan belt (avalanche / cloudburst / flash
    # flood / landslide hazard zone). Required for the Himalaya
    # 3-phase demo on Day 4. Bboxes are rough but never overlap the
    # cyclone-belt states above.
    "Uttarakhand":      (28.70, 31.50, 77.50, 81.10),
    "Himachal Pradesh": (30.20, 33.30, 75.40, 79.10),
    "Jammu & Kashmir":  (32.20, 37.10, 73.20, 80.30),
    "Sikkim":           (27.00, 28.20, 87.90, 89.00),
    "Arunachal Pradesh":(26.60, 29.50, 91.50, 97.50),
}

# Title-keyword → severity inference.  RSS feed gives only the
# headline; CAP severity isn't in the index. We map the headline
# vocabulary to CAP-style severities deterministically.
_EXTREME_KEYWORDS: tuple[str, ...] = (
    "extreme", "cyclone", "tsunami", "tornado",
    "very heavy rain", "extremely heavy",
)
_SEVERE_KEYWORDS: tuple[str, ...] = (
    "severe", "heavy rain", "heatwave warning", "heat wave warning",
    "flood warning", "storm surge", "thunderstorm warning",
    "snow storm",
)
_MODERATE_KEYWORDS: tuple[str, ...] = (
    "thunderstorm", "lightning", "gusty winds", "heat wave",
    "moderate", "rain warning", "squall",
)


# ── Pure helpers (unit-tested) ────────────────────────────────────

def resolve_state(lat: Optional[float],
                  lng: Optional[float]) -> Optional[str]:
    """Return the Indian state name for a (lat,lng) within one of the
    8 mapped bounding boxes — None otherwise (incl. None inputs)."""
    if lat is None or lng is None:
        return None
    for name, (la0, la1, lo0, lo1) in STATE_BBOX.items():
        if la0 <= lat <= la1 and lo0 <= lng <= lo1:
            return name
    return None


# ── SF-02 PostGIS dual-read (Day 3) ───────────────────────────────
#
# `resolve_state` above is the v1 STATE_BBOX path (synchronous, pure,
# unit-test-friendly). The functions below add a PostGIS `ST_Within`
# polygon-matching path. They are gated by the env flag
# `ENV_HAZARD_USE_POSTGIS=true` and only invoked from the async
# entry point `resolve_state_async` below.
#
# Day 3 plumbing-only: flag DEFAULTS TO FALSE. Flip to true on Day 4
# after prod-side p99 verification.
ENV_HAZARD_POSTGIS_FLAG = "ENV_HAZARD_USE_POSTGIS"


def _postgis_enabled() -> bool:
    return os.environ.get(ENV_HAZARD_POSTGIS_FLAG, "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ── SF-02 Day 4 · LRU caches ──────────────────────────────────────
#
# Emergent deploy topology has prod backend in us-east-1 and Supabase
# in ap-south-1 (Mumbai). Every uncached ST_Within call pays ~240ms
# of cross-region RTT. State/district boundaries don't move, so the
# (lat, lng) → match mapping is stable. Caching by rounded coordinate
# (~1 km grid via 2-decimal round) absorbs 99%+ of repeat queries.
#
# Why two caches, not one: `_postgis_resolve_state` returns a string
# (state name), `_postgis_check_location` returns a dict (rich
# match). Keeping them separate avoids stuffing two different shapes
# into one map.
#
# Why OrderedDict + manual eviction instead of functools.lru_cache:
# lru_cache doesn't work with async functions, and even with
# async_lru we'd lose the ability to surface hit/miss counters
# through a diagnostic endpoint.
#
# Cache is intentionally process-local (not Redis) — the value is
# tiny (~50 bytes), eviction is LRU, and a memory cache avoids
# adding a Redis round trip to a path that exists specifically to
# avoid a DB round trip.
_CACHE_MAXSIZE = 1000

# (lat_rounded, lng_rounded) → state_name | None
_resolve_cache: "OrderedDict[tuple[float, float], object]" = OrderedDict()
_resolve_stats = {"hits": 0, "misses": 0}

# (lat_rounded, lng_rounded) → match_dict | None
_check_cache: "OrderedDict[tuple[float, float], object]" = OrderedDict()
_check_stats = {"hits": 0, "misses": 0}


def _cache_key(lat: float, lng: float) -> tuple[float, float]:
    """Round to 2 decimals — ~1.1 km grid. State boundaries are
    coarse enough that this resolution preserves correctness for
    state/district matching while collapsing a typical user's day
    of GPS pings into a handful of unique keys."""
    return (round(lat, 2), round(lng, 2))


def _cache_get(cache: "OrderedDict", stats: dict,
               key: tuple[float, float], label: str):
    """Returns (hit_flag, value). On hit, refreshes LRU position."""
    if key in cache:
        cache.move_to_end(key)
        stats["hits"] += 1
        logger.debug("[SF-02 cache] %s HIT key=%s", label, key)
        return True, cache[key]
    stats["misses"] += 1
    logger.debug("[SF-02 cache] %s MISS key=%s", label, key)
    return False, None


def _cache_put(cache: "OrderedDict", key: tuple[float, float],
               value) -> None:
    """Insert with LRU eviction once capacity exceeds maxsize."""
    cache[key] = value
    cache.move_to_end(key)
    if len(cache) > _CACHE_MAXSIZE:
        cache.popitem(last=False)


def get_cache_stats() -> dict:
    """Public — used by `GET /api/admin/sf02/cache-stats`."""
    def summary(stats: dict, size: int) -> dict:
        total = stats["hits"] + stats["misses"]
        return {
            "hits": stats["hits"],
            "misses": stats["misses"],
            "total": total,
            "hit_rate": round(stats["hits"] / total, 4) if total else 0.0,
            "size": size,
            "maxsize": _CACHE_MAXSIZE,
        }
    return {
        "_postgis_resolve_state": summary(_resolve_stats, len(_resolve_cache)),
        "_postgis_check_location": summary(_check_stats, len(_check_cache)),
    }


def clear_cache() -> dict:
    """Drop both caches (e.g. after a curated polygon overlay update).
    Returns the pre-clear stats for the response."""
    pre = get_cache_stats()
    _resolve_cache.clear()
    _check_cache.clear()
    _resolve_stats["hits"] = 0
    _resolve_stats["misses"] = 0
    _check_stats["hits"] = 0
    _check_stats["misses"] = 0
    return pre


async def _postgis_resolve_state(
    lat: float, lng: float,
) -> Optional[str]:
    """PostGIS variant of `resolve_state` — returns the matched state
    name via `ST_Within` against `env_hazard_zones` rows tagged
    `type='state_boundary'`. Returns None if the point is outside
    every state polygon.

    Cached: rounds (lat,lng) to 2 decimals (~1 km), holds 1000 most
    recent results in a process-local LRU. Negative results (None)
    are also cached — a point in the middle of the ocean shouldn't
    cost a DB round trip every motion sample.

    Defense-in-depth flag guard: returns None immediately when
    `ENV_HAZARD_USE_POSTGIS` is not truthy, *regardless of caller*.
    Flag check runs before the cache check — when the feature is
    off, nothing is cached and the function is sub-microsecond.

    Fail-quiet: any DB error returns None so `resolve_state_async`'s
    fallback to STATE_BBOX kicks in. The error result is NOT cached
    (transient DB failures shouldn't poison the cache; a real
    `no-match` answer goes through the explicit `None` path)."""
    if not _postgis_enabled():
        return None
    key = _cache_key(lat, lng)
    hit, cached = _cache_get(_resolve_cache, _resolve_stats, key,
                             "resolve_state")
    if hit:
        return cached  # may be None (cached negative)
    try:
        from app.db.session import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT name FROM env_hazard_zones
                 WHERE type = 'state_boundary'
                   AND ST_Within(ST_SetSRID(ST_MakePoint($1, $2), 4326), geom)
                 ORDER BY area_km2 ASC NULLS LAST
                 LIMIT 1
                """,
                lng, lat,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SF-02] _postgis_resolve_state failed: %r", exc)
        return None  # do NOT cache on error
    _cache_put(_resolve_cache, key, result)
    return result


async def _postgis_check_location(
    lat: float, lng: float,
) -> Optional[dict]:
    """Forward-compatible rich variant of the PostGIS lookup.

    Cached: same (lat,lng) → result LRU scheme as
    `_postgis_resolve_state`, separate map (different value type).

    Defense-in-depth flag guard + cache layout mirror
    `_postgis_resolve_state`. See that function for details.

    Returns the highest-severity active hazard polygon containing
    the point (district preferred over state when both match —
    smaller polygon wins), enriched with severity + source. Returns
    None if no active polygon matches.

    Currently no rows carry `severity != 'low'` (only OSM admin
    boundaries are loaded). This function will start producing
    meaningful matches once real hazard layers (NDMA active
    polygons, landslide-prone zones) are loaded in a later sprint.
    The SF-03 entry point — kept here so the matcher API is stable
    when hazard data lands."""
    if not _postgis_enabled():
        return None
    key = _cache_key(lat, lng)
    hit, cached = _cache_get(_check_cache, _check_stats, key,
                             "check_location")
    if hit:
        return cached  # may be None (cached negative)
    try:
        from app.db.session import get_db_pool
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    name, type, severity, source,
                    area_km2
                  FROM env_hazard_zones
                 WHERE ST_Within(
                          ST_SetSRID(ST_MakePoint($1, $2), 4326), geom
                       )
                   AND (expires_at IS NULL OR expires_at > NOW())
                 ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high'     THEN 2
                        WHEN 'medium'   THEN 3
                        ELSE 4
                    END,
                    area_km2 ASC NULLS LAST
                 LIMIT 1
                """,
                lng, lat,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SF-02] _postgis_check_location failed: %r", exc)
        return None  # do NOT cache on error
    if not row:
        _cache_put(_check_cache, key, None)
        return None
    result = {
        "matched": True,
        "name": row["name"],
        "type": row["type"],
        "severity": row["severity"],
        "source": row["source"],
        "area_km2": float(row["area_km2"]) if row["area_km2"] is not None else None,
    }
    _cache_put(_check_cache, key, result)
    return result


async def resolve_state_async(
    lat: Optional[float], lng: Optional[float],
) -> Optional[str]:
    """Feature-flagged dual-read entry point — call this from any
    async caller. When `ENV_HAZARD_USE_POSTGIS=true`, attempts the
    PostGIS polygon match first; if it returns None (e.g. point is
    inside India but the polygon set is incomplete), falls through
    to the STATE_BBOX path as a safety net.

    When the flag is off (default), short-circuits straight to
    `resolve_state` — exact v1 behaviour, zero PostGIS round-trip."""
    if lat is None or lng is None:
        return None
    if _postgis_enabled():
        pg = await _postgis_resolve_state(lat, lng)
        if pg is not None:
            return pg
        # PostGIS empty → fall through to bbox so transitional gaps
        # (e.g. Arunachal pre-curated-patch) don't cause a regression.
    return resolve_state(lat, lng)


def infer_severity(title: str) -> str:
    """Return one of: extreme | severe | moderate | minor.

    Keyword scan is intentionally ordered most-actionable-first so a
    headline mentioning both "thunderstorm" and "extreme" lands on
    `extreme`."""
    t = (title or "").lower()
    if not t:
        return "minor"
    for kw in _EXTREME_KEYWORDS:
        if kw in t:
            return "extreme"
    for kw in _SEVERE_KEYWORDS:
        if kw in t:
            return "severe"
    for kw in _MODERATE_KEYWORDS:
        if kw in t:
            return "moderate"
    return "minor"


def _parse_pubdate(s: str) -> Optional[datetime]:
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        return None


def parse_rss(xml_bytes: bytes) -> list[dict]:
    """Parse the Sachet `rss_india.xml` feed into a flat alert list.

    Returns [] on any parse error (fail-quiet contract). Each dict
    carries `identifier, title, link, category, pub_date_iso,
    severity` — enough to drive matching + ranking + linkback."""
    if not xml_bytes:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.warning("[SACHET] RSS parse error: %r", e)
        return []
    alerts: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        identifier = (
            item.findtext("guid")
            or item.findtext("link")
            or ""
        ).strip()
        link = (item.findtext("link") or "").strip()
        category = (item.findtext("category") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        pub = _parse_pubdate(pub_raw)
        if not title or not identifier:
            continue
        alerts.append({
            "identifier":   identifier,
            "title":        title,
            "link":         link,
            "category":     category,
            "pub_date_iso": pub.isoformat() if pub else None,
            "severity":     infer_severity(title),
        })
    return alerts


def _title_mentions_state(title: str, state: str) -> bool:
    if not title or not state:
        return False
    return state.lower() in title.lower()


def pick_strongest(alerts: list[dict],
                   state: str) -> Optional[dict]:
    """Return the strongest-severity alert mentioning `state` in its
    headline. None if no alert matches."""
    if not state:
        return None
    matches = [
        a for a in alerts
        if _title_mentions_state(a.get("title", ""), state)
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda a: -_SEVERITY_RANK.get(a.get("severity", "minor"), 0),
    )
    return matches[0]


# ── HTTP + cache layer ────────────────────────────────────────────

async def _fetch_feed_uncached(timeout_s: float | None = None) -> list[dict]:
    """Single HTTPS GET to the Sachet RSS feed. Always returns a
    list (possibly empty) — never raises.

    `timeout_s` overrides the default `HTTP_TIMEOUT_S` (1.0s, sized
    for the alert hot path). Background callers like the
    pre-warmer should pass `PREWARMER_TIMEOUT_S` since they don't
    share the hot path's crash-budget — the NDMA endpoint
    typically responds at 1.4–1.9 s and a sub-second cap misses
    every fetch.

    REL-09: every non-200 / exception path emits a Sentry warning
    + counter metric. See `sachet_sentry.report_fetch_failure`."""
    import time as _time
    effective_timeout = timeout_s if timeout_s is not None else HTTP_TIMEOUT_S
    url = effective_url(SACHET_RSS_PATH)
    via_proxy = _proxy_origin() is not None
    t0 = _time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "nischint-safety/1.0"},
            )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (_time.monotonic() - t0) * 1000.0
        logger.warning("[SACHET] HTTP fetch failed url=%s err=%r", url, e)
        try:
            from app.services.external_signals.sachet_sentry import report_fetch_failure
            report_fetch_failure(
                status_code=None,
                upstream_url=url,
                response_time_ms=elapsed_ms,
                is_proxy=via_proxy,
                colo=None,
                error=repr(e)[:280],
            )
        except Exception:  # pragma: no cover — never break the fetch
            pass
        return []
    elapsed_ms = (_time.monotonic() - t0) * 1000.0
    if resp.status_code != 200:
        # CF Worker stamps `x-sachet-proxy-colo: BOM|ORD|...` on the
        # response so we can attribute outages to a specific colo in
        # Sentry. Header is absent for direct upstream calls.
        colo = resp.headers.get("x-sachet-proxy-colo") if via_proxy else None
        logger.warning(
            "[SACHET] RSS HTTP %s url=%s colo=%s rt=%.1fms",
            resp.status_code, url, colo, elapsed_ms,
        )
        try:
            from app.services.external_signals.sachet_sentry import report_fetch_failure
            report_fetch_failure(
                status_code=resp.status_code,
                upstream_url=url,
                response_time_ms=elapsed_ms,
                is_proxy=via_proxy,
                colo=colo,
                error=None,
            )
        except Exception:
            pass
        return []
    return parse_rss(resp.content)


async def get_alerts_cached() -> list[dict]:
    """5-minute Redis-cached parsed feed.

    Cache HIT → return immediately. Cache MISS → fetch upstream,
    persist the parsed list (TTL 300s) only on a non-empty response
    so a transient outage doesn't poison the cache with `[]`.

    Fail-quiet: any error path returns [] so the registry treats
    Sachet as "no signal here" rather than failing the batch."""
    cached = redis_service.get_json(CACHE_NAMESPACE, CACHE_KEY)
    if isinstance(cached, list):
        return cached
    fresh = await _fetch_feed_uncached()
    if fresh:
        redis_service.set_json(
            CACHE_NAMESPACE, CACHE_KEY, fresh, ttl=CACHE_TTL_S,
        )
    return fresh


# ── Provider ─────────────────────────────────────────────────────

class SachetSignalProvider(ExternalSignalProvider):
    """Wires Sachet alerts into the External Signal Layer."""

    name = "sachet"

    def is_enabled(self) -> bool:
        # Public feed — no API key. Disable only via explicit opt-out
        # so CI / preview envs can suppress the network hop.
        flag = os.environ.get("DISABLE_SACHET", "").strip().lower()
        return flag not in ("1", "true", "yes", "on")

    async def _fetch_unsafe(
        self, lat: float, lng: float,
        when: Optional[datetime] = None,
    ) -> Optional[ExternalSignal]:
        state = resolve_state(lat, lng)
        if not state:
            # Outside the 8 mapped Indian states — no signal here.
            return None

        alerts = await get_alerts_cached()
        if not alerts:
            return None

        match = pick_strongest(alerts, state)
        if not match:
            return None

        severity = match.get("severity") or "minor"
        risk = SEVERITY_RISK.get(severity, 0.30)
        if risk <= 0:
            return None

        # Factors are surfaced verbatim in the audit trail / UI.
        state_slug = state.lower().replace(" ", "_")
        factors = [f"sachet_{severity}", f"state:{state_slug}"]
        category = (match.get("category") or "").strip().lower()
        if category:
            factors.append(f"category:{category}")

        return ExternalSignal(
            provider=self.name,
            signal_type=f"ndma_{severity}",
            risk_0_1=float(risk),
            factors=factors,
            confidence=0.85,            # NDMA-curated, slightly lower than weather
            fetched_at=datetime.now(timezone.utc),
            ttl_s=SIGNAL_TTL_S,
            raw_url=match.get("link") or None,
        )


__all__ = [
    "SACHET_RSS_URL",
    "SACHET_UPSTREAM_HOST",
    "SACHET_RSS_PATH",
    "effective_url",
    "CACHE_NAMESPACE", "CACHE_KEY", "CACHE_TTL_S",
    "SIGNAL_TTL_S", "HTTP_TIMEOUT_S",
    "SEVERITY_RISK", "STATE_BBOX",
    "SachetSignalProvider",
    "get_alerts_cached",
    "infer_severity",
    "parse_rss",
    "pick_strongest",
    "resolve_state",
    "resolve_state_async",
    "_postgis_check_location",
    "ENV_HAZARD_POSTGIS_FLAG",
    "get_cache_stats",
    "clear_cache",
]
