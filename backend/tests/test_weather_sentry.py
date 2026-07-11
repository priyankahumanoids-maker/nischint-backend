"""REL-09 fan-out — Weather / OWM → Sentry observability tests.

Covers BOTH:
  * Pure `weather_sentry` helpers (tags, fingerprint, metric).
  * End-to-end through the OWM OneCall 3.0 alerts provider
    `_fetch_one` — 401/403 defensive contract (OWM tier not
    activated yet) MUST forward to Sentry with channel/metro tags
    without breaking the cache merge.
"""
from __future__ import annotations

import pytest

from tests._sentry_fakes import FakeSentry


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = FakeSentry()
    monkeypatch.setattr(
        "app.services.external_signals.weather_sentry._sentry",
        lambda: fake,
    )
    return fake


@pytest.fixture
def disable_sentry(monkeypatch):
    monkeypatch.setattr(
        "app.services.external_signals.weather_sentry._sentry",
        lambda: None,
    )


# ── Pure helper tests ──────────────────────────────────────────────


def test_fetch_failure_tags_channel_and_metro(fake_sentry):
    from app.services.external_signals.weather_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=403,
        upstream_url="https://api.openweathermap.org/data/3.0/onecall",
        response_time_ms=420.0,
        is_proxy=False,
        channel="onecall_alerts",
        metro="mumbai",
    )
    ev = fake_sentry.events[0]
    assert ev["tags"]["provider"] == "weather"
    assert ev["tags"]["channel"] == "onecall_alerts"
    assert ev["tags"]["metro"] == "mumbai"
    assert ev["tags"]["status_code"] == "403"


def test_fetch_failure_metric_named_weather(fake_sentry):
    from app.services.external_signals.weather_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=401, upstream_url="x", response_time_ms=10.0,
        is_proxy=False, channel="onecall_alerts", metro="delhi",
    )
    name, tags = fake_sentry.metrics.counters[0]
    assert name == "weather.fetch.failure"
    assert tags["channel"] == "onecall_alerts"
    assert tags["metro"] == "delhi"


def test_fetch_failure_disabled_sentry_is_noop(disable_sentry):
    from app.services.external_signals.weather_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=403, upstream_url="x", response_time_ms=1.0,
        is_proxy=False, channel="onecall_alerts",
    )  # must not raise


def test_transition_uses_weather_fingerprint(fake_sentry):
    from app.services.external_signals.weather_sentry import report_health_transition
    report_health_transition("healthy", "degraded", {})
    ev = fake_sentry.events[0]
    assert ev["fingerprint"] == ["weather-degraded"]


def test_degraded_to_healthy_recovery_is_info(fake_sentry):
    from app.services.external_signals.weather_sentry import report_health_transition
    report_health_transition("degraded", "healthy", {})
    ev = fake_sentry.events[0]
    assert ev["level"] == "info"


# ── End-to-end through OWM OneCall alerts `_fetch_one` ─────────────


@pytest.mark.asyncio
async def test_owm_alerts_401_reports_defensively(monkeypatch, fake_sentry):
    """The 401/403 path is the headline of the user's spec:
    OneCall 3.0 not yet activated on the OWM dashboard must NOT
    break the existing per-request WeatherProvider — `_fetch_one`
    returns None (cache preserved) and Sentry sees a defensive
    warning with channel=onecall_alerts + metro=mumbai."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key-12345")

    class _FakeResponse:
        status_code = 401

    class _FakeClient:
        async def get(self, *_a, **_kw):
            return _FakeResponse()

    from app.services.external_signals.owm_alerts_provider import _fetch_one
    out = await _fetch_one(_FakeClient(), "mumbai", 19.07, 72.87)
    assert out is None        # 401 → preserve cache, no signal
    ev = fake_sentry.events[0]
    assert ev["level"] == "warning"
    assert ev["tags"]["channel"] == "onecall_alerts"
    assert ev["tags"]["metro"] == "mumbai"
    assert ev["tags"]["status_code"] == "401"


@pytest.mark.asyncio
async def test_owm_alerts_403_reports_defensively(monkeypatch, fake_sentry):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key-12345")

    class _FakeResponse:
        status_code = 403

    class _FakeClient:
        async def get(self, *_a, **_kw):
            return _FakeResponse()

    from app.services.external_signals.owm_alerts_provider import _fetch_one
    out = await _fetch_one(_FakeClient(), "delhi", 28.6, 77.2)
    assert out is None
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "403"
    assert ev["tags"]["metro"] == "delhi"


@pytest.mark.asyncio
async def test_owm_alerts_exception_reports_defensively(monkeypatch, fake_sentry):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key-12345")

    class _FakeClient:
        async def get(self, *_a, **_kw):
            raise TimeoutError("owm hung")

    from app.services.external_signals.owm_alerts_provider import _fetch_one
    out = await _fetch_one(_FakeClient(), "kolkata", 22.57, 88.36)
    assert out is None
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "exception"
    assert ev["tags"]["metro"] == "kolkata"
    assert "TimeoutError" in ev["contexts"]["weather_fetch"]["error"]


@pytest.mark.asyncio
async def test_owm_alerts_200_does_not_report(monkeypatch, fake_sentry):
    """Happy path emits zero Sentry calls."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key-12345")

    class _FakeResponse:
        status_code = 200
        def json(self):
            return {"alerts": []}

    class _FakeClient:
        async def get(self, *_a, **_kw):
            return _FakeResponse()

    from app.services.external_signals.owm_alerts_provider import _fetch_one
    out = await _fetch_one(_FakeClient(), "chennai", 13.08, 80.27)
    assert out == []
    assert fake_sentry.events == []
    assert fake_sentry.metrics.counters == []
