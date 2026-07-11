"""NISCH-012.2 — News & social keyword monitor.

Two-tier source strategy:

  1. **NewsAPI** (`NEWSAPI_KEY` env var) — keyword queries over
     Indian sources. Returns structured JSON. When the key is
     absent the NewsAPI path is *disabled* — but the provider as a
     whole is NOT disabled because:

  2. **RSS fallback** (no key required) — NDTV India + Times of
     India top-stories feeds. Always runs. Detects the same
     keyword set in headlines via simple substring match.

The two paths are tracked independently in telemetry:
  * `parse_failure_rate` — NewsAPI-only rolling failure rate
    (skipped entirely when NewsAPI is disabled)
  * `rss_failure_rate` — RSS-only rolling failure rate
The pre-warmer's cache combines both into one modifier list, with
a `source: "newsapi" | "rss"` tag per item so operators can see
which channel produced each alert.

Normalised modifier shape (same as Sachet + TomTom):
    {zone, severity, strength, source, expiry_window_s, title,
     fetched_at, raw_url}

Zone matching is by Indian city name → centroid lookup using the
read-only `INDIAN_CITY_CENTROIDS` constant — NO PostGIS write
path, NO DB inserts (the user spec explicitly forbade writes; a
hardcoded centroid table is the minimal surface).
"""
from __future__ import annotations

import logging
import math
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.services import redis_service
from app.services.external_signals import (
    ExternalSignal, ExternalSignalProvider,
)

logger = logging.getLogger(__name__)


# ── Locked configuration ─────────────────────────────────────────
CACHE_NAMESPACE = "news"
CACHE_KEY = "modifiers_v1"
CACHE_TTL_S = 1800              # 30-min cache (pre-warmer fires every 15 min)
SIGNAL_TTL_S = 7200             # 2-hour decay on emitted signals
HTTP_TIMEOUT_S = 1.5

NEWSAPI_URL = "https://newsapi.org/v2/everything"

