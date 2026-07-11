# Device Health Aggregation Service
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_device_health(
    session: AsyncSession,
    device_id: UUID,
    window_hours: int = 24,
) -> dict:
    """Compute device health metrics for a single device over a rolling window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    expected_heartbeats = window_hours * 60

    row = (await session.execute(text("""
        WITH agg AS (
            SELECT COUNT(*) AS cnt,
                   AVG((metric_value->>'battery_level')::float) AS avg_bat,
                   MIN((metric_value->>'battery_level')::float) AS min_bat,
                   AVG((metric_value->>'signal_strength')::float) AS avg_sig
            FROM telemetries
            WHERE device_id = :did AND metric_type = 'heartbeat' AND created_at >= :cutoff
        ),
        latest AS (
            SELECT metric_value
            FROM telemetries
            WHERE device_id = :did AND metric_type = 'heartbeat' AND created_at >= :cutoff
            ORDER BY created_at DESC LIMIT 1
        ),
        offline AS (
            SELECT COUNT(*) AS offline_count
            FROM incidents
            WHERE device_id = :did AND incident_type = 'device_offline' AND created_at >= :cutoff
        )
        SELECT a.cnt, a.avg_bat, a.min_bat, a.avg_sig,
               (l.metric_value->>'battery_level')::float AS latest_bat,
               (l.metric_value->>'signal_strength')::float AS latest_sig,
               o.offline_count,
               d.device_identifier, d.status, d.last_seen
        FROM agg a
        LEFT JOIN latest l ON TRUE
        CROSS JOIN offline o
        CROSS JOIN devices d
        WHERE d.id = :did
    """), {"did": device_id, "cutoff": cutoff})).fetchone()

    if not row:
        return _empty_health(str(device_id), window_hours)

    uptime = round(min(row.cnt / expected_heartbeats * 100, 100), 1) if expected_heartbeats > 0 else 0
    score = _compute_reliability(uptime, row.latest_bat, row.avg_sig, row.offline_count)

    return {
        "device_id": str(device_id),
        "device_identifier": row.device_identifier,
        "status": row.status,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        "battery": {
            "latest": row.latest_bat,
            "average": round(row.avg_bat, 1) if row.avg_bat else None,
            "min": row.min_bat,
        },
        "signal": {
            "latest": row.latest_sig,
            "average": round(row.avg_sig, 1) if row.avg_sig else None,
        },
        "uptime_percent": uptime,
        "heartbeat_count": row.cnt,
        "offline_count": row.offline_count,
        "reliability_score": score,
        "window_hours": window_hours,
    }


async def get_devices_health_batch(
    session: AsyncSession,
    senior_id: UUID,
    window_hours: int = 24,
) -> list[dict]:
    """Compute device health for all devices under a senior in a single query."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    expected_heartbeats = window_hours * 60

    rows = (await session.execute(text("""
        SELECT
            d.id AS device_id,
            d.device_identifier,
            d.status,
            d.last_seen,
            COALESCE(hb.heartbeat_count, 0) AS heartbeat_count,
            hb.avg_battery,
            hb.min_battery,
            hb.avg_signal,
            hb.latest_battery,
            hb.latest_signal,
            COALESCE(oc.offline_count, 0) AS offline_count
        FROM devices d
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) AS heartbeat_count,
                AVG((t.metric_value->>'battery_level')::float) AS avg_battery,
                MIN((t.metric_value->>'battery_level')::float) AS min_battery,
                AVG((t.metric_value->>'signal_strength')::float) AS avg_signal,
                (ARRAY_AGG((t.metric_value->>'battery_level')::float ORDER BY t.created_at DESC))[1] AS latest_battery,
                (ARRAY_AGG((t.metric_value->>'signal_strength')::float ORDER BY t.created_at DESC))[1] AS latest_signal
            FROM telemetries t
            WHERE t.device_id = d.id
              AND t.metric_type = 'heartbeat'
              AND t.created_at >= :cutoff
        ) hb ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS offline_count
            FROM incidents i
            WHERE i.device_id = d.id
              AND i.incident_type = 'device_offline'
              AND i.created_at >= :cutoff
        ) oc ON TRUE
        WHERE d.senior_id = :sid
        ORDER BY d.created_at ASC
    """), {"sid": senior_id, "cutoff": cutoff})).fetchall()

    results = []
    for r in rows:
        uptime = round(min(r.heartbeat_count / expected_heartbeats * 100, 100), 1) if expected_heartbeats > 0 else 0
        score = _compute_reliability(uptime, r.latest_battery, r.avg_signal, r.offline_count)
        results.append({
            "device_id": str(r.device_id),
            "device_identifier": r.device_identifier,
            "status": r.status,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "battery": {
                "latest": r.latest_battery,
                "average": round(r.avg_battery, 1) if r.avg_battery else None,
                "min": r.min_battery,
            },
            "signal": {
                "latest": r.latest_signal,
                "average": round(r.avg_signal, 1) if r.avg_signal else None,
            },
            "uptime_percent": uptime,
            "heartbeat_count": r.heartbeat_count,
            "offline_count": r.offline_count,
            "reliability_score": score,
            "window_hours": window_hours,
        })
    return results


