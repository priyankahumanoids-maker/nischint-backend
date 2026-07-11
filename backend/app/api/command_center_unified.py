# Command Center — Unified Per-User Endpoint (Phase 1)
#
# Single source of truth for one user's full safety state. Replaces the 7
# fragmented calls the frontend currently makes (risk-score, baseline,
# predictions, risk-history, live tracking, active incident, environment).
#
# Versioned + timestamped envelope so future schema evolution is non-breaking
# and stale WebSocket patches can be rejected client-side.
#
# Phase 2 (WS-only consolidation) and Phase 5 (structured COMMAND_CENTER_DELTA
# envelopes) will broadcast incremental patches against this exact shape.

import logging
import uuid as uuid_mod
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select, and_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.roles import require_role
from app.models.user import User
from app.models.guardian import GuardianSession
from app.models.safety_event import SafetyEvent
from app.models.guardian_ai_v2 import (
    GuardianBaseline,
    GuardianRiskScore,
    GuardianPrediction,
    GuardianRiskEvent,
)
from app.services.guardian_ai_refinement import (
    get_or_create_baseline,
    compute_risk_score,
    generate_predictions,
    get_risk_history,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operator/command-center", tags=["Command Center"])

# Separate router for sibling endpoints under /operator (not nested in
# /command-center) — keeps `/cc-delta/metrics` clean and avoids collision
# with the catch-all `/command-center/{user_id}` route.
operator_extra_router = APIRouter(prefix="/operator", tags=["Command Center"])

# Bump on any breaking shape change.
PAYLOAD_VERSION = "v1"


# ── Phase 6: Fleet Weather Grid ───────────────────────────────────────
# IMPORTANT: this MUST be declared BEFORE the catch-all `/{user_id}`
# route so FastAPI matches the literal path first.
@router.get("/fleet-weather")
async def get_fleet_weather(
    city: str = "bengaluru",
    _operator: User = Depends(require_role("admin", "operator")),
):
    """
    Return the latest cached fleet weather grid (3×3 cells over Bengaluru).
    Refreshed every 5 minutes by the fleet weather scheduler.
    """
    from app.services.fleet_weather_service import get_grid, run_grid_refresh_cycle

    grid = get_grid(city)
    if not grid:
        # Cold start — compute on demand so the first ever caller still sees data.
        try:
            grid = await run_grid_refresh_cycle(city)
        except Exception:
            logger.exception("[FLEET_WX] cold-start refresh failed")
            return {
                "city": city,
                "cells": [],
                "version": "v1",
                "source": "unavailable",
                "error": "scheduler_not_warm",
            }
    return grid


# ── Phase 6: Delta Emitter Metrics ────────────────────────────────────
@operator_extra_router.get("/cc-delta/metrics")
async def get_cc_delta_metrics(
    _operator: User = Depends(require_role("admin", "operator")),
):
    """
    Return cumulative + rolling 1-min delta emitter counters. Useful for
    operators to confirm the system is processing deltas under load and
    to drive demo dashboards.
    """
    from app.services.cc_delta_emitter import get_metrics_snapshot
    return get_metrics_snapshot()


@router.get("/{user_id}")
async def get_command_center_user(
    user_id: str = Path(..., description="User UUID"),
    fresh: bool = False,
    _operator: User = Depends(require_role("admin", "operator")),
):
    """
    Unified per-user Command Center payload.

    Performance contract (locked June 2026 — was p95=66.87s, target <2s):
      * Each of the ~9 sections runs on its OWN async session, so the
        parallel `asyncio.gather` actually parallelizes instead of
        serializing on a single connection.
      * Two-stage pipeline: stage 1 fires the 8 independent fetches in
        parallel; stage 2 builds digital_twin + weather which need the
        stage-1 results.
      * Result is Redis-cached for 10s per user (`cc:user:{uid}:v1`).
        Operators polling the same user every few seconds see ≤ 1 cold
        computation per 10s; everything else is a sub-50ms cache hit.
      * Any section that raises is *isolated* (matches the pre-refactor
        try/except per-section pattern) — the envelope still renders.

    Envelope:
        {
          "version": "v1",
          "timestamp": "...",
          "user_id": "<uuid>",
          "user": { ... },
          "risk": { ... },
          "baseline": { ... },
          "digital_twin": { ... },
          "predictions": [...],
          "risk_history": [...],
          "live_location": { ... } | null,
          "active_event": { ... } | null,
          "environment": { ... },
          "motion_telemetry": { ... }
        }
    """
    import asyncio
    from app.db.session import async_session as _async_session
    from app.services import redis_service

    # 1. Validate user_id format up-front (cheap, no DB hit)
    try:
        uid = uuid_mod.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    # ── Cache strategy: stale-while-revalidate ─────────────────
    # The cold-pass takes ~9s (dominated by compute_risk_score, a
    # separate optimization target). To meet the operator's p95<2s
    # SLA WITHOUT extending the freshness window, we:
    #   * Mark a payload as FRESH for 10s   (user's requested TTL)
    #   * Keep serving it as STALE for up to 60s, BUT fire a
    #     background refresh on every stale hit
    #   * Only fall through to a synchronous fetch when the cache is
    #     truly empty (cold start, evicted, key first-write)
    # Net effect: a 9s synchronous fetch happens at MOST once per
    # 60s per user, and only when no operator has polled in 60s.
    # During steady-state operator polling, every request is a
    # cache hit (~50ms backend).
    CACHE_NS = "command_center_user"
    CACHE_KEY = f"{user_id}:v1"
    FRESH_TTL_S = 10
    STALE_TTL_S = 60
    REFRESH_LOCK_TTL_S = 30  # prevents thundering-herd background refreshes

    def _age_seconds(payload: dict) -> float:
        try:
            ts = payload.get("timestamp")
            if not ts:
                return 999.0
            from datetime import datetime as _dt
            cached_at = _dt.fromisoformat(ts.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - cached_at).total_seconds()
        except Exception:
            return 999.0

    if not fresh:
        try:
            cached = redis_service.get_json(CACHE_NS, CACHE_KEY)
            if cached:
                age = _age_seconds(cached)
                if age < FRESH_TTL_S:
                    cached["_cache"] = {"hit": True, "age_s": round(age, 2), "state": "fresh"}
                    return cached
                # STALE but still serveable — kick a background refresh,
                # return immediately. The lock prevents N concurrent
                # operators from each spawning a refresh task.
                lock_key = f"{CACHE_KEY}:refreshing"
                got_lock = False
                try:
                    c = redis_service._get_client()
                    if c is not None:
                        got_lock = bool(c.set(
                            f"nischint:{CACHE_NS}:{lock_key}",
                            "1", nx=True, ex=REFRESH_LOCK_TTL_S,
                        ))
                except Exception:
                    pass
                if got_lock:
                    import asyncio as _asyncio
                    _asyncio.create_task(_refresh_command_center_user_cache(
                        uid, CACHE_NS, CACHE_KEY, FRESH_TTL_S, STALE_TTL_S,
                    ))
                cached["_cache"] = {"hit": True, "age_s": round(age, 2), "state": "stale-refreshing" if got_lock else "stale"}
                return cached
        except Exception as e:
            logger.debug(f"[CC_UNIFIED] cache read failed: {e}")

    now = datetime.now(timezone.utc)
    payload = await _compute_command_center_user_payload(uid, now)
    # FRESH_TTL_S is logical; we keep the Redis key alive for STALE_TTL_S
    # so the SWR window can serve it.
    try:
        redis_service.set_json(CACHE_NS, CACHE_KEY, payload, ttl=STALE_TTL_S)
    except Exception as e:
        logger.debug(f"[CC_UNIFIED] cache write failed: {e}")
    payload["_cache"] = {"hit": False, "age_s": 0.0, "state": "cold"}
    return payload


async def _refresh_command_center_user_cache(
    uid: uuid_mod.UUID,
    cache_ns: str,
    cache_key: str,
    fresh_ttl_s: int,
    stale_ttl_s: int,
) -> None:
    """Background refresh worker spawned on stale-cache hit.

    Recomputes the payload, writes it back to Redis, releases the
    refresh lock. Lives entirely outside the request lifecycle, so
    timing it doesn't matter — the operator already got their stale
    response in <100ms.
    """
    from app.services import redis_service
    try:
        now = datetime.now(timezone.utc)
        payload = await _compute_command_center_user_payload(uid, now)
        redis_service.set_json(cache_ns, cache_key, payload, ttl=stale_ttl_s)
        logger.info(f"[CC_UNIFIED] background refresh complete for user={uid}")
    except Exception as e:
        logger.warning(f"[CC_UNIFIED] background refresh failed for user={uid}: {e}")
    finally:
        try:
            c = redis_service._get_client()
            if c is not None:
                c.delete(f"nischint:{cache_ns}:{cache_key}:refreshing")
        except Exception:
            pass


async def _compute_command_center_user_payload(
    uid: uuid_mod.UUID,
    now: datetime,
) -> dict:
    """The actual heavy computation — extracted so it can be invoked
    from the synchronous request path AND the background SWR refresh
    task with identical behaviour.

    Raises HTTPException(404) if the user does not exist; everything
    else is best-effort + degraded-section logged.
    """
    import asyncio
    from app.db.session import async_session as _async_session

    user_id = str(uid)

    # ── Stage 1: 8 independent fetches, each on its OWN session ──
    # All 8 must complete before we can build digital_twin + weather.

    async def _fetch_target_user():
        async with _async_session() as s:
            return (await s.execute(select(User).where(User.id == uid))).scalar_one_or_none()

    async def _fetch_risk():
        async with _async_session() as s:
            return await compute_risk_score(s, uid)

    async def _fetch_baseline():
        async with _async_session() as s:
            return await get_or_create_baseline(s, uid)

    async def _fetch_active_guardian_session():
        async with _async_session() as s:
            return (
                await s.execute(
                    select(GuardianSession)
                    .where(and_(
                        GuardianSession.user_id == uid,
                        GuardianSession.status == "active",
                    ))
                    .order_by(desc(GuardianSession.started_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def _fetch_predictions():
        async with _async_session() as s:
            return await generate_predictions(s, uid)

    async def _fetch_risk_history():
        async with _async_session() as s:
            return await get_risk_history(s, uid, limit=15)

    async def _fetch_active_event():
        async with _async_session() as s:
            return (
                await s.execute(
                    select(SafetyEvent)
                    .where(and_(
                        SafetyEvent.user_id == uid,
                        SafetyEvent.status == "active",
                    ))
                    .order_by(desc(SafetyEvent.created_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def _fetch_motion_telemetry():
        async with _async_session() as s:
            return await _build_motion_telemetry_view(s, uid, now)

    stage1 = await asyncio.gather(
        _fetch_target_user(),
        _fetch_risk(),
        _fetch_baseline(),
        _fetch_active_guardian_session(),
        _fetch_predictions(),
        _fetch_risk_history(),
        _fetch_active_event(),
        _fetch_motion_telemetry(),
        return_exceptions=True,
    )

    section_names = [
        "target_user", "risk", "baseline", "active_guardian_session",
        "predictions", "risk_history", "active_event", "motion_telemetry",
    ]
    defaults = {
        "target_user":             None,
        "risk":                    None,
        "baseline":                None,
        "active_guardian_session": None,
        "predictions":             [],
        "risk_history":            [],
        "active_event":            None,
        "motion_telemetry":        {"status": "unavailable", "reason": "fetch_error"},
    }
    failed_sections: list[str] = []
    res: dict = {}
    for name, value in zip(section_names, stage1):
        if isinstance(value, Exception):
            logger.warning(
                f"[CC_UNIFIED] section '{name}' failed for {user_id}: "
                f"{type(value).__name__}: {value}"
            )
            failed_sections.append(name)
            res[name] = defaults[name]
        else:
            res[name] = value

    target = res["target_user"]
    if not target:
        # Don't cache a 404 — user may be created shortly after.
        raise HTTPException(status_code=404, detail="User not found")

    # ── Stage 1.5: marshal live_location from active session ──
    live_location = None
    active_session = res["active_guardian_session"]
    if active_session and active_session.current_location:
        loc = active_session.current_location or {}
        lat = loc.get("lat") or loc.get("latitude")
        lng = loc.get("lng") or loc.get("longitude")
        if lat is not None and lng is not None:
            live_location = {
                "lat": float(lat),
                "lng": float(lng),
                "speed_mps": float(active_session.speed_mps or 0),
                "speed_kmh": round(float(active_session.speed_mps or 0) * 3.6, 1),
                "zone_name": active_session.zone_name,
                "risk_level": active_session.risk_level,
                "route_deviated": bool(active_session.route_deviated),
                "route_deviation_m": round(float(active_session.route_deviation_m or 0), 1),
                "is_idle": bool(active_session.is_idle),
                "idle_duration_s": float(active_session.idle_duration_s or 0),
                "session_id": str(active_session.id),
                "session_started_at": active_session.started_at.isoformat() if active_session.started_at else None,
                "ts": active_session.previous_update_at.isoformat() if active_session.previous_update_at else now.isoformat(),
            }

    # ── Marshal active_event ──
    active_event_row = res["active_event"]
    active_event = None
    if active_event_row:
        active_event = {
            "id": str(active_event_row.id),
            "primary_event": active_event_row.primary_event,
            "risk_score": float(active_event_row.risk_score),
            "risk_level": active_event_row.risk_level,
            "lat": float(active_event_row.location_lat),
            "lng": float(active_event_row.location_lng),
            "signals": active_event_row.signals or {},
            "created_at": active_event_row.created_at.isoformat() if active_event_row.created_at else None,
            "status": active_event_row.status,
        }

    # ── Stage 2: digital_twin + weather (both depend on stage 1) ──
    # Digital twin is pure CPU — no need to put it in gather. Weather
    # is an external HTTP call (OpenWeatherMap) — fire it concurrently
    # with the digital_twin compute to save the round-trip.
    async def _fetch_weather():
        if not (live_location and live_location.get("lat") is not None and live_location.get("lng") is not None):
            return None
        try:
            from app.services.weather_service import get_weather
            return await get_weather(float(live_location["lat"]), float(live_location["lng"]))
        except Exception as e:
            logger.warning(f"[CC_UNIFIED] weather fetch failed for {user_id}: {e}")
            return None

    weather_task = asyncio.create_task(_fetch_weather())
    digital_twin = _build_digital_twin_view(res["baseline"], res["risk"], now, live_location=live_location)
    weather = await weather_task

    environment = _build_environment_view(now, weather=weather)

    # ── Final envelope ──
    return {
        "version": PAYLOAD_VERSION,
        "timestamp": now.isoformat(),
        "user_id": str(uid),
        "user": {
            "id": str(target.id),
            "full_name": target.full_name,
            "email": target.email,
            "role": target.role,
            "phone": target.phone if hasattr(target, "phone") else None,
        },
        "risk": res["risk"],
        "baseline": res["baseline"],
        "digital_twin": digital_twin,
        "predictions": res["predictions"],
        "risk_history": res["risk_history"],
        "live_location": live_location,
        "active_event": active_event,
        "environment": environment,
        "motion_telemetry": res["motion_telemetry"],
        "_degraded_sections": failed_sections,
    }


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _build_digital_twin_view(baseline: dict | None, risk: dict | None, now: datetime, live_location: dict | None = None) -> dict:
    """
    Project the behavior baseline into the Digital Twin shape the frontend
    `DigitalTwinPanel` consumes. The `live_deviation` slot is now driven by
    the Phase 3 live-deviation engine, fed live signals from the active
    GuardianSession when available.
    """
    if not baseline:
        return {
            "status": "no_data",
            "confidence": 0.0,
            "live_deviation": {
                "status": "unknown", "score": 0.0, "confidence": 0.0,
                "reason": None, "factors": [], "computed_at": now.isoformat(),
            },
        }

    active_hours = baseline.get("active_hours") or {}
    high_hours = sorted([
        int(h) for h, v in active_hours.items() if v in ("high", "moderate")
    ])
    wake_hour = high_hours[0] if high_hours else None
    sleep_hour = high_hours[-1] if high_hours else None

    common_locs = baseline.get("common_locations") or []
    routes = baseline.get("route_clusters") or []

    # ── Phase 3 live deviation ──
    from app.services.live_deviation_engine import compute_live_deviation
    if live_location:
        live_deviation = compute_live_deviation(
            baseline,
            lat=live_location.get("lat"),
            lng=live_location.get("lng"),
            now=now,
            route_deviated=bool(live_location.get("route_deviated")),
            route_deviation_m=float(live_location.get("route_deviation_m") or 0),
            is_idle=bool(live_location.get("is_idle")),
            idle_duration_s=float(live_location.get("idle_duration_s") or 0),
        )
    else:
        # No active session — use time-only deviation (no GPS / route signals)
        live_deviation = compute_live_deviation(baseline, now=now)

    return {
        "status": "ready" if baseline.get("data_days", 0) >= 1 else "warming_up",
        "confidence": float(baseline.get("confidence", 0.5)),
        "data_days": int(baseline.get("data_days", 0)),
        "wake_hour": wake_hour,
        "sleep_hour": sleep_hour,
        "common_locations_count": len(common_locs),
        "route_clusters_count": len(routes),
        "avg_daily_distance_m": float(baseline.get("avg_daily_distance", 0)),
        "live_deviation": live_deviation,
    }


def _build_environment_view(now: datetime, weather: dict | None = None) -> dict:
    """
    Time-of-day environmental context plus real weather (Phase 4).
    `weather` is the normalized payload from `weather_service.get_weather`.
    """
    hour = now.hour
    if 22 <= hour or hour <= 5:
        time_band = "night"
        time_band_risk = 0.5
    elif 20 <= hour <= 22:
        time_band = "evening"
        time_band_risk = 0.25
    elif 6 <= hour <= 9:
        time_band = "early_morning"
        time_band_risk = 0.1
    else:
        time_band = "day"
        time_band_risk = 0.0

    # Build the public weather block. When OpenWeather is unavailable
    # (missing key, network error), the block stays explicit so the UI can
    # render an honest empty state instead of fabricating numbers.
    weather_risk = 0.0
    weather_factors: list[str] = []
    if weather and weather.get("source") == "openweather":
        from app.services.weather_service import compute_weather_risk
        weather_risk, weather_factors = compute_weather_risk(weather)
        weather_view = {
            "source": "openweather",
            "condition": weather.get("condition"),
            "description": weather.get("description"),
            "icon": weather.get("icon"),
            "temp_c": weather.get("temp_c"),
            "feels_like_c": weather.get("feels_like_c"),
            "humidity_pct": weather.get("humidity_pct"),
            "visibility_m": weather.get("visibility_m"),
            "wind_kmh": weather.get("wind_kmh"),
            "rain_1h_mm": weather.get("rain_1h_mm"),
            "city_name": weather.get("city_name"),
            "risk_score": weather_risk,
            "risk_factors": weather_factors,
            "from_cache": bool(weather.get("from_cache")),
        }
    else:
        weather_view = {
            "source": "unavailable",
            "error": (weather or {}).get("error") if isinstance(weather, dict) else None,
            "note": "Weather provider not configured or temporarily unreachable.",
        }

    # Aggregate environment-level risk + interpretability impact band
    env_risk = round(max(time_band_risk, weather_risk), 3)
    if env_risk >= 0.5:
        impact = "high"
    elif env_risk >= 0.2:
        impact = "medium"
    else:
        impact = "low"

    return {
        "time_band": time_band,
        "time_band_risk": time_band_risk,
        "hour_utc": hour,
        "weather": weather_view,
        "risk": env_risk,
        "impact": impact,
    }



# ── NISCH-012 motion telemetry view (per-user) ───────────────────────
# Reuses the existing `motion_features` table — NO new endpoint, NO
# new write path. The view is observational only; the data it surfaces
# is exactly what the writer ingests (idempotency_key-deduped windows).
#
# Locked freshness bands (mirror the trust evaluator's bands):
#   * live      → freshness ≤ 60 s    (within one window)
#   * fresh     → freshness ≤ 300 s   (within one batch upload)
#   * recent    → freshness ≤ 1800 s  (within trust-tile MEDIUM band)
#   * stale     → freshness >  1800 s
#   * unavailable → no rows for this entity
#
# Activity class is the locked enum at the writer boundary
# (`stationary | walking | running | vehicle | anomalous`) — the UI
# can trust it without revalidating.

_MOTION_LIVE_S   = 60.0
_MOTION_FRESH_S  = 300.0
_MOTION_RECENT_S = 1800.0


def _motion_status_band(freshness_s: float | None) -> str:
    if freshness_s is None:
        return "unavailable"
    if freshness_s <= _MOTION_LIVE_S:
        return "live"
    if freshness_s <= _MOTION_FRESH_S:
        return "fresh"
    if freshness_s <= _MOTION_RECENT_S:
        return "recent"
    return "stale"


async def _build_motion_telemetry_view(
    session: AsyncSession,
    entity_id,
    now: datetime,
) -> dict:
    """Single SELECT — latest window + 24h activity distribution for the
    user. Best-effort: returns `{status: "unavailable"}` on any error
    so the per-user envelope never breaks on motion-layer hiccups."""
    since_24h = now - timedelta(hours=24)

    # Two cheap SELECTs combined into one round trip: the latest
    # window's activity_class + timestamp, plus a 24h FILTER rollup
    # for the per-class distribution. Both indexed on
    # (entity_id, window_started_at).
    row = (await session.execute(text("""
        SELECT
          (SELECT activity_class FROM motion_features
              WHERE entity_id = :eid
              ORDER BY window_started_at DESC LIMIT 1)                     AS latest_class,
          (SELECT window_started_at FROM motion_features
              WHERE entity_id = :eid
              ORDER BY window_started_at DESC LIMIT 1)                     AS latest_at,
          (SELECT telemetry_pipeline_version FROM motion_features
              WHERE entity_id = :eid
              ORDER BY window_started_at DESC LIMIT 1)                     AS pipeline_v,
          (SELECT COUNT(*) FROM motion_features
              WHERE entity_id = :eid
                AND window_started_at >= :since)::int                      AS n_24h,
          (SELECT COUNT(*) FROM motion_features
              WHERE entity_id = :eid AND activity_class = 'stationary'
                AND window_started_at >= :since)::int                      AS n_stat,
          (SELECT COUNT(*) FROM motion_features
              WHERE entity_id = :eid AND activity_class = 'walking'
                AND window_started_at >= :since)::int                      AS n_walk,
          (SELECT COUNT(*) FROM motion_features
              WHERE entity_id = :eid AND activity_class = 'running'
                AND window_started_at >= :since)::int                      AS n_run,
          (SELECT COUNT(*) FROM motion_features
              WHERE entity_id = :eid AND activity_class = 'vehicle'
                AND window_started_at >= :since)::int                      AS n_veh,
          (SELECT COUNT(*) FROM motion_features
              WHERE entity_id = :eid AND activity_class = 'anomalous'
                AND window_started_at >= :since)::int                      AS n_anom
    """), {"eid": str(entity_id), "since": since_24h})).first()

    if not row or row[0] is None:
        return {
            "status": "unavailable",
            "activity_class": None,
            "last_motion_at": None,
            "freshness_s": None,
            "activity_distribution_24h": None,
            "window_count_24h": 0,
            "telemetry_pipeline_version": None,
        }

    latest_at = row[1]
    if latest_at and latest_at.tzinfo is None:
        latest_at = latest_at.replace(tzinfo=timezone.utc)
    freshness_s = (
        (now - latest_at).total_seconds() if latest_at else None
    )
    status = _motion_status_band(freshness_s)

    return {
        "status": status,
        "activity_class": row[0],
        "last_motion_at": latest_at.isoformat() if latest_at else None,
        "freshness_s": (
            round(freshness_s, 1) if freshness_s is not None else None
        ),
        "window_count_24h": int(row[3] or 0),
        "activity_distribution_24h": {
            "stationary": int(row[4] or 0),
            "walking":    int(row[5] or 0),
            "running":    int(row[6] or 0),
            "vehicle":    int(row[7] or 0),
            "anomalous":  int(row[8] or 0),
        },
        "telemetry_pipeline_version": row[2],
    }