# Indian sources only — the spec calls out India focus.
NEWSAPI_SOURCES = (
    "the-times-of-india,the-hindu,bbc-news"
)
RSS_FEEDS: tuple[tuple[str, str], ...] = (
    ("ndtv",
     "https://feeds.feedburner.com/ndtvnews-top-stories"),
    ("toi",
     "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
)

# Locked keyword → severity grid. Keys ordered most-severe first
# so a single headline mentioning multiple keywords picks the
# highest severity.
KEYWORD_SEVERITY: tuple[tuple[str, str], ...] = (
    ("riot",     "extreme"),
    ("fire",     "severe"),
    ("flood",    "severe"),
    ("accident", "moderate"),
    ("crime",    "moderate"),
)

SEVERITY_RISK: dict[str, float] = {
    "extreme":  0.85,
    "severe":   0.65,
    "moderate": 0.40,
    "minor":    0.20,
}

# Indian city centroids — read-only lookup table. Adding a city is
# a deliberate decision (the spec forbids DB writes, so this is
# the bounded surface). Values are (lat, lng).
INDIAN_CITY_CENTROIDS: dict[str, tuple[float, float]] = {
    "mumbai":     (19.0760, 72.8777),
    "delhi":      (28.6139, 77.2090),
    "bengaluru":  (12.9716, 77.5946),
    "bangalore":  (12.9716, 77.5946),       # alias
    "hyderabad":  (17.3850, 78.4867),
    "chennai":    (13.0827, 80.2707),
    "kolkata":    (22.5726, 88.3639),
    "pune":       (18.5204, 73.8567),
    "ahmedabad":  (23.0225, 72.5714),
    "jaipur":     (26.9124, 75.7873),
    "lucknow":    (26.8467, 80.9462),
    "kanpur":     (26.4499, 80.3319),
    "nagpur":     (21.1458, 79.0882),
    "surat":      (21.1702, 72.8311),
    "patna":      (25.5941, 85.1376),
    "indore":     (22.7196, 75.8577),
    "bhopal":     (23.2599, 77.4126),
    "guwahati":   (26.1445, 91.7362),
    "chandigarh": (30.7333, 76.7794),
    "kerala":     (10.8505, 76.2711),       # state-level
    "maharashtra": (19.7515, 75.7139),      # state-level
    "gujarat":    (22.2587, 71.1924),       # state-level
    "punjab":     (31.1471, 75.3412),       # state-level
}


def newsapi_enabled() -> bool:
    """Public predicate — also used by the registry and operator
    endpoint to surface a `disabled` state for the NewsAPI channel
    without disabling the provider as a whole."""
    return bool(os.environ.get("NEWSAPI_KEY", "").strip())


# ── Pure parse / extract helpers (unit-tested) ───────────────────
_PUNCT_RX = re.compile(r"[^a-z0-9 ]+")


def detect_keyword_severity(text: str) -> Optional[str]:
    """Substring match against the locked keyword → severity grid.
    Returns the HIGHEST severity hit, or None if no keyword matched.

    Case-insensitive substring search (NOT token-set) so plurals
    and simple inflections still hit — "riots", "fires", "flooded",
    "accidents" all match their root keyword."""
    if not text:
        return None
    norm = _PUNCT_RX.sub(" ", text.lower())
    for keyword, severity in KEYWORD_SEVERITY:
        if keyword in norm:
            return severity
    return None


def detect_zone(text: str) -> Optional[str]:
    """First matched Indian city/state name → its slug. Used for
    zone routing. Returns None if no known location surfaces.

    Substring search guarded by word boundaries so "delhi" doesn't
    accidentally match inside an unrelated word."""
    if not text:
        return None
    norm = _PUNCT_RX.sub(" ", text.lower())
    tokens = set(norm.split())
    for city in INDIAN_CITY_CENTROIDS:
        if city in tokens:
            return city
    return None


def build_modifier(title: str, source: str, url: Optional[str],
                   fetched_at: datetime) -> Optional[dict]:
    """Translate one headline → one normalised modifier, or None
    if the headline doesn't carry a recognised keyword + zone.

    Skips headlines without both an actionable keyword AND a known
    location — random news with no operational hook would otherwise
    noisily inflate the modifier count."""
    severity = detect_keyword_severity(title)
    zone = detect_zone(title)
    if not severity or not zone:
        return None
    return {
        "zone":            zone,
        "severity":        severity,
        "strength":        float(SEVERITY_RISK.get(severity, 0.20)),
        "source":          source,           # "newsapi" | "rss"
        "title":           title.strip(),
        "expiry_window_s": SIGNAL_TTL_S,
        "fetched_at":      fetched_at.isoformat(),
        "raw_url":         url,
    }


# ── HTTP fetchers ────────────────────────────────────────────────
async def fetch_newsapi() -> Optional[list[dict]]:
    """NewsAPI path. Returns None (NOT empty list) when:
      * key is absent (skip — RSS still runs)
      * HTTP error
      * malformed body
    Returns possibly-empty list when:
      * NewsAPI responded successfully but no headlines matched.

    The distinction matters: `None` means "NewsAPI was skipped" and
    must NOT count as a NewsAPI failure in telemetry. `[]` means
    "NewsAPI succeeded with zero matches" — counts as a success.

    REL-09: HTTP and exception failures forward to
    `news_sentry.report_fetch_failure` with `channel="newsapi"`."""
    if not newsapi_enabled():
        return None
    import time as _time
    keywords_query = " OR ".join(k for k, _ in KEYWORD_SEVERITY)
    now = datetime.now(timezone.utc)
    t0 = _time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            resp = await client.get(
                NEWSAPI_URL,
                params={
                    "q":        f"({keywords_query}) AND India",
                    "language": "en",
                    "sources":  NEWSAPI_SOURCES,
                    "pageSize": "50",
                    "apiKey":   os.environ.get("NEWSAPI_KEY", "").strip(),
                },
                headers={"User-Agent": "nischint-safety/1.0"},
            )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (_time.monotonic() - t0) * 1000.0
        logger.warning("[NEWS] NewsAPI fetch failed: %r", e)
        try:
            from app.services.external_signals.news_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=None,
                upstream_url=NEWSAPI_URL,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=repr(e)[:280],
                channel="newsapi",
            )
        except Exception:  # pragma: no cover
            pass
        return None
    elapsed_ms = (_time.monotonic() - t0) * 1000.0
    if resp.status_code != 200:
        logger.warning("[NEWS] NewsAPI HTTP %s", resp.status_code)
        try:
            from app.services.external_signals.news_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=resp.status_code,
                upstream_url=NEWSAPI_URL,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=None,
                channel="newsapi",
            )
        except Exception:
            pass
        return None
    try:
        body = resp.json()
    except Exception:
        return None
    articles = body.get("articles") or []
    out: list[dict] = []
    for a in articles:
        m = build_modifier(
            title=a.get("title") or "",
            source="newsapi",
            url=a.get("url"),
            fetched_at=now,
        )
        if m:
            out.append(m)
    return out


