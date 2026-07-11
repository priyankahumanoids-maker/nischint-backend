# Phase 3 — Live Deviation Engine unit tests
#
# Pure-function tests. No DB / no network.

from datetime import datetime, timezone

from app.services.live_deviation_engine import compute_live_deviation


def _baseline(common_locations=None, active_hours=None, days=10):
    return {
        "data_days": days,
        "confidence": 0.7,
        "common_locations": common_locations or [
            {"lat": 12.97, "lng": 77.59, "frequency": 0.5},
        ],
        "active_hours": active_hours or {
            **{str(h): "high" for h in range(9, 19)},
            **{str(h): "low" for h in list(range(0, 9)) + list(range(19, 24))},
        },
    }


def test_no_baseline_returns_unknown():
    out = compute_live_deviation(None, lat=12.97, lng=77.59)
    assert out["status"] == "unknown"
    assert out["score"] == 0.0
    assert out["confidence"] == 0.0


def test_normal_state_at_known_location_during_active_hours():
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)  # 12:00 UTC, active hour
    out = compute_live_deviation(_baseline(), lat=12.97, lng=77.59, now=now)
    assert out["status"] == "normal"
    assert out["score"] == 0.0
    assert out["reason"] is None


def test_high_deviation_far_location_at_night():
    now = datetime(2026, 4, 27, 2, 30, tzinfo=timezone.utc)  # 02:30 deep night
    out = compute_live_deviation(_baseline(), lat=20.5, lng=78.5, now=now)
    # time(0.7)*0.30 + location(1.0)*0.30 = 0.51 → "high"
    assert out["status"] in ("high", "critical")
    assert out["score"] >= 0.5
    assert out["reason"] is not None


def test_critical_when_route_deviated_and_idle_off_route():
    now = datetime(2026, 4, 27, 22, 30, tzinfo=timezone.utc)  # late evening, "low" band
    out = compute_live_deviation(
        _baseline(),
        lat=12.99, lng=77.61,                  # ~3km from common location
        now=now,
        route_deviated=True, route_deviation_m=600,    # > full threshold
        is_idle=True, idle_duration_s=2000,           # > full threshold
    )
    # time(0.7)*0.30 + location(1.0)*0.30 + route(1.0)*0.20 + idle(1.0)*0.20 = 1.0 → critical
    assert out["status"] == "critical"
    assert out["score"] >= 0.75
    # Route signal has highest reason priority
    assert "route" in (f.get("factor") for f in out["factors"])


def test_slight_when_minor_drift():
    now = datetime(2026, 4, 27, 19, 30, tzinfo=timezone.utc)  # transition hour, low band
    out = compute_live_deviation(
        _baseline(),
        lat=12.97, lng=77.59,                  # at known location
        now=now,
    )
    # time only signal in low (non-deep-night): 0.4 * 0.30 = 0.12 → normal
    assert out["status"] in ("normal", "slight")


def test_confidence_low_when_baseline_immature():
    sparse = _baseline(days=1, common_locations=[])
    sparse["confidence"] = 0.2
    now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    out = compute_live_deviation(sparse, lat=12.97, lng=77.59, now=now)
    # No common locations → location signal is 0; should not flag deviation
    assert out["confidence"] <= 0.3
    assert out["status"] == "normal"
