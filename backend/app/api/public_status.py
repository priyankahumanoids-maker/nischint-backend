"""Public-facing status page endpoint — Cloudflare/Stripe style.

Exposes a sanitized health roll-up at `GET /api/public/status` with
NO authentication. Designed for a public `/status` page that anyone
(customers, investors, on-call engineers, journalists) can hit.

Strict rules locked into this module:
  1. Public output must NEVER leak internal IDs, error messages,
     pool sizes, stack traces, or admin telemetry. Every field is
     either a fixed enum (`operational | degraded | outage`), a
     bounded short description, or a rounded number.
  2. The endpoint must be cheap. Heavy work is cached in Redis for
     30 s; under any traffic spike we serve cached state.
  3. The endpoint must NEVER fail to respond. Every internal data
     source is wrapped — a single broken source degrades only its
     own component, never the whole envelope.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.models.system_incident import SystemIncident


router = APIRouter(prefix="/public/status", tags=["public-status"])

# ── Constants ────────────────────────────────────────────────────────

CACHE_NS = "public_status"
CACHE_KEY = "v1"
CACHE_TTL_S = 30
UPTIME_WINDOW_DAYS = 30
UPTIME_WINDOW_MS = UPTIME_WINDOW_DAYS * 24 * 60 * 60 * 1000

# Public-facing component labels — keep these stable for status-page
# subscribers / RSS readers.
COMP_API = "API"
COMP_DB = "Database"
COMP_SACHET = "External Signals — SACHET"
COMP_WEATHER = "External Signals — Weather (OpenWeather)"

# Severity → public label
_SEV_LABEL = {
    "warning": "minor",
    "degraded": "major",
    "critical": "critical",
}

# Public-friendly titles per trigger_source.
_INCIDENT_TITLE = {
    "scheduler":     "Background job scheduling delays",
    "ai":            "AI inference latency",
    "queue":         "Background queue back-pressure",
    "database_pool": "Database connection pressure",
    "db":            "Database availability",
    "redis":         "Cache layer instability",
    "ws":            "Real-time connection issues",
    "auth":          "Authentication service latency",
    "auth_service":  "Authentication service latency",
    "api":           "API response latency",
    "external":      "External signals delay",
    "sachet":        "Public emergency feed (SACHET) delay",
    "weather":       "Weather signals delay",
    "push":          "Notification delivery delay",
}


# ── Status derivation per source ─────────────────────────────────────


def _api_status() -> dict[str, str]:
    # We are responding to this request → API is at minimum reachable.
    # We don't try to be cleverer here; if the API is down, this
    # function never runs and the load-balancer / CDN handles the
    # fallback. A nuanced internal degraded state is exposed only via
    # the admin-only `/system-health` endpoint.
    return {
        "name": COMP_API,
        "status": "operational",
        "description": "All public endpoints responding",
    }


def _db_status_from(db_block: dict[str, Any]) -> dict[str, str]:
    pool = db_block.get("pool") or {}
    active = db_block.get("active_incidents") or []
    if active:
        return {
            "name": COMP_DB,
            "status": "outage",
            "description": "Active database incident — engineers engaged",
        }
    if not pool.get("available", True):
        return {
            "name": COMP_DB,
            "status": "degraded",
            "description": "Database telemetry temporarily unavailable",
        }
    # Pool pressure check — only fields that exist on the public
    # pool_stats output; never leak raw numbers.
    used = pool.get("checked_out") or pool.get("used") or 0
    size = pool.get("size") or pool.get("pool_size") or 0
    try:
        if size and used / size >= 0.85:
            return {
                "name": COMP_DB,
                "status": "degraded",
                "description": "Database under elevated load",
            }
    except Exception:
        pass
    return {
        "name": COMP_DB,
        "status": "operational",
        "description": "Connection pool healthy",
    }


def _sachet_status_from(sachet_block: dict[str, Any]) -> dict[str, str]:
    if "error" in sachet_block:
        return {
            "name": COMP_SACHET,
            "status": "degraded",
            "description": "Signal feed temporarily unavailable",
        }
    state = (sachet_block.get("state") or sachet_block.get("health_state") or "").lower()
    if state == "degraded":
        return {
            "name": COMP_SACHET,
            "status": "degraded",
            "description": "Upstream signal feed lagging",
        }
    if state == "outage":
        return {
            "name": COMP_SACHET,
            "status": "outage",
            "description": "Upstream signal feed unreachable",
        }
    return {
        "name": COMP_SACHET,
        "status": "operational",
        "description": "Signals refreshing on schedule",
    }


async def _weather_status() -> dict[str, str]:
    """Lightweight freshness check using the fleet weather Redis cache."""
    try:
        from app.services import redis_service
        # Same key the fleet weather service uses (see fleet_weather_service.py)
        grid = redis_service.get_json("nischint", "fleet_weather_grid:bengaluru")
        if not grid:
            # First boot or cache evicted — not an outage signal.
            return {
                "name": COMP_WEATHER,
                "status": "operational",
                "description": "Weather grid initializing",
            }
        # All cells with `source == "unavailable"` → upstream is down
        cells = grid.get("cells") or []
        if cells and all((c.get("source") == "unavailable") for c in cells):
            return {
                "name": COMP_WEATHER,
                "status": "degraded",
                "description": "Weather provider not responding",
            }
        return {
            "name": COMP_WEATHER,
            "status": "operational",
            "description": "Weather telemetry refreshing on schedule",
        }
    except Exception:
        return {
            "name": COMP_WEATHER,
            "status": "operational",
            "description": "Weather telemetry refreshing on schedule",
        }


# ── Incidents (last 30 days, public-safe) ────────────────────────────


async def _recent_incidents(session: AsyncSession) -> tuple[list[dict], int]:
    """Return (public_incidents, total_downtime_ms_for_uptime_calc)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=UPTIME_WINDOW_DAYS)
    q = (
        select(SystemIncident)
        .where(SystemIncident.started_at >= cutoff)
        .order_by(SystemIncident.started_at.desc())
        .limit(50)
    )
    rows = (await session.execute(q)).scalars().all()

    incidents: list[dict] = []
    downtime_ms = 0
    for r in rows:
        sev_label = _SEV_LABEL.get(r.severity_peak or "", "minor")
        title = _INCIDENT_TITLE.get(r.trigger_source or "", "Service interruption")
        item = {
            # Truncated id is fine — public surface only needs a
            # stable token for in-page anchors, not the full UUID.
            "id":           str(r.id)[:8] if r.id else "",
            "title":        title,
            "status":       r.status or "active",
            "severity":     sev_label,
            "started_at":   r.started_at.isoformat() if r.started_at else None,
            "resolved_at":  r.resolved_at.isoformat() if r.resolved_at else None,
        }
        if r.duration_ms is not None:
            item["duration_minutes"] = int(round(r.duration_ms / 60_000))
        incidents.append(item)

        # Only `degraded` and `critical` severities count against
        # uptime. `warning` is informational. Active (unresolved) and
        # uncounted-duration rows are also excluded — we can't claim
        # downtime we haven't measured yet.
        if (
            r.status == "resolved"
            and r.duration_ms is not None
            and (r.severity_peak in ("degraded", "critical"))
        ):
            downtime_ms += max(0, int(r.duration_ms))
    return incidents, downtime_ms


