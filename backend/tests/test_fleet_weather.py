# Phase 6 — Fleet Weather Service unit tests
import asyncio
from unittest.mock import AsyncMock, patch

from app.services.fleet_weather_service import (
    BENGALURU_CELLS, run_grid_refresh_cycle, _impact_band, get_grid,
)


def _run(coro):
    return asyncio.run(coro)


def test_grid_has_nine_cells():
    assert len(BENGALURU_CELLS) == 9
    cell_ids = {c["cell_id"] for c in BENGALURU_CELLS}
    assert "center" in cell_ids
    assert len(cell_ids) == 9  # all unique


def test_impact_band_thresholds():
    assert _impact_band(0.0) == "low"
    assert _impact_band(0.19) == "low"
    assert _impact_band(0.20) == "medium"
    assert _impact_band(0.49) == "medium"
    assert _impact_band(0.50) == "high"
    assert _impact_band(1.0) == "high"


def test_unknown_city_returns_error():
    out = _run(run_grid_refresh_cycle("not-a-city"))
    assert out.get("error") == "unknown_city"
    assert out["cells"] == []


def test_refresh_cycle_emits_delta_on_first_run():
    """First run with empty prev cache should fire one fleet delta."""
    fake_weather = {
        "source": "openweather", "condition_id": 800, "condition": "clear",
        "temp_c": 25, "wind_kmh": 5, "visibility_m": 10000, "rain_1h_mm": 0,
        "description": "clear sky", "icon": "01d",
    }
    with patch("app.services.fleet_weather_service.get_weather", new=AsyncMock(return_value=fake_weather)), \
         patch("app.services.fleet_weather_service.redis_service.set_json", return_value=True), \
         patch("app.services.fleet_weather_service.redis_service.get_json", return_value=None), \
         patch("app.services.fleet_weather_service.emit_cc_delta", new=AsyncMock(return_value=True)) as mock_emit:
        grid = _run(run_grid_refresh_cycle("bengaluru"))
        assert len(grid["cells"]) == 9
        assert all(c["source"] == "openweather" for c in grid["cells"])
        # Condition changed for all 9 cells from None → 'clear', so delta fires
        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs.get("scope") == "fleet"


def test_refresh_cycle_no_delta_when_state_unchanged():
    """Identical consecutive cycles must NOT emit (debounce)."""
    fake_weather = {
        "source": "openweather", "condition_id": 800, "condition": "clear",
        "temp_c": 25, "wind_kmh": 5, "visibility_m": 10000, "rain_1h_mm": 0,
        "description": "clear sky", "icon": "01d",
    }
    # Build a "previous" snapshot that matches what the new cycle will compute
    prev_cells = [
        {"cell_id": s["cell_id"], "lat": s["lat"], "lng": s["lng"],
         "source": "openweather", "condition": "clear", "risk": 0.0,
         "impact": "low", "description": "clear sky"}
        for s in BENGALURU_CELLS
    ]
    prev_grid = {"city": "bengaluru", "cells": prev_cells}
    with patch("app.services.fleet_weather_service.get_weather", new=AsyncMock(return_value=fake_weather)), \
         patch("app.services.fleet_weather_service.redis_service.set_json", return_value=True), \
         patch("app.services.fleet_weather_service.redis_service.get_json", return_value=prev_grid), \
         patch("app.services.fleet_weather_service.emit_cc_delta", new=AsyncMock(return_value=True)) as mock_emit:
        _run(run_grid_refresh_cycle("bengaluru"))
        mock_emit.assert_not_called()


def test_refresh_cycle_emits_when_risk_crosses_threshold():
    """Risk shift ≥ 0.10 should emit, sub-threshold should not."""
    high_risk_weather = {
        "source": "openweather", "condition_id": 502, "condition": "rain",
        "temp_c": 22, "wind_kmh": 30, "visibility_m": 8000, "rain_1h_mm": 5.0,
        "description": "heavy rain", "icon": "10d",
    }
    prev_cells = [
        {"cell_id": s["cell_id"], "lat": s["lat"], "lng": s["lng"],
         "source": "openweather", "condition": "rain", "risk": 0.0,
         "impact": "low", "description": "light rain"}
        for s in BENGALURU_CELLS
    ]
    prev_grid = {"city": "bengaluru", "cells": prev_cells}
    with patch("app.services.fleet_weather_service.get_weather", new=AsyncMock(return_value=high_risk_weather)), \
         patch("app.services.fleet_weather_service.redis_service.set_json", return_value=True), \
         patch("app.services.fleet_weather_service.redis_service.get_json", return_value=prev_grid), \
         patch("app.services.fleet_weather_service.emit_cc_delta", new=AsyncMock(return_value=True)) as mock_emit:
        _run(run_grid_refresh_cycle("bengaluru"))
        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["scope"] == "fleet"
        # Each cell that changed should contribute risk + impact paths
        change_keys = list(mock_emit.call_args.args[1].keys()) if len(mock_emit.call_args.args) > 1 else list(mock_emit.call_args.kwargs.get("changes", {}).keys())
        assert any("risk" in k for k in change_keys)
