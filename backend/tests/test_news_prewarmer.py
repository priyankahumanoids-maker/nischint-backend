"""NISCH-012.2 — News/Social pre-warmer unit tests.

Locks the user-mandated invariants:
  1. NewsAPI path: cache untouched on empty + on exception.
  2. RSS fallback activates when NewsAPI returns empty.
  3. Jitter within bounds over 100 iterations, independent of
     Sachet's 4±45 AND TomTom's 5±60.
  4. Disabled mode when `NEWSAPI_KEY` absent — RSS still runs;
     provider is NEVER fully disabled.
  5. `news_health` appears in SSE replay-tail allow-list.
  6. **RSS fallback must NOT count as a NewsAPI success** —
     `parse_failure_rate`/NewsAPI telemetry tracks NewsAPI only.
  7. No DB writes — ratchet stays at 21 (tested indirectly via
     the swallow audit suite remaining green).

Plus parse-layer tests for keyword + zone detection.
"""
from __future__ import annotations

import random
from unittest.mock import AsyncMock, patch

import pytest

from app.services.external_signals import news_prewarmer as np
from app.services.external_signals import news_provider as npr
from app.services.external_signals.news_prewarmer import (
    CHANNEL_NEWSAPI_KEY, CHANNEL_RSS_KEY, JITTER_BASE_S,
    JITTER_RANGE_S, NewsPrewarmer, compute_next_interval_seconds,
    get_channel_telemetry, get_prewarmer_telemetry,
    run_prewarm_cycle,
)
from app.services.external_signals.news_provider import (
    INDIAN_CITY_CENTROIDS, KEYWORD_SEVERITY, SEVERITY_RISK,
    build_modifier, detect_keyword_severity, detect_zone,
    newsapi_enabled, parse_rss_items,
)


# ════════════════════════════════════════════════════════════════════
# Jitter — independent of Sachet AND TomTom
# ════════════════════════════════════════════════════════════════════

def test_jitter_bounds_locked():
    assert JITTER_BASE_S == 900       # 15 min
    assert JITTER_RANGE_S == 120      # ±2 min


def test_jitter_independent_of_sachet_and_tomtom():
    """News must not collide with either sibling provider's cadence
    — a coordinated outage is the only way three pre-warmers should
    ever fall into phase."""
    from app.services.external_signals import sachet_prewarmer as sp
    from app.services.external_signals import tomtom_prewarmer as tp
    assert JITTER_BASE_S != sp.JITTER_BASE_S
    assert JITTER_BASE_S != tp.JITTER_BASE_S
    assert (JITTER_BASE_S, JITTER_RANGE_S) != (sp.JITTER_BASE_S, sp.JITTER_RANGE_S)
    assert (JITTER_BASE_S, JITTER_RANGE_S) != (tp.JITTER_BASE_S, tp.JITTER_RANGE_S)


def test_jitter_stays_within_bounds_over_100_iterations():
    rng = random.Random(101)
    low = JITTER_BASE_S - JITTER_RANGE_S      # 780
    high = JITTER_BASE_S + JITTER_RANGE_S     # 1020
    samples = [compute_next_interval_seconds(rng) for _ in range(100)]
    assert min(samples) >= low
    assert max(samples) <= high
    assert len(set(round(s, 2) for s in samples)) > 50


# ════════════════════════════════════════════════════════════════════
# Cache-preservation — NewsAPI path
# ════════════════════════════════════════════════════════════════════

class _RedisDouble:
    def __init__(self):
        self.store: dict[tuple[str, str], object] = {}
        self.set_calls: list[tuple[str, str, object, int | None]] = []

    def get_json(self, ns, key):
        return self.store.get((ns, key))

    def set_json(self, ns, key, value, ttl=None):
        self.set_calls.append((ns, key, value, ttl))
        self.store[(ns, key)] = value
        return True


@pytest.fixture
def redis_double(monkeypatch):
    d = _RedisDouble()
    # Patch redis_service everywhere news_prewarmer touches it.
    from app.services.external_signals import base_prewarmer as _base
    monkeypatch.setattr(_base.redis_service, "get_json", d.get_json)
    monkeypatch.setattr(_base.redis_service, "set_json", d.set_json)
    monkeypatch.setattr(np.redis_service, "get_json", d.get_json)
    monkeypatch.setattr(np.redis_service, "set_json", d.set_json)
    return d


