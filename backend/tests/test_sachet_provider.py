"""NISCH-012.3 — Sachet (NDMA) provider unit tests.

Pure-unit. No real network, no real Redis. Each helper function is
locked individually + the provider's end-to-end fail-quiet contract
is verified with mocked HTTP + mocked cache.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.external_signals import ExternalSignal
from app.services.external_signals.sachet_provider import (
    CACHE_KEY, CACHE_NAMESPACE, CACHE_TTL_S, SEVERITY_RISK, SIGNAL_TTL_S,
    SachetSignalProvider, get_alerts_cached, infer_severity,
    parse_rss, pick_strongest, resolve_state,
)


# ════════════════════════════════════════════════════════════════════
# Tunables locked
# ════════════════════════════════════════════════════════════════════

def test_severity_risk_mapping_locked():
    """The deterministic severity→risk contract must not drift —
    operator-facing audit shows these numbers verbatim."""
    assert SEVERITY_RISK["extreme"]  == 0.95
    assert SEVERITY_RISK["severe"]   == 0.80
    assert SEVERITY_RISK["moderate"] == 0.50
    assert SEVERITY_RISK["minor"]    == 0.30
    # 5-min cache, 30-min signal decay are intentional.
    assert CACHE_TTL_S  == 300
    assert SIGNAL_TTL_S == 1800


# ════════════════════════════════════════════════════════════════════
# resolve_state — bounding-box reverse geocode
# ════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("lat,lng,expected", [
    (19.07, 72.87,  "Maharashtra"),     # Mumbai
    (23.03, 72.58,  "Gujarat"),         # Ahmedabad
    (12.97, 77.59,  "Karnataka"),       # Bengaluru
    (13.08, 80.27,  "Tamil Nadu"),      # Chennai
    ( 9.93, 76.27,  "Kerala"),          # Kochi (clearly west-of-77°E)
    (16.51, 80.65,  "Andhra Pradesh"),  # Vijayawada (east-of-Maharashtra)
    (22.57, 88.36,  "West Bengal"),     # Kolkata
    (20.27, 85.84,  "Odisha"),          # Bhubaneswar
])
def test_resolve_state_known_cities(lat, lng, expected):
    assert resolve_state(lat, lng) == expected


def test_resolve_state_returns_none_outside_india():
    assert resolve_state(40.7128, -74.0060) is None  # NYC
    assert resolve_state(51.5074,  -0.1278) is None  # London


def test_resolve_state_returns_none_for_missing_coords():
    assert resolve_state(None, None) is None
    assert resolve_state(None, 72.87) is None
    assert resolve_state(19.07, None) is None


# ════════════════════════════════════════════════════════════════════
# infer_severity — title-keyword classifier
# ════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("title,expected", [
    ("Cyclone Biparjoy approaching Gujarat coast", "extreme"),
    ("Extreme heat wave warning for Rajasthan",    "extreme"),
    ("Tsunami alert issued for coastal Tamil Nadu","extreme"),
    ("Severe heatwave warning for Maharashtra",    "severe"),
    ("Heavy rain expected over Kerala",            "severe"),
    ("Flood warning for districts of West Bengal", "severe"),
    ("Thunderstorm with lightning over Karnataka", "moderate"),
    ("Heat Wave likely at isolated places, Gujarat","moderate"),
    ("Routine advisory for fishermen",             "minor"),
    ("",                                            "minor"),
])
def test_infer_severity_keyword_table(title, expected):
    assert infer_severity(title) == expected


def test_infer_severity_extreme_beats_lower_keywords():
    """A headline containing both 'extreme' and 'thunderstorm' must
    classify as `extreme` — most actionable wins."""
    assert infer_severity(
        "Extreme thunderstorm warning for Maharashtra"
    ) == "extreme"


# ════════════════════════════════════════════════════════════════════
# parse_rss — XML parsing
# ════════════════════════════════════════════════════════════════════

_VALID_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>India</title>
  <item>
    <title>Cyclone Warning for coastal Maharashtra</title>
    <link>https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=A1</link>
    <category>Met</category>
    <pubDate>Sun, 10 May 2026 08:33:16 GMT</pubDate>
    <guid>A1</guid>
  </item>
  <item>
    <title>Heat Wave likely over Gujarat</title>
    <link>https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=B2</link>
    <category>Met</category>
    <pubDate>Sun, 10 May 2026 08:30:00 GMT</pubDate>
    <guid>B2</guid>
  </item>
</channel></rss>"""


