"""NISCH-012 — Live Activity Class chip (per-user motion telemetry view).

Locks the additive contract for the operator-facing chip:

  1. The unified Command Center payload exposes a `motion_telemetry`
     slot per selected user.
  2. The slot's `status` band aligns with the trust evaluator's
     freshness bands (live ≤ 60 s, fresh ≤ 5 min, recent ≤ 30 min,
     stale > 30 min).
  3. When the user has no motion windows, the slot is present with
     `status="unavailable"` — the UI never needs to guard against a
     missing key.
  4. Activity class returned is exactly the writer-boundary enum
     (`stationary|walking|running|vehicle|anomalous`).
  5. Pure observational helper — `_build_motion_telemetry_view` has
     ZERO write paths and never raises (caller wraps in try/except
     but the function itself only SELECTs).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.api.command_center_unified import (
    _motion_status_band,
    _MOTION_LIVE_S,
    _MOTION_FRESH_S,
    _MOTION_RECENT_S,
)


# ── Status-band invariants (pure function) ───────────────────────


def test_status_band_unavailable_when_no_freshness():
    assert _motion_status_band(None) == "unavailable"


def test_status_band_live_at_zero():
    assert _motion_status_band(0.0) == "live"


def test_status_band_live_at_upper_edge():
    assert _motion_status_band(_MOTION_LIVE_S) == "live"


def test_status_band_fresh_above_live_boundary():
    assert _motion_status_band(_MOTION_LIVE_S + 0.1) == "fresh"


def test_status_band_fresh_at_upper_edge():
    assert _motion_status_band(_MOTION_FRESH_S) == "fresh"


def test_status_band_recent_above_fresh_boundary():
    assert _motion_status_band(_MOTION_FRESH_S + 0.1) == "recent"


def test_status_band_recent_at_upper_edge():
    assert _motion_status_band(_MOTION_RECENT_S) == "recent"


def test_status_band_stale_above_recent_boundary():
    assert _motion_status_band(_MOTION_RECENT_S + 0.1) == "stale"


def test_status_band_stale_extreme_value():
    """Stale stays stale no matter how far past the threshold —
    never escalates to a non-existent severity band."""
    assert _motion_status_band(24 * 3600) == "stale"


# ── Band ordering — locked alignment with trust-tile bands ────────


def test_band_thresholds_match_trust_evaluator():
    """The chip bands must align with the trust-tile bands so
    operators don't see contradictory states (e.g. trust says
    `motion_telemetry_stale` while the chip still says `recent`).
    LOCKED: 30-min `recent` boundary == MOTION_FRESHNESS_MEDIUM_RED_S
    in trust.py."""
    from app.services.behavioral.trust import (
        MOTION_FRESHNESS_MEDIUM_RED_S,
    )
    assert _MOTION_RECENT_S == MOTION_FRESHNESS_MEDIUM_RED_S


# ── Helper-shape invariants (smoke, no DB) ────────────────────────


def test_helper_signature_uses_only_now_and_session():
    """The helper is read-only — must accept (session, entity_id, now)
    and return a dict. Locked so future refactors don't bolt on
    write paths or external HTTP."""
    from app.api.command_center_unified import (
        _build_motion_telemetry_view,
    )
    import inspect
    sig = inspect.signature(_build_motion_telemetry_view)
    assert list(sig.parameters) == ["session", "entity_id", "now"]


@pytest.mark.asyncio
async def test_helper_returns_unavailable_shape_on_no_rows(monkeypatch):
    """When no motion windows exist for an entity the helper must
    return the `unavailable` envelope — never raise, never return
    None. UI relies on this shape to render the stale chip."""
    from app.api.command_center_unified import (
        _build_motion_telemetry_view,
    )

    class _StubResult:
        def first(self):
            return None

    class _StubSession:
        async def execute(self, *_a, **_kw):
            return _StubResult()

    out = await _build_motion_telemetry_view(
        _StubSession(), entity_id="00000000-0000-0000-0000-000000000000",
        now=datetime.now(timezone.utc),
    )
    assert out["status"] == "unavailable"
    assert out["activity_class"] is None
    assert out["last_motion_at"] is None
    assert out["freshness_s"] is None
    assert out["window_count_24h"] == 0
    assert out["activity_distribution_24h"] is None


@pytest.mark.asyncio
async def test_helper_classifies_live_when_window_is_fresh():
    """A 5-second-old window must classify as `live` and carry the
    full distribution + pipeline_version."""
    from app.api.command_center_unified import (
        _build_motion_telemetry_view,
    )

    now = datetime.now(timezone.utc)
    latest = now - timedelta(seconds=5)

    class _Row:
        def __init__(self, vals):
            self._v = vals

        def __getitem__(self, i):
            return self._v[i]

    class _StubResult:
        def first(self):
            return _Row([
                "walking", latest, "motion-2026.02.1",
                12, 4, 6, 1, 1, 0,
            ])

    class _StubSession:
        async def execute(self, *_a, **_kw):
            return _StubResult()

    out = await _build_motion_telemetry_view(
        _StubSession(), entity_id="00000000-0000-0000-0000-000000000000",
        now=now,
    )
    assert out["status"] == "live"
    assert out["activity_class"] == "walking"
    assert out["freshness_s"] == 5.0
    assert out["window_count_24h"] == 12
    assert out["activity_distribution_24h"] == {
        "stationary": 4, "walking": 6, "running": 1,
        "vehicle": 1,   "anomalous": 0,
    }
    assert out["telemetry_pipeline_version"] == "motion-2026.02.1"


@pytest.mark.asyncio
async def test_helper_classifies_stale_when_window_is_old():
    """A 2-hour-old window must classify as `stale` (past the
    30-min `recent` boundary)."""
    from app.api.command_center_unified import (
        _build_motion_telemetry_view,
    )

    now = datetime.now(timezone.utc)
    latest = now - timedelta(hours=2)

    class _Row:
        def __init__(self, vals):
            self._v = vals

        def __getitem__(self, i):
            return self._v[i]

    class _StubResult:
        def first(self):
            return _Row([
                "stationary", latest, "motion-2026.02.1",
                0, 0, 0, 0, 0, 0,
            ])

    class _StubSession:
        async def execute(self, *_a, **_kw):
            return _StubResult()

    out = await _build_motion_telemetry_view(
        _StubSession(), entity_id="00000000-0000-0000-0000-000000000000",
        now=now,
    )
    assert out["status"] == "stale"
    assert out["activity_class"] == "stationary"
    assert out["freshness_s"] > 1800