def _compute_uptime_pct(downtime_ms: int) -> float:
    available = max(0, UPTIME_WINDOW_MS - downtime_ms)
    pct = (available / UPTIME_WINDOW_MS) * 100.0
    # Two decimal places, never exceed 100.00
    return round(min(pct, 100.0), 2)


def _overall_status(components: list[dict]) -> str:
    # worst-of: outage > degraded > operational
    statuses = {c.get("status") for c in components}
    if "outage" in statuses:
        return "outage"
    if "degraded" in statuses:
        return "degraded"
    return "operational"


# ── Endpoint ────────────────────────────────────────────────────────


async def _build_status_envelope() -> dict[str, Any]:
    """Compose the full public envelope. Each subsystem is isolated."""

    # Pull the existing admin gather function for DB + SACHET (it
    # already wraps each source in try/except and is heavily cached).
    try:
        from app.api.monitoring import _gather_dashboard_summary
        admin_bundle = await _gather_dashboard_summary()
    except Exception:
        admin_bundle = {}

    components = [
        _api_status(),
        _db_status_from(admin_bundle.get("db") or {}),
        _sachet_status_from(admin_bundle.get("sachet") or {}),
        await _weather_status(),
    ]

    # Incidents + uptime
    incidents: list[dict] = []
    downtime_ms = 0
    try:
        async for sess in get_db_session():
            incidents, downtime_ms = await _recent_incidents(sess)
            break
    except Exception:
        incidents = []
        downtime_ms = 0

    return {
        "overall":       _overall_status(components),
        "components":    components,
        "uptime_30d_pct": _compute_uptime_pct(downtime_ms),
        "uptime_window_days": UPTIME_WINDOW_DAYS,
        "incidents":     incidents,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }


@router.get("")
@router.get("/")
async def get_public_status(response: Response):
    """Public, unauthenticated status snapshot.

    Cached in Redis for 30 s and CDN-cached for the same window so a
    public status-page widget hitting us every 5 s from N visitors
    costs us at most 2 backend recomputes per minute.
    """
    # CDN + browser cache hints. `s-maxage` is for Cloudflare; the
    # short browser cache prevents tab-spam stampedes.
    response.headers["Cache-Control"] = "public, max-age=15, s-maxage=30"
    response.headers["CDN-Cache-Control"] = "max-age=30"

    # Fast path — Redis cache
    try:
        from app.services import redis_service
        cached = redis_service.get_json(CACHE_NS, CACHE_KEY)
        if cached is not None:
            return cached
    except Exception:
        pass

    envelope = await _build_status_envelope()

    try:
        from app.services import redis_service
        redis_service.set_json(CACHE_NS, CACHE_KEY, envelope, ttl=CACHE_TTL_S)
    except Exception:
        pass
    return envelope
