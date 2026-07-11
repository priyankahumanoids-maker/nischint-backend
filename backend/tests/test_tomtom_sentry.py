"""REL-09 fan-out — TomTom → Sentry observability tests.

Mirrors `test_sachet_sentry.py` structure 1-for-1 but against
`tomtom_sentry` + an end-to-end probe through `_fetch_one`.

Locked:
  * `provider=tomtom` tag on every event.
  * `tomtom-degraded` fingerprint groups all degraded transitions.
  * `zone` tag forwarded on per-zone failures so a single flapping
    city is visually distinguishable from a global outage.
  * Sentry SDK unavailable → all helpers no-op, never raise.
"""
from __future__ import annotations

import pytest

from tests._sentry_fakes import FakeSentry


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = FakeSentry()
    monkeypatch.setattr(
        "app.services.external_signals.tomtom_sentry._sentry",
        lambda: fake,
    )
    return fake


@pytest.fixture
def disable_sentry(monkeypatch):
    monkeypatch.setattr(
        "app.services.external_signals.tomtom_sentry._sentry",
        lambda: None,
    )


# ── report_fetch_failure ───────────────────────────────────────────


def test_fetch_failure_with_status_code_tags_zone(fake_sentry):
    from app.services.external_signals.tomtom_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=503,
        upstream_url="https://api.tomtom.com/...",
        response_time_ms=820.0,
        is_proxy=False,
        zone="Mumbai",
    )
    assert len(fake_sentry.events) == 1
    ev = fake_sentry.events[0]
    assert ev["level"] == "warning"
    assert ev["tags"]["provider"] == "tomtom"
    assert ev["tags"]["status_code"] == "503"
    assert ev["tags"]["zone"] == "Mumbai"
    # context echoes the same extras
    assert ev["contexts"]["tomtom_fetch"]["zone"] == "Mumbai"


def test_fetch_failure_exception_path_uses_exception_tag(fake_sentry):
    from app.services.external_signals.tomtom_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=None,
        upstream_url="https://api.tomtom.com/...",
        response_time_ms=1000.0,
        is_proxy=False,
        error="ReadTimeout('flow segment')",
        zone="Delhi",
    )
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "exception"
    assert "exception" in ev["msg"]
    assert "ReadTimeout" in ev["contexts"]["tomtom_fetch"]["error"]


def test_fetch_failure_metric_incremented(fake_sentry):
    from app.services.external_signals.tomtom_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=502, upstream_url="x", response_time_ms=100.0,
        is_proxy=False, zone="Chennai",
    )
    assert len(fake_sentry.metrics.counters) == 1
    name, tags = fake_sentry.metrics.counters[0]
    assert name == "tomtom.fetch.failure"
    assert tags["status_code"] == "502"
    assert tags["zone"] == "Chennai"


def test_fetch_failure_disabled_sentry_is_noop(disable_sentry):
    from app.services.external_signals.tomtom_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=500, upstream_url="x", response_time_ms=1.0, is_proxy=False,
    )  # must not raise


# ── report_health_transition ───────────────────────────────────────


def test_transition_to_degraded_captures_with_fingerprint(fake_sentry):
    from app.services.external_signals.tomtom_sentry import report_health_transition
    report_health_transition(
        "healthy",
        "degraded",
        {"health_state": "degraded", "consecutive_failures": 3},
    )
    ev = fake_sentry.events[0]
    assert ev["level"] == "warning"
    assert ev["fingerprint"] == ["tomtom-degraded"]
    assert ev["tags"]["transition"] == "healthy->degraded"


def test_degraded_to_healthy_recovery_is_info_level(fake_sentry):
    from app.services.external_signals.tomtom_sentry import report_health_transition
    report_health_transition("degraded", "healthy", {})
    ev = fake_sentry.events[0]
    assert ev["level"] == "info"
    assert ev["fingerprint"] == ["tomtom-degraded"]
    assert "recovered" in ev["msg"].lower()


@pytest.mark.parametrize("prior,new", [
    ("healthy", "stale"),
    ("stale", "healthy"),
    ("healthy", "healthy"),
    ("degraded", "degraded"),
    ("unknown", "stale"),
])
def test_other_transitions_are_silent(prior, new, fake_sentry):
    from app.services.external_signals.tomtom_sentry import report_health_transition
    report_health_transition(prior, new, {})
    assert fake_sentry.events == []


# ── End-to-end through `_fetch_one` ──────────────────────────────


@pytest.mark.asyncio
async def test_e2e_http_503_reports_to_sentry(monkeypatch, fake_sentry):
    """The real `_fetch_one` must forward a 503 to
    `tomtom_sentry.report_fetch_failure` with `zone=Bengaluru`."""
    monkeypatch.setenv("TOMTOM_API_KEY", "test-key-12345")

    class _FakeResponse:
        status_code = 503

    class _FakeClient:
        async def get(self, *_a, **_kw):
            return _FakeResponse()

    from app.services.external_signals.tomtom_provider import _fetch_one
    out = await _fetch_one(_FakeClient(), "Bengaluru", 12.97, 77.59)
    assert out is None
    assert len(fake_sentry.events) == 1
    ev = fake_sentry.events[0]
    assert ev["tags"]["provider"] == "tomtom"
    assert ev["tags"]["zone"] == "Bengaluru"
    assert ev["tags"]["status_code"] == "503"


@pytest.mark.asyncio
async def test_e2e_exception_reports_to_sentry(monkeypatch, fake_sentry):
    monkeypatch.setenv("TOMTOM_API_KEY", "test-key-12345")

    class _FakeClient:
        async def get(self, *_a, **_kw):
            raise TimeoutError("tomtom hung")

    from app.services.external_signals.tomtom_provider import _fetch_one
    out = await _fetch_one(_FakeClient(), "Pune", 18.5, 73.8)
    assert out is None
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "exception"
    assert ev["tags"]["zone"] == "Pune"
    assert "TimeoutError" in ev["contexts"]["tomtom_fetch"]["error"]
