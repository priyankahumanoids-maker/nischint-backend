# Fleet Weather Grid — Phase 6
#
# A 3×3 city-level weather grid (9 cells) covering Bengaluru. Refreshed
# every 5 minutes by APScheduler. Reuses `weather_service.get_weather`
# (which is already Redis-cached at ~1km grid for 10 min) so we never
# generate duplicate upstream calls.
#
# Public API:
#   • get_grid(city)                — return the cached grid (Redis read)
#   • run_grid_refresh_cycle()      — recompute every cell + diff-emit deltas
#   • start_fleet_weather_scheduler — schedules the cycle every 5 min

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services import redis_service
from app.services.weather_service import get_weather, compute_weather_risk
from app.services.cc_delta_emitter import emit_cc_delta

logger = logging.getLogger(__name__)

REDIS_NAMESPACE = "fleet_weather_grid"
REDIS_LAST_CHANGE_NAMESPACE = "fleet_weather_last_change"
REDIS_TTL_SECONDS = 30 * 60  # 30m — stale after a missed refresh, but still
                             # available for last-known-state reads

# Impact band ranking (used for escalation detection)
_IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}

# 3×3 grid centered on Bengaluru (~5km cell spacing).
# Keep this list short and deterministic so cell IDs stay stable across
# restarts and the diff-emitter only fires on real changes.
BENGALURU_CELLS = [
    {"cell_id": "north_west",   "lat": 13.06, "lng": 77.55},
    {"cell_id": "north_center", "lat": 13.06, "lng": 77.59},
    {"cell_id": "north_east",   "lat": 13.06, "lng": 77.65},
    {"cell_id": "center_west",  "lat": 12.97, "lng": 77.55},
    {"cell_id": "center",       "lat": 12.97, "lng": 77.59},
    {"cell_id": "center_east",  "lat": 12.97, "lng": 77.65},
    {"cell_id": "south_west",   "lat": 12.88, "lng": 77.55},
    {"cell_id": "south_center", "lat": 12.88, "lng": 77.59},
    {"cell_id": "south_east",   "lat": 12.88, "lng": 77.65},
]

CITY_GRIDS = {"bengaluru": BENGALURU_CELLS}

# Diff threshold — only emit a fleet delta when a cell's risk shifts by at
# least this amount, OR its condition string changes. Prevents fleet-wide
# noise on tiny weather wobbles.
RISK_DELTA_THRESHOLD = 0.10

# ── Background-refresh tuning ────────────────────────────────────
# Same operational reflex codified for Sachet pre-warmer: the hot
# path needs a tight timeout (`weather_service.HTTP_TIMEOUT = 4.0 s`),
# but the fleet grid is background and should not time out 9 cells
# in lockstep when OpenWeather is briefly slow. A semaphore rate-
# spreads the burst within the free-tier budget — sleep would be
# dead time on the happy path, semaphore only kicks in when fetches
# actually overlap.
FLEET_REFRESH_TIMEOUT_S = 8.0
_REFRESH_CONCURRENCY = 3


def _impact_band(risk: float) -> str:
    if risk >= 0.5:
        return "high"
    if risk >= 0.2:
        return "medium"
    return "low"


def _redis_key(city: str) -> str:
    return city


def get_grid(city: str = "bengaluru") -> Optional[dict]:
    """Read the latest cached grid for `city`. None if never computed."""
    try:
        return redis_service.get_json(REDIS_NAMESPACE, _redis_key(city))
    except Exception:
        logger.exception("[FLEET_WX] read failed city=%s", city)
        return None


