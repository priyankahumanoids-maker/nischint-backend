"""REL-09 Step 2 — OWM OneCall 3.0 alerts provider + prewarmer tests.

What's locked:
  * `is_enabled()` gates on `OPENWEATHER_API_KEY`.
  * `parse_alerts` drops minor-severity items and rejects malformed
    payloads.
  * `pick_strongest` ranks by inferred severity.
  * `nearest_metro` returns None outside the 75 km radius.
  * `_merge_with_cached` preserves per-metro state when one metro
    fails (the core cache-preservation contract).
  * Prewarmer `run_cycle`:
       - returns `disabled` when key absent
       - persists merged dict on partial success
       - returns `no_fresh_items` and preserves cache when ALL metros fail
  * `OWMAlertsSignalProvider._fetch_unsafe` reads the cache and
    emits an ExternalSignal with `provider=weather_alerts`,
    confidence=0.75 (lower than SACHET's 0.85 to preserve SACHET
    primacy in the blended risk score).
"""
from __future__ import annotations

import pytest

from app.services.external_signals.owm_alerts_provider import (
    METROS, OWMAlertsSignalProvider,
    _merge_with_cached, infer_severity, nearest_metro, parse_alerts,
    pick_strongest,
)


# ── Pure helper tests ──────────────────────────────────────────────


@pytest.mark.parametrize("event,expected", [
    ("Tornado Warning",            "extreme"),
    ("Cyclone Approaching",        "extreme"),
    ("Severe Thunderstorm",        "severe"),
    ("Heavy Rain Alert",           "severe"),
    ("Heatwave Advisory",          "severe"),
    ("Thunderstorm Warning",       "severe"),     # explicit warning lands severe
    ("Thunderstorm",               "moderate"),
    ("Lightning Activity",         "moderate"),
    ("Light Rain",                 "minor"),
    ("",                           "minor"),
])
def test_infer_severity_grid(event, expected):
    assert infer_severity(event, tags=[]) == expected


def test_infer_severity_uses_tags():
    # event is generic; tags carry the severity signal.
    assert infer_severity("Weather Advisory", tags=["thunderstorm"]) == "moderate"
    assert infer_severity("Weather Advisory", tags=["cyclone"]) == "extreme"


def test_parse_alerts_drops_minor_severity():
    payload = {
        "alerts": [
            {"event": "Tornado Warning", "tags": [], "sender_name": "IMD"},
            {"event": "Light Drizzle",   "tags": [], "sender_name": "OWM"},
            {"event": "Severe Flood",    "tags": [], "sender_name": "NDMA"},
        ]
    }
    out = parse_alerts(payload, metro="mumbai")
    events = {a["event"] for a in out}
    assert "Tornado Warning" in events
    assert "Severe Flood" in events
    assert "Light Drizzle" not in events     # minor filter dropped it
    for a in out:
        assert a["metro"] == "mumbai"
        assert a["severity"] in ("extreme", "severe", "moderate")


def test_parse_alerts_rejects_malformed():
    assert parse_alerts(None, "mumbai") == []
    assert parse_alerts({"alerts": "not-a-list"}, "mumbai") == []
    assert parse_alerts({"alerts": []}, "mumbai") == []
    # Item with no event is skipped silently
    assert parse_alerts({"alerts": [{"foo": "bar"}]}, "mumbai") == []


def test_pick_strongest_ranks_by_severity():
    alerts = [
        {"event": "Thunderstorm", "severity": "moderate"},
        {"event": "Cyclone", "severity": "extreme"},
        {"event": "Heatwave", "severity": "severe"},
    ]
    top = pick_strongest(alerts)
    assert top["severity"] == "extreme"
    assert top["event"] == "Cyclone"


def test_pick_strongest_empty_returns_none():
    assert pick_strongest([]) is None


@pytest.mark.parametrize("lat,lng,expected", [
    (19.0760, 72.8777, "mumbai"),       # bullseye
    (28.65,   77.20,   "delhi"),        # bullseye
    (12.97,   77.59,   "bengaluru"),    # bullseye
    (20.0,    72.9,    None),           # ~100km north of Mumbai → outside 75km
    (0.0,     0.0,     None),           # mid-ocean
])
def test_nearest_metro_radius_gate(lat, lng, expected):
    assert nearest_metro(lat, lng) == expected


def test_nearest_metro_none_inputs():
    assert nearest_metro(None, None) is None
    assert nearest_metro(19.0, None) is None


def test_merge_preserves_failed_metro_state():
    cached = {
        "mumbai": [{"event": "Old Cyclone", "severity": "extreme"}],
        "delhi":  [{"event": "Old Heatwave", "severity": "severe"}],
    }
    # mumbai succeeds fresh; delhi missing from fresh (failed this cycle)
    fresh = {"mumbai": [{"event": "New Storm", "severity": "severe"}]}
    merged = _merge_with_cached(fresh, cached)
    assert merged["mumbai"][0]["event"] == "New Storm"           # overwritten
    assert merged["delhi"][0]["event"] == "Old Heatwave"         # preserved


def test_merge_handles_empty_cache():
    fresh = {"chennai": [{"event": "Cyclone Warning", "severity": "extreme"}]}
    merged = _merge_with_cached(fresh, None)
    assert merged == fresh


def test_merge_drops_unknown_keys():
    # Defends against stale cache shape from a prior version.
    cached = {"mars": [{"event": "Dust Storm"}]}
    merged = _merge_with_cached({}, cached)
    assert "mars" not in merged
    assert merged == {}


# ── Provider tests ─────────────────────────────────────────────────


def test_provider_disabled_without_key(monkeypatch):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    assert OWMAlertsSignalProvider().is_enabled() is False