async def get_all_devices_health(
    session: AsyncSession,
    window_hours: int = 24,
) -> list[dict]:
    """Compute device health metrics across ALL devices (operator view). Single query."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    expected_heartbeats = window_hours * 60

    rows = (await session.execute(text("""
        SELECT
            d.id AS device_id,
            d.device_identifier,
            d.status,
            d.last_seen,
            s.full_name AS senior_name,
            COALESCE(u.full_name, u.email) AS guardian_name,
            COALESCE(hb.heartbeat_count, 0) AS heartbeat_count,
            hb.avg_battery,
            hb.min_battery,
            hb.avg_signal,
            hb.latest_battery,
            hb.latest_signal,
            COALESCE(oc.offline_count, 0) AS offline_count,
            dl.latitude,
            dl.longitude
        FROM devices d
        JOIN seniors s ON s.id = d.senior_id
        JOIN users u ON u.id = s.guardian_id
        LEFT JOIN device_locations dl ON dl.device_id = d.id
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) AS heartbeat_count,
                AVG((t.metric_value->>'battery_level')::float) AS avg_battery,
                MIN((t.metric_value->>'battery_level')::float) AS min_battery,
                AVG((t.metric_value->>'signal_strength')::float) AS avg_signal,
                (ARRAY_AGG((t.metric_value->>'battery_level')::float ORDER BY t.created_at DESC))[1] AS latest_battery,
                (ARRAY_AGG((t.metric_value->>'signal_strength')::float ORDER BY t.created_at DESC))[1] AS latest_signal
            FROM telemetries t
            WHERE t.device_id = d.id
              AND t.metric_type = 'heartbeat'
              AND t.created_at >= :cutoff
        ) hb ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS offline_count
            FROM incidents i
            WHERE i.device_id = d.id
              AND i.incident_type = 'device_offline'
              AND i.created_at >= :cutoff
        ) oc ON TRUE
        ORDER BY d.created_at ASC
    """), {"cutoff": cutoff})).fetchall()

    results = []
    for r in rows:
        uptime = round(min(r.heartbeat_count / expected_heartbeats * 100, 100), 1) if expected_heartbeats > 0 else 0
        score = _compute_reliability(uptime, r.latest_battery, r.avg_signal, r.offline_count)
        results.append({
            "device_id": str(r.device_id),
            "device_identifier": r.device_identifier,
            "status": r.status,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "senior_name": r.senior_name,
            "guardian_name": r.guardian_name,
            "battery_latest": r.latest_battery,
            "battery_avg": round(r.avg_battery, 1) if r.avg_battery else None,
            "signal_avg": round(r.avg_signal, 1) if r.avg_signal else None,
            "uptime_percent": uptime,
            "offline_count": r.offline_count,
            "reliability_score": score,
            "latitude": float(r.latitude) if r.latitude else None,
            "longitude": float(r.longitude) if r.longitude else None,
        })
    return results


def _compute_reliability(
    uptime_pct: float,
    battery_latest: int | None,
    signal_avg: float | None,
    offline_count: int,
) -> int:
    """
    Composite reliability score (0-100).
    40% uptime + 30% battery stability + 30% signal stability - offline penalty.
    """
    uptime_score = min(uptime_pct, 100)

    if battery_latest is not None:
        battery_score = min(max(battery_latest, 0), 100)
    else:
        battery_score = 50

    if signal_avg is not None:
        signal_score = max(0, min(100, (signal_avg + 90) / 60 * 100))
    else:
        signal_score = 50

    offline_penalty = min(offline_count * 5, 20)
    raw = (0.4 * uptime_score) + (0.3 * battery_score) + (0.3 * signal_score) - offline_penalty
    return max(0, min(100, round(raw)))


def _empty_health(device_id: str, window_hours: int) -> dict:
    return {
        "device_id": device_id,
        "device_identifier": None,
        "status": "unknown",
        "last_seen": None,
        "battery": {"latest": None, "average": None, "min": None},
        "signal": {"latest": None, "average": None},
        "uptime_percent": 0,
        "heartbeat_count": 0,
        "offline_count": 0,
        "reliability_score": 0,
        "window_hours": window_hours,
    }