async def _fetch_rss_one(client: httpx.AsyncClient, name: str,
                         url: str) -> Optional[list[dict]]:
    import time as _time
    t0 = _time.monotonic()
    try:
        resp = await client.get(
            url, headers={"User-Agent": "nischint-safety/1.0"},
        )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (_time.monotonic() - t0) * 1000.0
        logger.warning("[NEWS] RSS %s fetch failed: %r", name, e)
        try:
            from app.services.external_signals.news_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=None,
                upstream_url=url,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=repr(e)[:280],
                channel="rss",
                feed=name,
            )
        except Exception:  # pragma: no cover
            pass
        return None
    elapsed_ms = (_time.monotonic() - t0) * 1000.0
    if resp.status_code != 200:
        logger.warning("[NEWS] RSS %s HTTP %s", name, resp.status_code)
        try:
            from app.services.external_signals.news_sentry import (
                report_fetch_failure,
            )
            report_fetch_failure(
                status_code=resp.status_code,
                upstream_url=url,
                response_time_ms=elapsed_ms,
                is_proxy=False,
                error=None,
                channel="rss",
                feed=name,
            )
        except Exception:
            pass
        return None
    return parse_rss_items(resp.content, name)


def parse_rss_items(content: bytes,
                    source_name: str) -> Optional[list[dict]]:
    """Pure RSS parser — extracted so unit tests can drive it
    without HTTP. Returns None on parse failure, list (possibly
    empty) on success."""
    if not content:
        return None
    try:
        root = ET.fromstring(content)
    except Exception:
        return None
    # RSS 2.0 (channel/item) only — both NDTV and ToI use this.
    items = root.findall(".//item")
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for it in items[:50]:
        title_el = it.find("title")
        link_el = it.find("link")
        title = (title_el.text or "") if title_el is not None else ""
        link = (link_el.text or "") if link_el is not None else None
        m = build_modifier(
            title=title, source="rss", url=link, fetched_at=now,
        )
        if m:
            out.append(m)
    return out