@pytest.fixture
def enable_newsapi(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "test-key")


@pytest.fixture
def disable_newsapi(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)


@pytest.mark.asyncio
async def test_newsapi_cache_untouched_on_empty(redis_double, enable_newsapi):
    """When NewsAPI returns no matches and RSS also returns nothing,
    the cache must NOT be poisoned with []."""
    healthy = [{"zone": "mumbai", "severity": "severe",
                "source": "newsapi", "title": "Fire in Mumbai"}]
    redis_double.store[("news", "modifiers_v1")] = healthy

    with patch(
        "app.services.external_signals.news_prewarmer.fetch_newsapi",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.external_signals.news_prewarmer.fetch_rss",
        new=AsyncMock(return_value=[]),
    ):
        result = await run_prewarm_cycle()

    assert result["status"] == "no_fresh_news"
    assert redis_double.store[("news", "modifiers_v1")] == healthy
    cache_writes = [c for c in redis_double.set_calls if c[0] == "news"]
    assert cache_writes == []


@pytest.mark.asyncio
async def test_newsapi_failure_does_not_advance_newsapi_last_success(
        redis_double, enable_newsapi):
    """NewsAPI returning None (failure) must NOT update its
    `last_success_ts` — the spec demands NewsAPI tracks its own
    failure rate independently of RSS."""
    with patch(
        "app.services.external_signals.news_prewarmer.fetch_newsapi",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.external_signals.news_prewarmer.fetch_rss",
        new=AsyncMock(return_value=[]),
    ):
        await run_prewarm_cycle()

    newsapi_tele = get_channel_telemetry(CHANNEL_NEWSAPI_KEY)
    assert newsapi_tele["last_success_ts"] is None
    assert newsapi_tele["failure_rate"] == 1.0     # one failure, one attempt


# ════════════════════════════════════════════════════════════════════
# RSS fallback activates when NewsAPI is empty
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_rss_fallback_activates_when_newsapi_empty(
        redis_double, enable_newsapi):
    rss_hit = [{
        "zone": "delhi", "severity": "moderate", "strength": 0.40,
        "source": "rss", "title": "Accident in Delhi",
        "expiry_window_s": 7200, "fetched_at": "2026-05-01T00:00:00+00:00",
        "raw_url": "http://example.com/a",
    }]
    with patch(
        "app.services.external_signals.news_prewarmer.fetch_newsapi",
        new=AsyncMock(return_value=[]),       # NewsAPI returns empty
    ), patch(
        "app.services.external_signals.news_prewarmer.fetch_rss",
        new=AsyncMock(return_value=rss_hit),  # RSS has hits
    ):
        result = await run_prewarm_cycle()
    assert result == {"status": "success", "news_count": 1}
    cached = redis_double.store[("news", "modifiers_v1")]
    assert cached == rss_hit


@pytest.mark.asyncio
async def test_rss_does_not_count_as_newsapi_success(
        redis_double, enable_newsapi):
    """A successful RSS fallback must NOT inflate the NewsAPI
    success telemetry. The spec demands the counters stay
    independent so an operator can spot a paid-API outage even
    when the fallback is healthy."""
    with patch(
        "app.services.external_signals.news_prewarmer.fetch_newsapi",
        new=AsyncMock(return_value=None),       # NewsAPI failed
    ), patch(
        "app.services.external_signals.news_prewarmer.fetch_rss",
        new=AsyncMock(return_value=[{"zone": "x"}]),  # RSS succeeded
    ):
        await run_prewarm_cycle()

    newsapi_tele = get_channel_telemetry(CHANNEL_NEWSAPI_KEY)
    rss_tele = get_channel_telemetry(CHANNEL_RSS_KEY)
    # NewsAPI telemetry records a failure (None response).
    assert newsapi_tele["failure_rate"] == 1.0
    assert newsapi_tele["last_success_ts"] is None
    # RSS telemetry records its own success.
    assert rss_tele["failure_rate"] == 0.0
    assert rss_tele["last_success_ts"] is not None