def test_provider_enabled_with_key(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-12345")
    assert OWMAlertsSignalProvider().is_enabled() is True


@pytest.mark.asyncio
async def test_provider_no_metro_no_signal(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")
    p = OWMAlertsSignalProvider()
    # Mid-ocean → no metro → no signal
    sig = await p._fetch_unsafe(0.0, 0.0)
    assert sig is None


@pytest.mark.asyncio
async def test_provider_emits_signal_when_cache_has_metro(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")

    async def _fake_cached():
        return {
            "mumbai": [
                {
                    "metro": "mumbai",
                    "event": "Cyclone Tauktae",
                    "severity": "extreme",
                    "sender": "IMD",
                    "tags": ["cyclone"],
                }
            ]
        }
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_provider.get_alerts_cached",
        _fake_cached,
    )

    p = OWMAlertsSignalProvider()
    sig = await p._fetch_unsafe(19.08, 72.88)        # central Mumbai
    assert sig is not None
    assert sig.provider == "weather_alerts"
    assert sig.signal_type == "owm_extreme"
    assert sig.risk_0_1 == 0.95
    assert sig.confidence == 0.75
    factors = sig.factors
    assert "owm_alert_extreme" in factors
    assert "metro:mumbai" in factors
    # SACHET stays primary — OWM confidence (0.75) MUST be lower
    # than SACHET's (0.85). Locked here so a future change can't
    # accidentally invert the priority.
    from app.services.external_signals.sachet_provider import SachetSignalProvider
    # SACHET's signals are emitted at confidence=0.85 (hardcoded
    # in `sachet_provider._fetch_unsafe`). We assert the inequality
    # at the provider level rather than reaching into the static.
    assert sig.confidence < 0.85


@pytest.mark.asyncio
async def test_provider_cold_cache_returns_none(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")

    async def _empty_cache():
        return {}
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_provider.get_alerts_cached",
        _empty_cache,
    )

    p = OWMAlertsSignalProvider()
    sig = await p._fetch_unsafe(19.08, 72.88)
    assert sig is None


# ── Prewarmer tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prewarmer_disabled_when_no_key(monkeypatch):
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    from app.services.external_signals.owm_alerts_prewarmer import run_prewarm_cycle
    result = await run_prewarm_cycle()
    assert result["status"] == "disabled"
    assert result["reason"] == "no_api_key"


@pytest.mark.asyncio
async def test_prewarmer_persists_on_partial_success(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")

    # Simulate 3 of 6 metros responding successfully.
    async def _fresh():
        return {
            "mumbai": [{"event": "Cyclone Foo", "severity": "extreme"}],
            "delhi":  [],
            "chennai": [{"event": "Heatwave", "severity": "severe"}],
        }
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_prewarmer.fetch_all_metros",
        _fresh,
    )
    written: dict = {}
    def _set_json(ns, key, val, ttl=None):
        # Capture by (ns, key) — `_record_attempt` and the state
        # writer also use set_json, so we must filter to the cache
        # namespace to avoid the last-write-wins trap.
        written[(ns, key)] = val
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_prewarmer.redis_service.set_json",
        _set_json,
    )

    async def _empty_cached():
        return {}
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_prewarmer.get_alerts_cached",
        _empty_cached,
    )

    from app.services.external_signals.owm_alerts_prewarmer import run_prewarm_cycle
    result = await run_prewarm_cycle()
    assert result["status"] == "success"
    assert result["metros_fresh"] == 3
    assert result["active_alerts"] == 2          # extreme + severe; empty bucket has 0
    cache_write = written[("owm_alerts", "alerts_by_metro_v1")]
    assert "mumbai" in cache_write
    assert "chennai" in cache_write
    # delhi included with empty list (succeeded but no alerts)
    assert cache_write["delhi"] == []


@pytest.mark.asyncio
async def test_prewarmer_preserves_cache_on_total_failure(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "k")

    async def _empty_fresh():
        return {}
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_prewarmer.fetch_all_metros",
        _empty_fresh,
    )
    # set_json MUST NOT be called with the cache namespace on total
    # failure (other set_json calls — telemetry, state — are fine).
    cache_write_called = {"yes": False}
    def _set_json(ns, key, *_a, **_kw):
        if ns == "owm_alerts" and key == "alerts_by_metro_v1":
            cache_write_called["yes"] = True
    monkeypatch.setattr(
        "app.services.external_signals.owm_alerts_prewarmer.redis_service.set_json",
        _set_json,
    )

    from app.services.external_signals.owm_alerts_prewarmer import run_prewarm_cycle
    result = await run_prewarm_cycle()
    assert result["status"] == "no_fresh_items"
    assert result["metros_fresh"] == 0
    assert cache_write_called["yes"] is False


def test_prewarmer_jitter_bounds():
    """User-spec: 15-min cadence. Locked: ±60 s jitter."""
    from app.services.external_signals.owm_alerts_prewarmer import (
        JITTER_BASE_S, JITTER_RANGE_S, compute_next_interval_seconds,
    )
    assert JITTER_BASE_S == 900
    assert JITTER_RANGE_S == 60
    for _ in range(20):
        v = compute_next_interval_seconds()
        assert 840 <= v <= 960


# ── Registry integration ──────────────────────────────────────────


def test_registered_in_provider_list():
    """OWM alerts MUST be in the canonical registry list so
    `fetch_all_signals` picks it up. SACHET primacy is preserved
    because providers are additive (not priority-ordered)."""
    from app.services.external_signals.registry import _PROVIDERS
    provider_names = {p.name for p in _PROVIDERS}
    assert "weather_alerts" in provider_names
    assert "sachet" in provider_names           # SACHET still present