def test_parse_rss_yields_alerts():
    alerts = parse_rss(_VALID_RSS)
    assert len(alerts) == 2
    a1, a2 = alerts
    assert a1["identifier"] == "A1"
    assert a1["title"].startswith("Cyclone")
    assert a1["link"].startswith("https://sachet.ndma.gov.in/")
    assert a1["category"] == "Met"
    assert a1["severity"] == "extreme"
    assert a1["pub_date_iso"] is not None
    assert a2["severity"] == "moderate"


def test_parse_rss_empty_bytes_returns_empty():
    assert parse_rss(b"") == []


def test_parse_rss_malformed_returns_empty():
    assert parse_rss(b"<not_real_xml>>>>") == []


def test_parse_rss_skips_items_missing_title_or_id():
    bad = b"""<?xml version="1.0"?><rss><channel>
      <item><title></title><guid>X</guid></item>
      <item><title>OK title</title></item>
    </channel></rss>"""
    assert parse_rss(bad) == []


# ════════════════════════════════════════════════════════════════════
# pick_strongest — state filter + severity ranking
# ════════════════════════════════════════════════════════════════════

def _alert(title, sev="minor", link="https://x", category="Met"):
    return {
        "identifier": title[:8],
        "title":      title,
        "link":       link,
        "category":   category,
        "pub_date_iso": None,
        "severity":   sev,
    }


def test_pick_strongest_returns_highest_severity():
    alerts = [
        _alert("Light rain in Maharashtra",      "minor"),
        _alert("Severe storm over Maharashtra",  "severe"),
        _alert("Cyclone hits Maharashtra coast", "extreme"),
        _alert("Thunderstorm in Maharashtra",    "moderate"),
    ]
    chosen = pick_strongest(alerts, "Maharashtra")
    assert chosen is not None
    assert chosen["severity"] == "extreme"


def test_pick_strongest_returns_none_when_no_state_match():
    alerts = [
        _alert("Cyclone hits Karnataka", "extreme"),
        _alert("Heavy rain Tamil Nadu",  "severe"),
    ]
    assert pick_strongest(alerts, "Maharashtra") is None


def test_pick_strongest_state_match_is_case_insensitive():
    alerts = [_alert("cyclone over MAHARASHTRA coast", "extreme")]
    assert pick_strongest(alerts, "Maharashtra") is not None


def test_pick_strongest_empty_state_returns_none():
    alerts = [_alert("Cyclone Maharashtra", "extreme")]
    assert pick_strongest(alerts, "") is None


# ════════════════════════════════════════════════════════════════════
# get_alerts_cached — Redis cache layer
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cache_hit_skips_http():
    """Redis HIT → no upstream HTTP call should fire."""
    cached_alerts = [_alert("Cyclone Maharashtra", "extreme")]
    with patch(
        "app.services.external_signals.sachet_provider.redis_service.get_json",
        return_value=cached_alerts,
    ), patch(
        "app.services.external_signals.sachet_provider._fetch_feed_uncached",
        new=AsyncMock(side_effect=AssertionError("MUST NOT FETCH")),
    ):
        out = await get_alerts_cached()
    assert out == cached_alerts


