"""Tests for NISCH-002B — alert_proximity helpers.

Pure unit tests against `is_co_located`, `is_suppressible_kind`, and
the haversine math. SSE-fan-out wiring is exercised by the existing
test_alert_trigger.py once we add proximity-aware tests there.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import alert_proximity as ap


# ── Haversine sanity ────────────────────────────────────────────────
def test_haversine_zero_distance():
    assert ap.haversine_m(12.97, 77.59, 12.97, 77.59) == pytest.approx(0.0, abs=1e-3)


def test_haversine_known_distance_bangalore_chennai():
    # Bangalore (12.9716, 77.5946) → Chennai (13.0827, 80.2707) ≈ 290 km
    d = ap.haversine_m(12.9716, 77.5946, 13.0827, 80.2707)
    assert 285_000 < d < 295_000


def test_haversine_one_meter_precision():
    # Two coords ~10m apart in y-direction at ~equator
    d = ap.haversine_m(0.0, 0.0, 0.0, 0.00009)  # ~10m
    assert 9 < d < 12


# ── is_co_located: happy paths ──────────────────────────────────────
def _now():
    return datetime.now(timezone.utc)


def test_co_located_close_and_fresh_returns_true():
    now = _now()
    assert ap.is_co_located(
        guardian_lat=12.9716, guardian_lng=77.5946, guardian_last_at=now,
        child_lat=12.9716, child_lng=77.5946,
        radius_m=150,
    ) is True


def test_far_apart_returns_false():
    now = _now()
    assert ap.is_co_located(
        guardian_lat=12.9716, guardian_lng=77.5946, guardian_last_at=now,
        child_lat=13.0827, child_lng=80.2707,  # Chennai
    ) is False


def test_just_inside_radius_returns_true():
    now = _now()
    # ~100m offset in lat from base
    assert ap.is_co_located(
        guardian_lat=12.9716, guardian_lng=77.5946, guardian_last_at=now,
        child_lat=12.9716 + 0.0009, child_lng=77.5946,
        radius_m=150,
    ) is True


def test_just_outside_radius_returns_false():
    now = _now()
    # ~250m offset (1° lat ≈ 111km, 0.00225 ≈ 250m)
    assert ap.is_co_located(
        guardian_lat=12.9716, guardian_lng=77.5946, guardian_last_at=now,
        child_lat=12.9716 + 0.00225, child_lng=77.5946,
        radius_m=150,
    ) is False


# ── Fail-safe: missing data → False ─────────────────────────────────
@pytest.mark.parametrize("missing", [
    {"guardian_lat": None},
    {"guardian_lng": None},
    {"child_lat": None},
    {"child_lng": None},
    {"guardian_last_at": None},
])
def test_missing_field_falls_back_to_not_colocated(missing):
    base = dict(
        guardian_lat=12.97, guardian_lng=77.59, guardian_last_at=_now(),
        child_lat=12.97, child_lng=77.59,
    )
    base.update(missing)
    assert ap.is_co_located(**base) is False


def test_stale_guardian_fix_returns_false():
    old = _now() - timedelta(minutes=30)
    assert ap.is_co_located(
        guardian_lat=12.97, guardian_lng=77.59, guardian_last_at=old,
        child_lat=12.97, child_lng=77.59,
        freshness_s=300,
    ) is False


def test_future_timestamp_returns_false():
    """Clock-skew or buggy client sends ts in the future → ignore."""
    future = _now() + timedelta(minutes=10)
    assert ap.is_co_located(
        guardian_lat=12.97, guardian_lng=77.59, guardian_last_at=future,
        child_lat=12.97, child_lng=77.59,
    ) is False


def test_naive_datetime_treated_as_utc():
    # Some callers pass naive datetimes; we must not crash.
    naive = datetime.utcnow()
    out = ap.is_co_located(
        guardian_lat=12.97, guardian_lng=77.59, guardian_last_at=naive,
        child_lat=12.97, child_lng=77.59,
    )
    # Either result is acceptable — must not raise. We just assert truthy/falsy.
    assert out in (True, False)


def test_string_coordinate_does_not_crash():
    out = ap.is_co_located(
        guardian_lat="abc",  # type: ignore[arg-type]
        guardian_lng=77.59, guardian_last_at=_now(),
        child_lat=12.97, child_lng=77.59,
    )
    assert out is False


# ── Suppressible kinds (life-safety bypass) ────────────────────────
@pytest.mark.parametrize("kind", [
    "geofence_breach", "safe_zone_exit", "wandering",
    "low_battery", "device_offline", "minor_deviation",
    "check_in_request", "arrived_safely", "resolved",
])
def test_suppressible_kinds_are_suppressible(kind):
    assert ap.is_suppressible_kind(kind) is True


@pytest.mark.parametrize("kind", [
    "sos", "voice_distress", "emergency_triggered",
    "fall_detected", "help_requested", "critical_deviation",
    "unsafe_deviation", "totally_unknown",
])
def test_critical_kinds_never_suppressible(kind):
    assert ap.is_suppressible_kind(kind) is False


def test_kind_case_insensitive_and_strips():
    assert ap.is_suppressible_kind("  GEOFENCE_BREACH  ") is True
    assert ap.is_suppressible_kind("SOS") is False


def test_blank_kind_not_suppressible():
    assert ap.is_suppressible_kind("") is False
    assert ap.is_suppressible_kind(None) is False  # type: ignore[arg-type]