async def _build_cell(
    spec: dict,
    *,
    timeout_s: Optional[float] = None,
) -> dict:
    """Compute one cell's weather snapshot. Always returns a dict.

    `timeout_s` forwards to `get_weather`; when None the hot-path
    default applies. Fleet refresh passes the generous background
    budget so a slow upstream doesn't poison all 9 cells in lockstep."""
    if timeout_s is not None:
        weather = await get_weather(spec["lat"], spec["lng"], timeout_s=timeout_s)
    else:
        weather = await get_weather(spec["lat"], spec["lng"])
    risk, factors = compute_weather_risk(weather) if weather else (0.0, [])
    src = (weather or {}).get("source", "unavailable")
    return {
        "cell_id": spec["cell_id"],
        "lat": spec["lat"],
        "lng": spec["lng"],
        "source": src,
        "condition": (weather or {}).get("condition") if src == "openweather" else None,
        "description": (weather or {}).get("description") if src == "openweather" else None,
        "icon": (weather or {}).get("icon") if src == "openweather" else None,
        "temp_c": (weather or {}).get("temp_c") if src == "openweather" else None,
        "wind_kmh": (weather or {}).get("wind_kmh") if src == "openweather" else None,
        "visibility_m": (weather or {}).get("visibility_m") if src == "openweather" else None,
        "risk": float(risk),
        "impact": _impact_band(float(risk)),
        "risk_factors": factors,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def run_grid_refresh_cycle(city: str = "bengaluru") -> dict:
    """
    Recompute every cell + diff against the previous snapshot. When a cell's
    risk moves by ≥ RISK_DELTA_THRESHOLD or its condition string changes,
    emit a fleet-scoped COMMAND_CENTER_DELTA. Returns the new grid.
    """
    cells_spec = CITY_GRIDS.get(city)
    if not cells_spec:
        return {"city": city, "cells": [], "error": "unknown_city"}

    prev = get_grid(city) or {}
    prev_cells_by_id = {c.get("cell_id"): c for c in (prev.get("cells") or [])}

    # Run each cell concurrently, capped by `_REFRESH_CONCURRENCY` so a
    # briefly-slow OpenWeather doesn't time out all 9 cells in lockstep.
    # Generous background budget — hot path keeps its tight default.
    sema = asyncio.Semaphore(_REFRESH_CONCURRENCY)

    async def _bounded(spec):
        async with sema:
            return await _build_cell(spec, timeout_s=FLEET_REFRESH_TIMEOUT_S)

    new_cells = await asyncio.gather(*[_bounded(s) for s in cells_spec])

    grid = {
        "city": city,
        "cells": new_cells,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "version": "v1",
    }
    redis_service.set_json(REDIS_NAMESPACE, _redis_key(city), grid, ttl=REDIS_TTL_SECONDS)

    # ── Diff + emit fleet delta only for materially-changed cells ──
    changes: dict = {}
    cells_updated = 0
    cells_escalated = 0
    cells_deescalated = 0
    escalation_breakdown: list[dict] = []

    for idx, cell in enumerate(new_cells):
        prev_cell = prev_cells_by_id.get(cell["cell_id"]) or {}
        risk_changed = abs(float(cell.get("risk") or 0) - float(prev_cell.get("risk") or 0)) >= RISK_DELTA_THRESHOLD
        condition_changed = (cell.get("condition") or "") != (prev_cell.get("condition") or "")
        if risk_changed:
            changes[f"fleet_weather_grid.cells[{idx}].risk"] = cell["risk"]
            changes[f"fleet_weather_grid.cells[{idx}].impact"] = cell["impact"]
        if condition_changed:
            changes[f"fleet_weather_grid.cells[{idx}].condition"] = cell.get("condition")
            changes[f"fleet_weather_grid.cells[{idx}].description"] = cell.get("description")
        if risk_changed or condition_changed:
            changes[f"fleet_weather_grid.cells[{idx}].cell_id"] = cell["cell_id"]
            changes[f"fleet_weather_grid.cells[{idx}].updated_at"] = cell["updated_at"]
            cells_updated += 1

            # Phase 7 — escalation detection (low→medium→high)
            old_rank = _IMPACT_RANK.get(prev_cell.get("impact") or "low", 0)
            new_rank = _IMPACT_RANK.get(cell.get("impact") or "low", 0)
            if new_rank > old_rank:
                cells_escalated += 1
                escalation_breakdown.append({
                    "cell_id": cell["cell_id"],
                    "from": prev_cell.get("impact") or "low",
                    "to": cell.get("impact") or "low",
                    "direction": "up",
                })
            elif new_rank < old_rank:
                cells_deescalated += 1
                escalation_breakdown.append({
                    "cell_id": cell["cell_id"],
                    "from": prev_cell.get("impact") or "low",
                    "to": cell.get("impact") or "low",
                    "direction": "down",
                })

    if changes:
        try:
            await emit_cc_delta(
                user_id="__fleet__",  # sentinel — frontend matches on scope
                changes=changes,
                scope="fleet",
            )
            logger.info("[FLEET_WX] delta emitted city=%s changed_cells=%d", city, len({k.split('[')[1].split(']')[0] for k in changes}))
        except Exception:
            logger.exception("[FLEET_WX] delta emit failed city=%s", city)

    # ── Phase 7 — Change summary (perception layer) ──
    # Lightweight separate event so the UI can render a glanceable badge
    # without parsing the full COMMAND_CENTER_DELTA payload.
    if cells_updated > 0:
        change_summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "city": city,
            "cells_updated": cells_updated,
            "cells_escalated": cells_escalated,
            "cells_deescalated": cells_deescalated,
            "breakdown": escalation_breakdown,
        }
        try:
            redis_service.set_json(
                REDIS_LAST_CHANGE_NAMESPACE, _redis_key(city),
                change_summary, ttl=REDIS_TTL_SECONDS,
            )
        except Exception:
            logger.exception("[FLEET_WX] last_change cache write failed")

        try:
            from app.services.event_broadcaster import broadcaster
            await broadcaster.broadcast_to_operators(
                "FLEET_CHANGE_SUMMARY",
                {
                    "scope": "fleet",
                    "timestamp": change_summary["timestamp"],
                    "summary": {
                        "cells_updated": cells_updated,
                        "cells_escalated": cells_escalated,
                        "cells_deescalated": cells_deescalated,
                    },
                    "breakdown": escalation_breakdown,
                },
            )
            logger.info(
                "[FLEET_CHANGE] city=%s updated=%d escalated=%d deescalated=%d",
                city, cells_updated, cells_escalated, cells_deescalated,
            )
        except Exception:
            logger.exception("[FLEET_CHANGE] broadcast failed")

    return grid


def get_last_change(city: str = "bengaluru") -> dict | None:
    """Read the most recent change summary from Redis."""
    try:
        return redis_service.get_json(REDIS_LAST_CHANGE_NAMESPACE, _redis_key(city))
    except Exception:
        return None


# ── Scheduler ─────────────────────────────────────────────────────────
_scheduler: AsyncIOScheduler | None = None


def start_fleet_weather_scheduler():
    """Start the 5-min APScheduler tick. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    # Allow ops to disable in CI/dev via env var
    if os.environ.get("DISABLE_FLEET_WEATHER", "").lower() in ("1", "true", "yes"):
        logger.info("[FLEET_WX] scheduler disabled via DISABLE_FLEET_WEATHER")
        return None

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        run_grid_refresh_cycle,
        "interval",
        minutes=5,
        id="fleet_weather_refresh",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # run once at startup
    )
    _scheduler.start()
    logger.info("[FLEET_WX] scheduler started (5-min cycle, city=bengaluru)")
    return _scheduler


def shutdown_fleet_weather_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