@pytest.mark.asyncio
async def test_cache_miss_fetches_and_writes():
    """Redis MISS → upstream fetch + cache write at CACHE_TTL_S."""
    fresh = [_alert("Severe storm Gujarat", "severe")]
    set_calls: list = []

    def fake_set_json(ns, key, value, ttl=None):
        set_calls.append((ns, key, value, ttl))
        return True

    with patch(
        "app.services.external_signals.sachet_provider.redis_service.get_json",
        return_value=None,
    ), patch(
        "app.services.external_signals.sachet_provider.redis_service.set_json",
        side_effect=fake_set_json,
    ), patch(
        "app.services.external_signals.sachet_provider._fetch_feed_uncached",
        new=AsyncMock(return_value=fresh),
    ):
        out = await get_alerts_cached()

    assert out == fresh
    assert len(set_calls) == 1
    ns, key, value, ttl = set_calls[0]
    assert ns == CACHE_NAMESPACE
    assert key == CACHE_KEY
    assert ttl == CACHE_TTL_S


@pytest.mark.asyncio
async def test_cache_miss_does_not_persist_empty_feed():
    """Transient upstream failure → empty list returned but cache
    NOT written, so the next call retries instead of being stuck on
    [] for 5 minutes."""
    set_called: list = []
    with patch(
        "app.services.external_signals.sachet_provider.redis_service.get_json",
        return_value=None,
    ), patch(
        "app.services.external_signals.sachet_provider.redis_service.set_json",
        side_effect=lambda *a, **kw: set_called.append(a) or True,
    ), patch(
        "app.services.external_signals.sachet_provider._fetch_feed_uncached",
        new=AsyncMock(return_value=[]),
    ):
        out = await get_alerts_cached()

    assert out == []
    assert set_called == []


# ════════════════════════════════════════════════════════════════════
# Provider — end-to-end shape
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_provider_returns_external_signal_for_matching_state():
    alerts = [
        _alert("Cyclone Biparjoy hits Maharashtra coast",
               sev="extreme",
               link="https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=A1"),
    ]
    with patch(
        "app.services.external_signals.sachet_provider.get_alerts_cached",
        new=AsyncMock(return_value=alerts),
    ):
        sig = await SachetSignalProvider()._fetch_unsafe(19.07, 72.87)

    assert isinstance(sig, ExternalSignal)
    assert sig.provider == "sachet"
    assert sig.signal_type == "ndma_extreme"
    assert sig.risk_0_1 == 0.95
    assert "sachet_extreme" in sig.factors
    assert "state:maharashtra" in sig.factors
    assert sig.raw_url and sig.raw_url.startswith(
        "https://sachet.ndma.gov.in/"
    )
    assert sig.ttl_s == SIGNAL_TTL_S


@pytest.mark.asyncio
async def test_provider_returns_none_outside_indian_states():
    """Coordinates outside the 8-state bbox short-circuit BEFORE any
    upstream / cache hit — provider must be cheap for global users."""
    with patch(
        "app.services.external_signals.sachet_provider.get_alerts_cached",
        new=AsyncMock(side_effect=AssertionError("must not fetch")),
    ):
        sig = await SachetSignalProvider()._fetch_unsafe(40.7128, -74.0060)
    assert sig is None


@pytest.mark.asyncio
async def test_provider_returns_none_when_no_alerts_for_state():
    alerts = [_alert("Cyclone hits Gujarat", "extreme")]
    with patch(
        "app.services.external_signals.sachet_provider.get_alerts_cached",
        new=AsyncMock(return_value=alerts),
    ):
        # Mumbai (Maharashtra) — no Maharashtra alert in feed.
        sig = await SachetSignalProvider()._fetch_unsafe(19.07, 72.87)
    assert sig is None


@pytest.mark.asyncio
async def test_provider_returns_none_when_feed_empty():
    with patch(
        "app.services.external_signals.sachet_provider.get_alerts_cached",
        new=AsyncMock(return_value=[]),
    ):
        sig = await SachetSignalProvider()._fetch_unsafe(19.07, 72.87)
    assert sig is None


def test_provider_is_disabled_when_env_flag_set(monkeypatch):
    monkeypatch.setenv("DISABLE_SACHET", "true")
    assert SachetSignalProvider().is_enabled() is False
    monkeypatch.setenv("DISABLE_SACHET", "")
    assert SachetSignalProvider().is_enabled() is True
