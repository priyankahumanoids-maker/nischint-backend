import math

from app.services.guardian_mode_engine import (
    _remaining_route_distance_m,
    _smooth_eta_minutes,
    _smooth_speed_mps,
)


def test_remaining_route_distance_uses_polyline_not_direct_destination_only():
    route = {
        "points": [
            {"lat": 19.0000, "lng": 72.0000},
            {"lat": 19.0010, "lng": 72.0000},
            {"lat": 19.0010, "lng": 72.0010},
        ]
    }
    remaining = _remaining_route_distance_m(19.0005, 72.0000, route)
    assert remaining is not None
    # Half of first segment + full second segment: materially above the direct
    # diagonal shortcut from the current point to the destination.
    direct = math.hypot(0.0005 * 111_320, 0.0010 * 111_320 * math.cos(math.radians(19.0)))
    assert remaining > direct


def test_speed_smoothing_adapts_from_walk_to_vehicle_without_single_sample_jump():
    walking = _smooth_speed_mps(1.3, 1.4, 1.5)
    first_vehicle = _smooth_speed_mps(walking, 9.0, 10.0)
    sustained_vehicle = first_vehicle
    for _ in range(5):
        sustained_vehicle = _smooth_speed_mps(sustained_vehicle, 9.5, 10.0)
    assert 1.0 < walking < 2.0
    assert walking < first_vehicle < 10.0
    assert sustained_vehicle > first_vehicle


def test_eta_smoothing_rejects_one_fix_spike_but_converges():
    current = 30.0
    first = _smooth_eta_minutes(current, 6.0)
    assert 6.0 < first < current
    for _ in range(6):
        first = _smooth_eta_minutes(first, 6.0)
    assert first < 15.0