# ════════════════════════════════════════════════════════════════════
# Disabled mode — NewsAPI absent, RSS still runs
# ════════════════════════════════════════════════════════════════════

def test_newsapi_disabled_without_key(disable_newsapi):
    assert newsapi_enabled() is False


def test_provider_never_fully_disabled():
    """Even without NEWSAPI_KEY, the provider class reports enabled
    so the scheduler registers and RSS keeps polling."""
    p = NewsPrewarmer()
    assert p.is_enabled() is True


@pytest.mark.asyncio
async def test_disabled_newsapi_does_not_record_newsapi_telemetry(
        redis_double, disable_newsapi):
    """When the NewsAPI key is absent, that channel must be SKIPPED
    entirely — no Redis write to `channel_newsapi`. Otherwise the
    UI would show a permanent NewsAPI failure rate of 100%."""
    rss_hit = [{
        "zone": "mumbai", "severity": "severe", "strength": 0.65,
        "source": "rss", "title": "Fire in Mumbai",
        "expiry_window_s": 7200, "fetched_at": "2026-05-01T00:00:00+00:00",
        "raw_url": None,
    }]
    with patch(
        "app.services.external_signals.news_prewarmer.fetch_rss",
        new=AsyncMock(return_value=rss_hit),
    ):
        await run_prewarm_cycle()

    # No telemetry write under CHANNEL_NEWSAPI_KEY.
    newsapi_blob = redis_double.store.get(
        (np.TELEMETRY_NAMESPACE, CHANNEL_NEWSAPI_KEY)
    )
    assert newsapi_blob is None
    # RSS telemetry IS recorded.
    rss_blob = redis_double.store[
        (np.TELEMETRY_NAMESPACE, CHANNEL_RSS_KEY)
    ]
    assert rss_blob is not None
    assert rss_blob["last_success_ts"] is not None


@pytest.mark.asyncio
async def test_disabled_newsapi_rss_still_runs(
        redis_double, disable_newsapi):
    rss_hit = [{
        "zone": "delhi", "severity": "moderate", "strength": 0.40,
        "source": "rss", "title": "Accident in Delhi",
        "expiry_window_s": 7200, "fetched_at": "2026-05-01T00:00:00+00:00",
        "raw_url": None,
    }]
    with patch(
        "app.services.external_signals.news_prewarmer.fetch_rss",
        new=AsyncMock(return_value=rss_hit),
    ):
        result = await run_prewarm_cycle()
    assert result == {"status": "success", "news_count": 1}


def test_telemetry_surfaces_newsapi_disabled_flag(
        redis_double, disable_newsapi):
    out = get_prewarmer_telemetry()
    assert out["channels"]["newsapi"]["enabled"] is False
    assert out["channels"]["rss"]["enabled"] is True


# ════════════════════════════════════════════════════════════════════
# SSE replay tail — news_health is in the allow-list
# ════════════════════════════════════════════════════════════════════

def test_news_health_in_known_sources():
    from app.services.system_health_history import KNOWN_SOURCES
    assert "news_health" in KNOWN_SOURCES


def test_news_emitter_records_history(monkeypatch):
    from app.services import system_health_history as shh
    captured = {"calls": []}
    monkeypatch.setattr(
        shh, "record_transition",
        lambda src, payload: captured["calls"].append((src, payload)) or True,
    )

    class _NoBroadcaster:
        async def broadcast_to_operators(self, *a, **kw):
            return None

    import app.services.event_broadcaster as eb
    monkeypatch.setattr(eb, "broadcaster", _NoBroadcaster())

    np._emit_news_health_delta(
        prior_state="healthy",
        new_state="degraded",
        telemetry={
            "cache_age_seconds":  3600,
            "parse_failure_rate": 0.30,
            "active_news_count":  0,
            "last_success_ts":    "2026-05-01T00:00:00+00:00",
        },
    )
    assert len(captured["calls"]) == 1
    src, payload = captured["calls"][0]
    assert src == "news_health"
    assert payload["source"] == "news_health"
    assert payload["news_health"]["state"] == "degraded"