async def fetch_rss() -> Optional[list[dict]]:
    """Fan-out across the static RSS feed list. Returns None only
    if EVERY feed fails (true RSS-channel outage); partial success
    returns the combined matches."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            results = []
            for name, url in RSS_FEEDS:
                results.append(await _fetch_rss_one(client, name, url))
    except Exception as e:  # noqa: BLE001
        logger.warning("[NEWS] RSS batch outer error: %r", e)
        return None
    successful = [r for r in results if r is not None]
    if not successful:
        return None
    out: list[dict] = []
    for r in successful:
        out.extend(r)
    return out


__all__ = [
    "CACHE_NAMESPACE", "CACHE_KEY", "CACHE_TTL_S",
    "SIGNAL_TTL_S", "HTTP_TIMEOUT_S",
    "NEWSAPI_URL", "RSS_FEEDS",
    "KEYWORD_SEVERITY", "SEVERITY_RISK",
    "INDIAN_CITY_CENTROIDS",
    "newsapi_enabled",
    "detect_keyword_severity",
    "detect_zone",
    "build_modifier",
    "parse_rss_items",
    "fetch_newsapi",
    "fetch_rss",
    "NewsSignalProvider",
    "news_hot_path_enabled",
    "NEWS_ZONE_RADIUS_KM",
]


# ── Hot-path provider — feature-flagged OFF by default ────────────
#
# The pre-warmer keeps the `news/modifiers_v1` cache fresh even when
# the hot path is disabled. Enabling the flag wires the cached
# modifiers into `fetch_all_signals()` so the news layer can modulate
# alert confidence. Per session policy (V2-ramp gating), this is OFF
# until V2 lands and we have headroom to observe the modifier effect
# against real incident traffic.

NEWS_ZONE_RADIUS_KM = 75.0          # max distance from city centroid
                                     # to count as "in zone"


def news_hot_path_enabled() -> bool:
    """Public predicate. Operator endpoint surfaces the flag state
    so the chip can show 'enabled but no key' vs 'disabled' clearly."""
    return os.environ.get(
        "EXTERNAL_SIGNAL_NEWS_ENABLED", "",
    ).strip().lower() in ("1", "true", "yes", "on")


def _haversine_km(lat1: float, lng1: float,
                  lat2: float, lng2: float) -> float:
    """Plain haversine — accurate enough for the 75km zone radius
    check. No external geo lib needed."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def find_nearest_zone(lat: float, lng: float,
                      radius_km: float = NEWS_ZONE_RADIUS_KM,
                      ) -> Optional[str]:
    """Return the slug of the closest city centroid within
    `radius_km`, or None. Locked at module level so it's
    independently unit-testable without instantiating the provider."""
    if lat is None or lng is None:
        return None
    best_slug: Optional[str] = None
    best_dist = radius_km
    for slug, (clat, clng) in INDIAN_CITY_CENTROIDS.items():
        d = _haversine_km(lat, lng, clat, clng)
        if d <= best_dist:
            best_dist = d
            best_slug = slug
    return best_slug


def pick_strongest_modifier(modifiers: list[dict],
                            zone: str) -> Optional[dict]:
    """Highest-severity modifier matching the zone slug, or None."""
    if not zone or not modifiers:
        return None
    rank = {"extreme": 4, "severe": 3, "moderate": 2, "minor": 1}
    matches = [m for m in modifiers if m.get("zone") == zone]
    if not matches:
        return None
    matches.sort(key=lambda m: -rank.get(m.get("severity", "minor"), 0))
    return matches[0]


class NewsSignalProvider(ExternalSignalProvider):
    """Wires news/social modifiers into the External Signal Layer
    on a feature-flagged opt-in basis. Reads the pre-warmer's
    cached modifier list — no HTTP from the hot path."""

    name = "news"

    def is_enabled(self) -> bool:
        # Disabled by default per session policy. The pre-warmer
        # keeps the cache warm regardless so flipping the flag in
        # prod is a no-restart change.
        return news_hot_path_enabled()

    async def _fetch_unsafe(
        self, lat: float, lng: float,
        when: Optional[datetime] = None,
    ) -> Optional[ExternalSignal]:
        zone = find_nearest_zone(lat, lng)
        if not zone:
            return None
        cached = redis_service.get_json(CACHE_NAMESPACE, CACHE_KEY)
        if not isinstance(cached, list) or not cached:
            return None
        match = pick_strongest_modifier(cached, zone)
        if not match:
            return None
        severity = match.get("severity") or "minor"
        risk = float(match.get("strength") or SEVERITY_RISK.get(severity, 0.20))
        if risk <= 0:
            return None
        factors = [
            f"news_{severity}",
            f"zone:{zone}",
            f"source:{match.get('source', 'unknown')}",
        ]
        return ExternalSignal(
            provider=self.name,
            signal_type=f"news_{severity}",
            risk_0_1=risk,
            factors=factors,
            confidence=0.55,                # lower than NDMA — headlines aren't curated
            fetched_at=datetime.now(timezone.utc),
            ttl_s=SIGNAL_TTL_S,
            raw_url=match.get("raw_url"),
        )
