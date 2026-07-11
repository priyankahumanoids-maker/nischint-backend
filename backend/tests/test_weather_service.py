# Phase 4 — Weather Service unit tests (pure logic only, no HTTP)
from app.services.weather_service import compute_weather_risk


def _w(**kw):
    base = {"source": "openweather", "condition_id": 800, "wind_kmh": 10,
            "visibility_m": 10000, "rain_1h_mm": 0.0, "temp_c": 22}
    base.update(kw)
    return base


def test_clear_weather_no_risk():
    score, factors = compute_weather_risk(_w())
    assert score == 0.0
    assert factors == []


def test_thunderstorm_high_risk():
    score, factors = compute_weather_risk(_w(condition_id=200))
    assert score >= 0.40
    assert "thunderstorm" in factors


def test_tornado_caps_at_one():
    score, factors = compute_weather_risk(_w(condition_id=781, wind_kmh=80, visibility_m=200))
    assert score == 1.0  # bounded
    assert "tornado" in factors


def test_heavy_rain_not_double_counted():
    # condition_id 502 is heavy_rain AND rain_1h_mm above threshold; should
    # not add the same factor twice.
    score, factors = compute_weather_risk(_w(condition_id=502, rain_1h_mm=8.0))
    assert factors.count("heavy_rain") == 1
    assert score >= 0.30


def test_low_visibility_adds_signal():
    score, factors = compute_weather_risk(_w(visibility_m=400))
    assert "very_low_visibility" in factors
    assert score >= 0.5


def test_heatwave_signal():
    score, factors = compute_weather_risk(_w(temp_c=45))
    assert "extreme_heat" in factors


def test_unavailable_source_is_neutral():
    score, factors = compute_weather_risk({"source": "unavailable"})
    assert score == 0.0
    assert factors == []


def test_none_input_is_neutral():
    score, factors = compute_weather_risk(None)
    assert score == 0.0
    assert factors == []
