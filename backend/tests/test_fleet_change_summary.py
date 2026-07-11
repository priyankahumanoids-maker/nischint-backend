# Phase 7 — Fleet Change Indicator (perception layer) tests
import asyncio
from unittest.mock import AsyncMock, patch

from app.services.fleet_weather_service import (
    BENGALURU_CELLS, run_grid_refresh_cycle,
)


def _run(coro):
    return asyncio.run(coro)


def _fake_weather(condition_id=800, condition="clear", description="clear sky", **extra):
    base = {
        "source": "openweather", "condition_id": condition_id,
        "condition": condition, "description": description, "icon": "01d",
        "temp_c": 25, "wind_kmh": 5, "visibility_m": 10000, "rain_1h_mm": 0,
    }
    base.update(extra)
    return base


def test_change_summary_emitted_on_first_run():
    """First-ever cycle should emit FLEET_CHANGE_SUMMARY (all cells fresh)."""
    with patch("app.services.fleet_weather_service.get_weather", new=AsyncMock(return_value=_fake_weather())), \
         patch("app.services.fleet_weather_service.redis_service.set_json", return_value=True), \
         patch("app.services.fleet_weather_service.redis_service.get_json", return_value=None), \
         patch("app.services.fleet_weather_service.emit_cc_delta", new=AsyncMock(return_value=True)), \
         patch("app.services.event_broadcaster.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        _run(run_grid_refresh_cycle("bengaluru"))
        # Find the FLEET_CHANGE_SUMMARY broadcast specifically
        calls = [c for c in mock_b.broadcast_to_operators.call_args_list
                 if c.args[0] == "FLEET_CHANGE_SUMMARY"]
        assert len(calls) == 1
        payload = calls[0].args[1]
        assert payload["scope"] == "fleet"
        assert payload["summary"]["cells_updated"] == 9


def test_no_change_summary_when_state_unchanged():
    """Second identical cycle must NOT emit FLEET_CHANGE_SUMMARY."""
    fake = _fake_weather()
    prev_cells = [
        {"cell_id": s["cell_id"], "lat": s["lat"], "lng": s["lng"],
         "source": "openweather", "condition": "clear", "description": "clear sky",
         "risk": 0.0, "impact": "low"}
        for s in BENGALURU_CELLS
    ]
    prev_grid = {"city": "bengaluru", "cells": prev_cells}
    with patch("app.services.fleet_weather_service.get_weather", new=AsyncMock(return_value=fake)), \
         patch("app.services.fleet_weather_service.redis_service.set_json", return_value=True), \
         patch("app.services.fleet_weather_service.redis_service.get_json", return_value=prev_grid), \
         patch("app.services.fleet_weather_service.emit_cc_delta", new=AsyncMock(return_value=True)), \
         patch("app.services.event_broadcaster.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        _run(run_grid_refresh_cycle("bengaluru"))
        change_calls = [c for c in mock_b.broadcast_to_operators.call_args_list
                        if c.args[0] == "FLEET_CHANGE_SUMMARY"]
        assert len(change_calls) == 0


def test_escalation_count_when_low_to_high():
    """Going from clear → heavy thunderstorm should record escalations."""
    prev_cells = [
        {"cell_id": s["cell_id"], "lat": s["lat"], "lng": s["lng"],
         "source": "openweather", "condition": "clear", "description": "clear sky",
         "risk": 0.0, "impact": "low"}
        for s in BENGALURU_CELLS
    ]
    prev_grid = {"city": "bengaluru", "cells": prev_cells}
    severe = _fake_weather(condition_id=200, condition="thunderstorm",
                           description="thunderstorm", visibility_m=400)
    with patch("app.services.fleet_weather_service.get_weather", new=AsyncMock(return_value=severe)), \
         patch("app.services.fleet_weather_service.redis_service.set_json", return_value=True), \
         patch("app.services.fleet_weather_service.redis_service.get_json", return_value=prev_grid), \
         patch("app.services.fleet_weather_service.emit_cc_delta", new=AsyncMock(return_value=True)), \
         patch("app.services.event_broadcaster.broadcaster") as mock_b:
        mock_b.broadcast_to_operators = AsyncMock()
        _run(run_grid_refresh_cycle("bengaluru"))
        change_calls = [c for c in mock_b.broadcast_to_operators.call_args_list
                        if c.args[0] == "FLEET_CHANGE_SUMMARY"]
        assert len(change_calls) == 1
        payload = change_calls[0].args[1]
        assert payload["summary"]["cells_updated"] == 9
        assert payload["summary"]["cells_escalated"] == 9
        assert payload["summary"]["cells_deescalated"] == 0
        assert all(b["direction"] == "up" for b in payload["breakdown"])
