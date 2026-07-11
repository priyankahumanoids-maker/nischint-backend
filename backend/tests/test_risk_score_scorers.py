"""Tests for the June-2026 compute_risk_score hot-path refactor.

The refactor extracted all I/O into a single `_prefetch_risk_inputs`
call and made the 5 sub-scores pure CPU. These tests lock the scoring
logic against regression — they don't hit the DB at all (everything is
fed via dicts, which is the new contract).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.guardian_ai_refinement import (
    _score_behavior_deviation,
    _score_location_risk,
    _score_device_risk,
    _score_response_risk,
)


def _now_at(hour: int) -> datetime:
    return datetime(2026, 6, 1, hour, 0, 0, tzinfo=timezone.utc)


def _empty_session():
    """Default session view — no idle / no route deviation / no risk."""
    class _S:
        current_location = None
        risk_level = None
        is_idle = False
        idle_duration_s = 0
        route_deviated = False
        route_deviation_m = 0
    return _S()


# ────────────────────────────────────────────────────────────
# behavior
# ────────────────────────────────────────────────────────────


def test_behavior_low_activity_late_night_triggers_factor():
    inputs = {
        "now": _now_at(23),
        "recent_active_session": _empty_session(),
        "alerts_24h": 0,
    }
    baseline = {"active_hours": {"23": "low"}, "normal_alerts_per_day": 1.0}
    score, factors = _score_behavior_deviation(inputs, baseline)
    assert score == 0.7
    assert "time_deviation" in factors


def test_behavior_idle_session_adds_inactivity_anomaly():
    sess = _empty_session()
    sess.is_idle = True
    sess.idle_duration_s = 900  # 15min
    inputs = {"now": _now_at(14), "recent_active_session": sess, "alerts_24h": 0}
    score, factors = _score_behavior_deviation(inputs, {"active_hours": {}})
    assert "inactivity_anomaly" in factors
    assert 0 < score <= 1.0


def test_behavior_route_deviated_adds_factor():
    sess = _empty_session()
    sess.route_deviated = True
    sess.route_deviation_m = 600
    inputs = {"now": _now_at(14), "recent_active_session": sess, "alerts_24h": 0}
    score, factors = _score_behavior_deviation(inputs, {"active_hours": {}})
    assert "route_deviation" in factors


def test_behavior_alert_spike_adds_factor():
    inputs = {
        "now": _now_at(14),
        "recent_active_session": _empty_session(),
        "alerts_24h": 10,
    }
    baseline = {"active_hours": {}, "normal_alerts_per_day": 1.0}
    score, factors = _score_behavior_deviation(inputs, baseline)
    assert "alert_spike" in factors


def test_behavior_quiet_normal_period_scores_zero():
    inputs = {"now": _now_at(14), "recent_active_session": _empty_session(), "alerts_24h": 0}
    score, factors = _score_behavior_deviation(inputs, {"active_hours": {}, "normal_alerts_per_day": 1.0})
    assert score == 0.0
    assert factors == []


# ────────────────────────────────────────────────────────────
# location
# ────────────────────────────────────────────────────────────


def test_location_far_from_common_locations_triggers_deviation():
    sess = _empty_session()
    sess.current_location = {"lat": 12.99, "lng": 77.99}
    sess.risk_level = "OK"
    inputs = {"now": _now_at(14), "recent_any_session": sess}
    baseline = {"common_locations": [{"lat": 12.95, "lng": 77.55}]}
    score, factors = _score_location_risk(inputs, baseline)
    assert "location_deviation" in factors
    assert score > 0.0


def test_location_high_risk_zone_overrides_deviation():
    sess = _empty_session()
    sess.current_location = {"lat": 12.95, "lng": 77.55}
    sess.risk_level = "CRITICAL"
    inputs = {"now": _now_at(14), "recent_any_session": sess}
    baseline = {"common_locations": []}
    score, factors = _score_location_risk(inputs, baseline)
    assert score == 0.9  # CRITICAL maps to 0.9
    assert "zone_risk_high" in factors


def test_location_no_session_returns_zero():
    inputs = {"now": _now_at(14), "recent_any_session": None}
    score, factors = _score_location_risk(inputs, {"common_locations": []})
    assert score == 0.0
    assert factors == []


# ────────────────────────────────────────────────────────────
# device
# ────────────────────────────────────────────────────────────


def test_device_no_incidents_zero():
    score, factors = _score_device_risk({"device_incidents_6h": 0})
    assert score == 0.0
    assert factors == []


def test_device_two_or_more_incidents_flags_offline():
    score, factors = _score_device_risk({"device_incidents_6h": 3})
    assert score > 0
    assert "device_offline" in factors
    assert "device_low_battery" in factors


# ────────────────────────────────────────────────────────────
# response
# ────────────────────────────────────────────────────────────


def test_response_no_caregivers_high_risk():
    score, factors = _score_response_risk({"caregivers_available": 0, "unacked_2h": 0})
    assert score == 0.8
    assert "no_caregiver_nearby" in factors


def test_response_single_caregiver_moderate_risk():
    score, factors = _score_response_risk({"caregivers_available": 1, "unacked_2h": 0})
    assert score == 0.3
    assert factors == []


def test_response_unacked_storm_overrides_low_caregiver_score():
    score, factors = _score_response_risk({"caregivers_available": 5, "unacked_2h": 5})
    assert score == 0.6
    assert "response_delay" in factors


def test_response_plenty_caregivers_zero_risk():
    score, factors = _score_response_risk({"caregivers_available": 5, "unacked_2h": 0})
    assert score == 0.0
    assert factors == []
