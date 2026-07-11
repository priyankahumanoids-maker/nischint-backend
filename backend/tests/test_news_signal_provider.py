"""News hot-path provider — feature-flag default + behaviour locks.

The prewarmer keeps the news cache fresh regardless of the flag.
This test file locks two invariants:

  1. `EXTERNAL_SIGNAL_NEWS_ENABLED` default OFF — flipping the
     class on by accident in a future PR is the regression we
     guard against. The whole point of shipping news behind a
     flag is to defer modifier effect on alert confidence until
     V2 ramp completes.

  2. Zone resolution + modifier picking — pure helpers used by
     `_fetch_unsafe`. Tested independently so the integration
     point doesn't need a running prewarmer.
"""
from __future__ import annotations

import os

import pytest

from app.services.external_signals.news_provider import (
    NEWS_ZONE_RADIUS_KM,
    NewsSignalProvider,
    find_nearest_zone,
    news_hot_path_enabled,
    pick_strongest_modifier,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EXTERNAL_SIGNAL_NEWS_ENABLED", raising=False)
    yield


def test_default_is_disabled():
    """Flag absent → provider disabled. Locks the gating contract."""
    assert news_hot_path_enabled() is False
    assert NewsSignalProvider().is_enabled() is False


@pytest.mark.parametrize("truthy", ["1", "true", "yes", "on", "TRUE"])
def test_truthy_values_enable(monkeypatch, truthy):
    monkeypatch.setenv("EXTERNAL_SIGNAL_NEWS_ENABLED", truthy)
    assert news_hot_path_enabled() is True
    assert NewsSignalProvider().is_enabled() is True


@pytest.mark.parametrize("falsy", ["", "0", "false", "no", "off"])
def test_falsy_values_remain_disabled(monkeypatch, falsy):
    monkeypatch.setenv("EXTERNAL_SIGNAL_NEWS_ENABLED", falsy)
    assert news_hot_path_enabled() is False
    assert NewsSignalProvider().is_enabled() is False


def test_zone_resolution_returns_closest_city():
    """Mumbai centroid input → mumbai slug."""
    assert find_nearest_zone(19.08, 72.88) == "mumbai"
    assert find_nearest_zone(28.61, 77.21) == "delhi"


def test_zone_resolution_returns_none_outside_radius():
    """Far from any Indian centroid → None. Locks the 75km radius."""
    assert find_nearest_zone(0.0, -160.0) is None
    # San Francisco — definitely not in zone.
    assert find_nearest_zone(37.77, -122.41) is None


def test_zone_resolution_handles_none_inputs():
    assert find_nearest_zone(None, 72.88) is None
    assert find_nearest_zone(19.08, None) is None


def test_pick_strongest_modifier_picks_highest_severity():
    mods = [
        {"zone": "mumbai", "severity": "minor"},
        {"zone": "mumbai", "severity": "severe"},
        {"zone": "mumbai", "severity": "moderate"},
        {"zone": "delhi",  "severity": "extreme"},
    ]
    assert pick_strongest_modifier(mods, "mumbai")["severity"] == "severe"
    assert pick_strongest_modifier(mods, "delhi")["severity"] == "extreme"


def test_pick_strongest_modifier_returns_none_on_mismatch():
    mods = [{"zone": "delhi", "severity": "extreme"}]
    assert pick_strongest_modifier(mods, "mumbai") is None
    assert pick_strongest_modifier([], "mumbai") is None
    assert pick_strongest_modifier(mods, "") is None


def test_radius_constant_locked():
    """A future PR widening the radius silently would change which
    cities a given (lat,lng) resolves to. Locked at 75km."""
    assert NEWS_ZONE_RADIUS_KM == 75.0


def test_provider_registered_in_registry():
    """News must appear in `_PROVIDERS` so flipping the flag is a
    no-restart change. If a future refactor de-registers it, this
    test catches it."""
    from app.services.external_signals.registry import _PROVIDERS
    names = {p.name for p in _PROVIDERS}
    assert "news" in names