# ════════════════════════════════════════════════════════════════════
# Parse layer — keyword detection, zone detection, modifier build
# ════════════════════════════════════════════════════════════════════

def test_keyword_severity_locked():
    """Order matters — `riot` MUST outrank `fire` even if both are
    in the same headline."""
    assert detect_keyword_severity("Riots and fires in Delhi today") == "extreme"
    assert detect_keyword_severity("Fire reported in Mumbai") == "severe"
    assert detect_keyword_severity("Flood warning issued") == "severe"
    assert detect_keyword_severity("Major accident on highway") == "moderate"
    assert detect_keyword_severity("Crime rate up in Pune") == "moderate"
    assert detect_keyword_severity("Cricket match results") is None
    assert detect_keyword_severity(None) is None
    assert detect_keyword_severity("") is None


def test_keyword_detection_is_case_insensitive():
    assert detect_keyword_severity("FIRE in MUMBAI") == "severe"
    assert detect_keyword_severity("FloOd alert") == "severe"


def test_zone_detection():
    assert detect_zone("Fire breaks out in Mumbai today") == "mumbai"
    assert detect_zone("Accident reported in Delhi") == "delhi"
    assert detect_zone("Cricket match results") is None


def test_zone_detection_handles_punctuation():
    assert detect_zone("Mumbai: Fire breaks out at...") == "mumbai"
    assert detect_zone("Delhi - Accident on flyover.") == "delhi"


def test_build_modifier_skips_unactionable_headlines():
    """No keyword OR no zone → no modifier. Random news with no
    operational hook would otherwise inflate the active list."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assert build_modifier(
        "Cricket match in Mumbai", "newsapi", None, now,
    ) is None
    assert build_modifier(
        "Fire reported nationwide", "newsapi", None, now,
    ) is None


def test_build_modifier_succeeds_on_actionable_headline():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    m = build_modifier(
        "Fire breaks out in Mumbai", "newsapi",
        "http://example.com/a", now,
    )
    assert m is not None
    assert m["zone"] == "mumbai"
    assert m["severity"] == "severe"
    assert m["strength"] == SEVERITY_RISK["severe"]
    assert m["source"] == "newsapi"
    assert m["expiry_window_s"] == 7200


def test_rss_parse_extracts_items_from_rss20():
    rss_doc = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>NDTV India</title>
    <item>
      <title>Fire breaks out in Mumbai high-rise</title>
      <link>http://example.com/a</link>
    </item>
    <item>
      <title>Cricket: India wins ODI</title>
      <link>http://example.com/b</link>
    </item>
    <item>
      <title>Flood alert in Kerala</title>
      <link>http://example.com/c</link>
    </item>
  </channel>
</rss>"""
    out = parse_rss_items(rss_doc, "ndtv")
    assert out is not None
    # Only the two actionable headlines survive (Mumbai + Kerala).
    assert len(out) == 2
    zones = sorted(m["zone"] for m in out)
    assert zones == ["kerala", "mumbai"]


def test_rss_parse_returns_none_on_malformed():
    assert parse_rss_items(b"<<not xml>>", "ndtv") is None
    assert parse_rss_items(b"", "ndtv") is None


# ════════════════════════════════════════════════════════════════════
# City centroid table — read-only, audited shape
# ════════════════════════════════════════════════════════════════════

def test_centroid_table_is_well_formed():
    """Adding a city is a deliberate decision (no DB writes
    allowed). Every entry must be a (lat, lng) tuple within Indian
    geography."""
    for city, (lat, lng) in INDIAN_CITY_CENTROIDS.items():
        # India roughly spans lat 8-37, lng 68-97.
        assert 5.0 <= lat <= 38.0, f"{city} lat out of range"
        assert 67.0 <= lng <= 98.0, f"{city} lng out of range"
        assert city == city.lower()
        assert " " not in city, f"{city} contains space"


def test_keywords_match_spec():
    """Spec locked the keyword set — accidental edits to the
    keyword list should require updating this test alongside."""
    keywords = {k for k, _ in KEYWORD_SEVERITY}
    assert keywords == {"flood", "riot", "accident", "fire", "crime"}
