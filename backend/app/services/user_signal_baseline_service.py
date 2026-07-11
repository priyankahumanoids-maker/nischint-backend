"""SB-02 — `user_signal_baselines` materialised-view service.

Owns four things and only four things:
  1. Refresh — `REFRESH MATERIALIZED VIEW CONCURRENTLY` plus
     metadata persistence to `user_signal_baselines_meta`.
  2. Read helpers — `get_user_baseline()` (single hour) and
     `get_user_baselines_24h()` (full profile) — both keyed by
     user_id, both serving from the matview.
  3. Refresh status read — for the operator UI / `/api/admin/baselines/status`.
  4. A pure-function status classifier so the scheduler can flag
     stale matviews (≥ 36 h since last refresh = stale).

Why a service module (not inline SQL in the API):
  * The refresh path needs to be callable from BOTH the scheduler
    (nightly) and the admin endpoint (on-demand). Centralising
    here avoids drift between the two call sites.
  * The metadata recording contract is locked in unit tests —
    keeping the SQL in a function lets us patch the session at
    a single seam.

Failure contract:
  * Refresh failure → record `last_status='failure'` + the error,
    do NOT raise into the scheduler. Operator UI sees the failure;
    the scheduler keeps ticking.
  * Read helpers MAY fall through to the legacy join when the
    matview is missing (e.g. migration not run on a fresh dev DB).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Staleness threshold — anything older than this is `stale` on the
# operator dashboard. 36 h gives one nightly refresh window of slack
# (a 24 h refresh that runs ~25 min late shouldn't read as stale).
STALENESS_THRESHOLD_S = 36 * 3600

# `REFRESH MATERIALIZED VIEW CONCURRENTLY` requires a unique index
# (created by the migration). When CONCURRENTLY isn't available
# (fresh dev DB before the unique index exists), we fall back to a
# blocking refresh that still works — at the cost of read locks
# during the refresh window.
_REFRESH_SQL_CONCURRENT = (
    "REFRESH MATERIALIZED VIEW CONCURRENTLY user_signal_baselines"
)
_REFRESH_SQL_BLOCKING = (
    "REFRESH MATERIALIZED VIEW user_signal_baselines"
)


# ── Refresh path ───────────────────────────────────────────────────


async def refresh_user_signal_baselines(
    session: AsyncSession,
    *,
    use_concurrent: bool = True,
) -> dict[str, Any]:
    """Refresh the matview and record metadata. NEVER raises.

    Returns a dict shaped for the operator UI:
        {
          "status":              "success" | "failure",
          "duration_ms":         float,
          "rows":                int  (post-refresh row count),
          "error":               Optional[str],
          "refreshed_at":        ISO8601 str,
          "mode":                "concurrent" | "blocking",
        }
    """
    sql = _REFRESH_SQL_CONCURRENT if use_concurrent else _REFRESH_SQL_BLOCKING
    mode = "concurrent" if use_concurrent else "blocking"
    t0 = time.monotonic()
    error: Optional[str] = None
    rows: int = 0
    status = "success"

    try:
        await session.execute(text(sql))
        # Row count is informational — used by the operator UI to
        # detect "the matview suddenly has way fewer rows" which
        # usually signals an upstream `behavior_baselines` issue
        # (e.g. mass device deletion) rather than a matview problem.
        row_result = await session.execute(
            text("SELECT COUNT(*) FROM user_signal_baselines")
        )
        rows = int(row_result.scalar() or 0)
        await session.commit()
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        error = repr(e)[:500]
        status = "failure"
        logger.warning(
            "[SB-02] matview refresh failed (mode=%s): %r", mode, e,
        )

    duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
    refreshed_at_utc = datetime.now(timezone.utc)

    # Best-effort metadata write — a failed metadata write must NOT
    # mask the underlying refresh result. We swallow + log.
    try:
        await session.execute(
            text("""
                UPDATE user_signal_baselines_meta
                   SET last_refreshed_at        = :ts,
                       last_refresh_duration_ms = :dur,
                       last_refresh_rows        = :rows,
                       last_status              = :status,
                       last_error               = :err
                 WHERE id = 1
            """),
            {
                "ts": refreshed_at_utc,
                "dur": duration_ms,
                "rows": rows,
                "status": status,
                "err": error,
            },
        )
        await session.commit()
    except Exception as e:  # noqa: BLE001
        await session.rollback()
        logger.warning("[SB-02] meta write failed (ignored): %r", e)

    if status == "success":
        logger.info(
            "[SB-02] matview refreshed mode=%s duration_ms=%.0f rows=%d",
            mode, duration_ms, rows,
        )

    # SB-02 → System Health Capsule wiring. Fire `system_health_delta`
    # on state transitions only (the threshold engine's golden rule).
    # `last_refreshed_at` is `refreshed_at_utc` on success — the
    # classifier interprets a `failure` status as `degraded` even
    # though we technically did just touch the timestamp.
    try:
        from app.services.health_thresholds import evaluate_baselines_state
        evaluate_baselines_state(
            last_status=status,
            last_refreshed_at=refreshed_at_utc if status == "success" else None,
            extra={
                "duration_ms": duration_ms,
                "rows":        rows,
                "mode":        mode,
                "error":       error,
            },
        )
    except Exception as e:  # pragma: no cover — telemetry must never raise
        logger.warning("[SB-02] health-delta evaluation failed (ignored): %r", e)

    return {
        "status":       status,
        "duration_ms":  duration_ms,
        "rows":         rows,
        "error":        error,
        "refreshed_at": refreshed_at_utc.isoformat(),
        "mode":         mode,
    }


# ── Read helpers ───────────────────────────────────────────────────


async def get_user_baseline(
    session: AsyncSession,
    user_id: str,
    hour_of_day: int,
) -> list[dict[str, Any]]:
    """Return baseline rows for one user @ one hour, one row per
    device. Empty list when nothing matches (user has no devices,
    no baseline yet, etc.)."""
    if not (0 <= hour_of_day <= 23):
        return []
    rows = (await session.execute(
        text("""
            SELECT device_id, device_identifier, device_type, device_status,
                   hour_of_day,
                   avg_movement, std_movement,
                   avg_location_switch, std_location_switch,
                   avg_interaction_rate, std_interaction_rate,
                   sample_count, baseline_updated_at
              FROM user_signal_baselines
             WHERE user_id = :uid AND hour_of_day = :hr
        """),
        {"uid": user_id, "hr": int(hour_of_day)},
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_user_baselines_24h(
    session: AsyncSession,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return the full 24-hour profile for one user across all
    devices. Sorted by (device_id, hour_of_day) so callers can
    group by device without an extra sort."""
    rows = (await session.execute(
        text("""
            SELECT device_id, device_identifier, device_type, device_status,
                   hour_of_day,
                   avg_movement, std_movement,
                   avg_location_switch, std_location_switch,
                   avg_interaction_rate, std_interaction_rate,
                   sample_count, baseline_updated_at
              FROM user_signal_baselines
             WHERE user_id = :uid
             ORDER BY device_id, hour_of_day
        """),
        {"uid": user_id},
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Device-grain reads ────────────────────────────────────────────
#
# Same matview, different access path. The operator console's
# "behavior pattern for device X" endpoint reads device-grain, not
# user-grain — and the matview's `(device_id)` index makes this a
# trivial point lookup. Splitting the helper API by grain keeps
# every call site explicit about what it's actually asking for.


async def get_device_baseline(
    session: AsyncSession,
    device_id: str,
    hour_of_day: int,
) -> Optional[dict[str, Any]]:
    """Return the single-hour baseline row for one device, or None.

    Defensive on out-of-range hour (short-circuits without SQL).
    The matview's UNIQUE (user_id, device_id, hour_of_day) index
    guarantees this is a point lookup."""
    if not (0 <= hour_of_day <= 23):
        return None
    row = (await session.execute(
        text("""
            SELECT device_id, device_identifier, device_type, device_status,
                   hour_of_day,
                   avg_movement, std_movement,
                   avg_location_switch, std_location_switch,
                   avg_interaction_rate, std_interaction_rate,
                   sample_count, baseline_updated_at
              FROM user_signal_baselines
             WHERE device_id = :did AND hour_of_day = :hr
             LIMIT 1
        """),
        {"did": device_id, "hr": int(hour_of_day)},
    )).fetchone()
    return _row_to_dict(row) if row is not None else None


async def get_device_baselines_24h(
    session: AsyncSession,
    device_id: str,
) -> list[dict[str, Any]]:
    """Full 24-hour profile for ONE device. Sorted by hour_of_day so
    callers can index into the result directly."""
    rows = (await session.execute(
        text("""
            SELECT device_id, device_identifier, device_type, device_status,
                   hour_of_day,
                   avg_movement, std_movement,
                   avg_location_switch, std_location_switch,
                   avg_interaction_rate, std_interaction_rate,
                   sample_count, baseline_updated_at
              FROM user_signal_baselines
             WHERE device_id = :did
             ORDER BY hour_of_day
        """),
        {"did": device_id},
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: Any) -> dict[str, Any]:
    """Normalise a matview row into the JSON-friendly shape the
    operator UI expects. Centralised so any future column tweak
    only touches one place."""
    updated = r.baseline_updated_at
    if isinstance(updated, datetime):
        updated_iso = updated.astimezone(timezone.utc).isoformat()
    else:
        updated_iso = None
    return {
        "device_id":            str(r.device_id),
        "device_identifier":    r.device_identifier,
        "device_type":          r.device_type,
        "device_status":        r.device_status,
        "hour_of_day":          int(r.hour_of_day),
        "avg_movement":         round(float(r.avg_movement), 3),
        "std_movement":         round(float(r.std_movement), 3),
        "avg_location_switch": round(float(r.avg_location_switch), 3),
        "std_location_switch": round(float(r.std_location_switch), 3),
        "avg_interaction_rate": round(float(r.avg_interaction_rate), 1),
        "std_interaction_rate": round(float(r.std_interaction_rate), 1),
        "sample_count":         int(r.sample_count),
        "baseline_updated_at":  updated_iso,
    }


# ── Refresh status & freshness classifier ─────────────────────────


def classify_freshness(
    last_refreshed_at: Optional[datetime],
    now: Optional[datetime] = None,
    threshold_s: int = STALENESS_THRESHOLD_S,
) -> str:
    """Pure function — unit-tested. Returns one of:
      * `fresh`     — refreshed within the threshold window
      * `stale`     — last refresh older than threshold
      * `unknown`   — no refresh on record yet (cold start)
    """
    if last_refreshed_at is None:
        return "unknown"
    n = now or datetime.now(timezone.utc)
    last = last_refreshed_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_s = (n - last).total_seconds()
    if age_s < 0:           # clock skew defence
        return "fresh"
    return "fresh" if age_s <= threshold_s else "stale"


async def get_refresh_status(
    session: AsyncSession,
) -> dict[str, Any]:
    """Operator-UI view of matview health.

    Returns:
        {
          "last_refreshed_at":        ISO8601 | None,
          "last_refresh_duration_ms": float | None,
          "last_refresh_rows":        int | None,
          "last_status":              str,
          "last_error":               str | None,
          "freshness":                "fresh" | "stale" | "unknown",
          "threshold_s":              int,
        }
    """
    row = (await session.execute(
        text("""
            SELECT last_refreshed_at, last_refresh_duration_ms,
                   last_refresh_rows, last_status, last_error
              FROM user_signal_baselines_meta
             WHERE id = 1
        """),
    )).fetchone()
    if row is None:
        return {
            "last_refreshed_at":        None,
            "last_refresh_duration_ms": None,
            "last_refresh_rows":        None,
            "last_status":              "unknown",
            "last_error":               None,
            "freshness":                "unknown",
            "threshold_s":              STALENESS_THRESHOLD_S,
        }
    last_ts = row.last_refreshed_at
    return {
        "last_refreshed_at":        last_ts.isoformat() if isinstance(last_ts, datetime) else None,
        "last_refresh_duration_ms": (
            float(row.last_refresh_duration_ms)
            if row.last_refresh_duration_ms is not None else None
        ),
        "last_refresh_rows":        (
            int(row.last_refresh_rows)
            if row.last_refresh_rows is not None else None
        ),
        "last_status":              row.last_status or "unknown",
        "last_error":               row.last_error,
        "freshness":                classify_freshness(last_ts),
        "threshold_s":              STALENESS_THRESHOLD_S,
    }


__all__ = [
    "STALENESS_THRESHOLD_S",
    "refresh_user_signal_baselines",
    "get_user_baseline",
    "get_user_baselines_24h",
    "get_device_baseline",
    "get_device_baselines_24h",
    "get_refresh_status",
    "classify_freshness",
]
