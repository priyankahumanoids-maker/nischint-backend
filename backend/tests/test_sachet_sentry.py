"""REL-09 — Tests for the SACHET → Sentry observability hooks.

We don't drive a real Sentry client — we monkeypatch the `sentry_sdk`
import target inside `sachet_sentry._sentry` to a recorder object,
then assert what got captured.

What's locked down:
  1. Non-200 fetch fires `report_fetch_failure` with correct context
     (status_code, url, response_time_ms, is_proxy, colo).
  2. Exception fetch fires `report_fetch_failure` with status_code=None
     and `error=...`.
  3. via_proxy is computed correctly from `SACHET_PROXY_URL` env.
  4. The CF `x-sachet-proxy-colo` header is captured and tagged.
  5. `report_health_transition`:
       * fires on `* → degraded` with stable fingerprint
       * fires on `degraded → healthy` with level=info + same fingerprint
       * does NOT fire for any other transition.
  6. Sentry SDK unavailable → all helpers are no-ops, never raise.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest


# ── Fake Sentry SDK ─────────────────────────────────────────────────


class _FakeScope:
    def __init__(self, recorder: dict[str, Any]):
        self._rec = recorder
        self._rec["scope_tags"] = {}
        self._rec["scope_contexts"] = {}
        self._rec["scope_fingerprint"] = None

    def set_tag(self, k, v):
        self._rec["scope_tags"][k] = v

    def set_context(self, k, v):
        self._rec["scope_contexts"][k] = v

    @property
    def fingerprint(self):
        return self._rec["scope_fingerprint"]

    @fingerprint.setter
    def fingerprint(self, v):
        self._rec["scope_fingerprint"] = v


class _FakeMetrics:
    def __init__(self):
        self.counters: list[tuple[str, dict]] = []

    def incr(self, name, *, tags=None, **_):
        self.counters.append((name, dict(tags or {})))


class _FakeSentry:
    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.metrics = _FakeMetrics()

    @contextmanager
    def push_scope(self):
        rec: dict[str, Any] = {}
        scope = _FakeScope(rec)
        self._pending = rec
        try:
            yield scope
        finally:
            self._pending = rec  # held for next capture_message call

    def capture_message(self, msg, level="warning"):
        # Snapshot the scope state with this capture so we can assert
        # they were paired correctly.
        snap = {
            "msg": msg,
            "level": level,
            "tags": dict(self._pending.get("scope_tags", {})),
            "contexts": dict(self._pending.get("scope_contexts", {})),
            "fingerprint": self._pending.get("scope_fingerprint"),
        }
        self.events.append(snap)


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = _FakeSentry()
    monkeypatch.setattr(
        "app.services.external_signals.sachet_sentry._sentry",
        lambda: fake,
    )
    return fake


@pytest.fixture
def disable_sentry(monkeypatch):
    """Forces `_sentry()` to return None — exercises the no-op path."""
    monkeypatch.setattr(
        "app.services.external_signals.sachet_sentry._sentry",
        lambda: None,
    )


# ── report_fetch_failure ───────────────────────────────────────────


def test_fetch_failure_with_status_code_captures_context(fake_sentry):
    from app.services.external_signals.sachet_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=504,
        upstream_url="https://sachet-proxy.example.workers.dev/cap_public_website/rss/rss_india.xml",
        response_time_ms=1234.56,
        is_proxy=True,
        colo="BOM",
    )
    assert len(fake_sentry.events) == 1
    ev = fake_sentry.events[0]
    assert ev["level"] == "warning"
    assert "504" in ev["msg"]
    assert ev["tags"]["provider"] == "sachet"
    assert ev["tags"]["via_proxy"] == "true"
    assert ev["tags"]["status_code"] == "504"
    assert ev["tags"]["cf_colo"] == "BOM"
    ctx = ev["contexts"]["sachet_fetch"]
    assert ctx["status_code"] == 504
    assert ctx["response_time_ms"] == 1234.56
    assert ctx["is_proxy"] is True
    assert ctx["colo"] == "BOM"


def test_fetch_failure_exception_path_uses_exception_tag(fake_sentry):
    from app.services.external_signals.sachet_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=None,
        upstream_url="https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml",
        response_time_ms=5000.0,
        is_proxy=False,
        error="ReadTimeout('NDMA hung')",
    )
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "exception"
    assert ev["tags"]["via_proxy"] == "false"
    assert "exception" in ev["msg"]
    assert "ReadTimeout" in ev["contexts"]["sachet_fetch"]["error"]


def test_fetch_failure_metric_incremented(fake_sentry):
    from app.services.external_signals.sachet_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=502, upstream_url="x", response_time_ms=100.0,
        is_proxy=True,
    )
    assert len(fake_sentry.metrics.counters) == 1
    name, tags = fake_sentry.metrics.counters[0]
    assert name == "sachet.fetch.failure"
    assert tags == {"status_code": "502", "via_proxy": "true"}


def test_fetch_failure_disabled_sentry_is_noop(disable_sentry):
    # Must not raise even when sentry_sdk import returns None.
    from app.services.external_signals.sachet_sentry import report_fetch_failure
    report_fetch_failure(
        status_code=504, upstream_url="x", response_time_ms=1.0, is_proxy=False,
    )


# ── report_health_transition ───────────────────────────────────────


def test_transition_to_degraded_captures_with_fingerprint(fake_sentry):
    from app.services.external_signals.sachet_sentry import report_health_transition
    report_health_transition(
        "healthy",
        "degraded",
        {"health_state": "degraded", "consecutive_failures": 3, "active_alert_count": 0},
    )
    assert len(fake_sentry.events) == 1
    ev = fake_sentry.events[0]
    assert ev["level"] == "warning"
    assert ev["fingerprint"] == ["sachet-degraded"]
    assert ev["tags"]["transition"] == "healthy->degraded"
    assert ev["contexts"]["sachet_health"]["consecutive_failures"] == 3


def test_transition_from_stale_to_degraded_also_fires(fake_sentry):
    from app.services.external_signals.sachet_sentry import report_health_transition
    report_health_transition("stale", "degraded", {})
    assert len(fake_sentry.events) == 1


def test_degraded_to_healthy_recovery_is_info_level(fake_sentry):
    from app.services.external_signals.sachet_sentry import report_health_transition
    report_health_transition(
        "degraded",
        "healthy",
        {"health_state": "healthy", "consecutive_successes": 3},
    )
    ev = fake_sentry.events[0]
    assert ev["level"] == "info"
    assert ev["fingerprint"] == ["sachet-degraded"]
    assert "recovered" in ev["msg"].lower()


@pytest.mark.parametrize("prior,new", [
    ("healthy", "stale"),
    ("stale", "healthy"),
    ("healthy", "healthy"),
    ("unknown", "stale"),
    ("unknown", "healthy"),   # boot recovery — already known-good
    ("degraded", "degraded"),
    ("healthy", "unknown"),
])
def test_other_transitions_are_silent(prior, new, fake_sentry):
    from app.services.external_signals.sachet_sentry import report_health_transition
    report_health_transition(prior, new, {})
    assert fake_sentry.events == [], f"{prior}->{new} should not capture"


def test_transition_disabled_sentry_is_noop(disable_sentry):
    from app.services.external_signals.sachet_sentry import report_health_transition
    report_health_transition("healthy", "degraded", {})


# ── End-to-end through `_fetch_feed_uncached` ──────────────────────


@pytest.mark.asyncio
async def test_fetch_504_through_provider_reports_to_sentry(monkeypatch, fake_sentry):
    """Top-level integration: the real `_fetch_feed_uncached` must
    call `report_fetch_failure` with `is_proxy=True` + the colo
    header from the response."""
    monkeypatch.setenv("SACHET_PROXY_URL", "https://sachet-proxy.example.workers.dev")

    class _FakeResponse:
        status_code = 504
        headers = {"x-sachet-proxy-colo": "BOM"}
        content = b""

    class _FakeClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_e): return False
        async def get(self, _url, headers=None):
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.external_signals.sachet_provider.httpx.AsyncClient",
        _FakeClient,
    )

    from app.services.external_signals.sachet_provider import _fetch_feed_uncached
    out = await _fetch_feed_uncached()
    assert out == []          # failure → empty list
    assert len(fake_sentry.events) == 1
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "504"
    assert ev["tags"]["via_proxy"] == "true"
    assert ev["tags"]["cf_colo"] == "BOM"
    ctx = ev["contexts"]["sachet_fetch"]
    assert ctx["status_code"] == 504
    assert ctx["is_proxy"] is True


@pytest.mark.asyncio
async def test_fetch_exception_through_provider_reports_to_sentry(monkeypatch, fake_sentry):
    monkeypatch.delenv("SACHET_PROXY_URL", raising=False)

    class _FakeClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_e): return False
        async def get(self, _url, headers=None):
            raise TimeoutError("upstream timed out")

    monkeypatch.setattr(
        "app.services.external_signals.sachet_provider.httpx.AsyncClient",
        _FakeClient,
    )

    from app.services.external_signals.sachet_provider import _fetch_feed_uncached
    out = await _fetch_feed_uncached()
    assert out == []
    ev = fake_sentry.events[0]
    assert ev["tags"]["status_code"] == "exception"
    assert ev["tags"]["via_proxy"] == "false"
    assert "TimeoutError" in ev["contexts"]["sachet_fetch"]["error"]


@pytest.mark.asyncio
async def test_fetch_200_does_not_report_to_sentry(monkeypatch, fake_sentry):
    """Happy path must NOT emit any Sentry calls — telemetry should
    only fire on real degradation."""
    monkeypatch.delenv("SACHET_PROXY_URL", raising=False)

    class _FakeResponse:
        status_code = 200
        headers = {}
        content = b"<rss><channel></channel></rss>"

    class _FakeClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_e): return False
        async def get(self, _url, headers=None):
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.external_signals.sachet_provider.httpx.AsyncClient",
        _FakeClient,
    )

    from app.services.external_signals.sachet_provider import _fetch_feed_uncached
    await _fetch_feed_uncached()
    assert fake_sentry.events == []
    assert fake_sentry.metrics.counters == []
