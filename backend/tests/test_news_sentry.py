"""REL-09 fan-out — News → Sentry observability tests.

Locked:
  * `provider=news` tag on every event.
  * `news-degraded` fingerprint groups all degraded transitions.
  * `channel` tag (`newsapi` | `rss`) on every failure.
  * `feed` extra tag set on RSS-specific failures.
  * Sentry SDK unavailable → all helpers no-op, never raise.
"""
from __future__ import annotations

import pytest

from tests._sentry_fakes import FakeSentry


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = FakeSentry()
    monkeypatch.setattr(
        "app.services.external_signals.news_sentry._sentry",
        lambda: fake,
    )
    return fake


@pytest.fixture
def disable_sentry(monkeypatch):
    monkeypatch.setattr(
        "app.services.external_signals.news_sentry._sentry",
        lambda: None,
    )


def test_fetch_failure_with_channel_newsapi(fake_sentry):
    from app.services.external_signals.news_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=429,
        upstream_url="https://newsapi.org/v2/everything",
        response_time_ms=120.0,
        is_proxy=False,
        channel="newsapi",
    )
    ev = fake_sentry.events[0]
    assert ev["tags"]["provider"] == "news"
    assert ev["tags"]["channel"] == "newsapi"
    assert ev["tags"]["status_code"] == "429"


def test_fetch_failure_rss_carries_feed_tag(fake_sentry):
    from app.services.external_signals.news_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=None,
        upstream_url="https://feeds.feedburner.com/ndtvnews-top-stories",
        response_time_ms=2000.0,
        is_proxy=False,
        error="ReadTimeout",
        channel="rss",
        feed="ndtv",
    )
    ev = fake_sentry.events[0]
    assert ev["tags"]["channel"] == "rss"
    assert ev["tags"]["feed"] == "ndtv"
    assert ev["contexts"]["news_fetch"]["feed"] == "ndtv"


def test_metric_includes_channel_tag(fake_sentry):
    from app.services.external_signals.news_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=500, upstream_url="x", response_time_ms=100.0,
        is_proxy=False, channel="newsapi",
    )
    name, tags = fake_sentry.metrics.counters[0]
    assert name == "news.fetch.failure"
    assert tags["channel"] == "newsapi"


def test_fetch_failure_disabled_sentry_is_noop(disable_sentry):
    from app.services.external_signals.news_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=500, upstream_url="x", response_time_ms=1.0, is_proxy=False,
        channel="rss",
    )  # must not raise


def test_transition_to_degraded_fingerprint(fake_sentry):
    from app.services.external_signals.news_sentry import report_health_transition
    report_health_transition(
        "healthy", "degraded", {"consecutive_failures": 4},
    )
    ev = fake_sentry.events[0]
    assert ev["level"] == "warning"
    assert ev["fingerprint"] == ["news-degraded"]


def test_degraded_to_healthy_recovery_is_info(fake_sentry):
    from app.services.external_signals.news_sentry import report_health_transition
    report_health_transition("degraded", "healthy", {})
    ev = fake_sentry.events[0]
    assert ev["level"] == "info"
    assert ev["fingerprint"] == ["news-degraded"]


# ── End-to-end through `fetch_newsapi` ──────────────────────────


@pytest.mark.asyncio
async def test_newsapi_http_500_reports_with_channel_tag(monkeypatch, fake_sentry):
    monkeypatch.setenv("NEWSAPI_KEY", "test-key-12345")

    class _FakeResponse:
        status_code = 500

    class _FakeClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_e): return False
        async def get(self, *_a, **_kw):
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.external_signals.news_provider.httpx.AsyncClient",
        _FakeClient,
    )

    from app.services.external_signals.news_provider import fetch_newsapi
    out = await fetch_newsapi()
    assert out is None
    ev = fake_sentry.events[0]
    assert ev["tags"]["channel"] == "newsapi"
    assert ev["tags"]["status_code"] == "500"


@pytest.mark.asyncio
async def test_rss_per_feed_failure_carries_feed_tag(monkeypatch, fake_sentry):
    class _FakeResponse:
        status_code = 502

    class _FakeClient:
        async def get(self, *_a, **_kw):
            return _FakeResponse()

    from app.services.external_signals.news_provider import _fetch_rss_one
    out = await _fetch_rss_one(_FakeClient(), "toi", "https://example.com/toi.rss")
    assert out is None
    ev = fake_sentry.events[0]
    assert ev["tags"]["channel"] == "rss"
    assert ev["tags"]["feed"] == "toi"
