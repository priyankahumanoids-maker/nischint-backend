# Dry-run rule simulation — mirrors scheduler detection queries without mutations
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_MATCHED = 25


async def simulate_low_battery(session: AsyncSession, threshold_json: dict) -> list[dict]:
    t = threshold_json
    battery_percent = t["battery_percent"]
    sustain_minutes = t["sustain_minutes"]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=sustain_minutes)

    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT t.device_id,
                   (ARRAY_AGG((t.metric_value->>'battery_level')::float ORDER BY t.created_at DESC))[1] AS latest,
                   MIN((t.metric_value->>'battery_level')::float) AS min_val,
                   COUNT(*) AS cnt
            FROM telemetries t
            WHERE t.metric_type = 'heartbeat' AND t.created_at >= :cutoff
              AND (t.metric_value->>'battery_level') IS NOT NULL
            GROUP BY t.device_id
        )
        SELECT d.device_identifier, s.full_name AS senior_name, u.full_name AS guardian_name
        FROM recent r
        JOIN devices d ON d.id = r.device_id
        JOIN seniors s ON s.id = d.senior_id
        LEFT JOIN users u ON u.id = s.guardian_id
        WHERE r.latest < :threshold AND r.min_val < :threshold AND r.cnt >= 2
        LIMIT :lim
    """), {"cutoff": cutoff, "threshold": battery_percent, "lim": MAX_MATCHED})).fetchall()

    return [{"device_identifier": r.device_identifier, "senior_name": r.senior_name, "guardian_name": r.guardian_name} for r in rows]


async def simulate_signal_degradation(session: AsyncSession, threshold_json: dict) -> list[dict]:
    t = threshold_json
    signal_threshold = t["signal_threshold"]
    sustain_minutes = t["sustain_minutes"]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=sustain_minutes)

    rows = (await session.execute(text("""
        WITH recent AS (
            SELECT t.device_id,
                   (ARRAY_AGG((t.metric_value->>'signal_strength')::float ORDER BY t.created_at DESC))[1] AS latest,
                   MAX((t.metric_value->>'signal_strength')::float) AS max_val,
                   COUNT(*) AS cnt
            FROM telemetries t
            WHERE t.metric_type = 'heartbeat' AND t.created_at >= :cutoff
              AND (t.metric_value->>'signal_strength') IS NOT NULL
            GROUP BY t.device_id
        )
        SELECT d.device_identifier, s.full_name AS senior_name, u.full_name AS guardian_name
        FROM recent r
        JOIN devices d ON d.id = r.device_id
        JOIN seniors s ON s.id = d.senior_id
        LEFT JOIN users u ON u.id = s.guardian_id
        WHERE r.latest < :threshold AND r.max_val < :threshold AND r.cnt >= 2
        LIMIT :lim
    """), {"cutoff": cutoff, "threshold": signal_threshold, "lim": MAX_MATCHED})).fetchall()

    return [{"device_identifier": r.device_identifier, "senior_name": r.senior_name, "guardian_name": r.guardian_name} for r in rows]


async def simulate_reboot_anomaly(session: AsyncSession, threshold_json: dict) -> list[dict]:
    t = threshold_json
    gap_minutes = t["gap_minutes"]
    gap_count = t["gap_count"]
    window_minutes = t["window_minutes"]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    rows = (await session.execute(text("""
        WITH heartbeats AS (
            SELECT t.device_id, t.created_at,
                   LAG(t.created_at) OVER (PARTITION BY t.device_id ORDER BY t.created_at) AS prev_ts
            FROM telemetries t
            WHERE t.metric_type = 'heartbeat' AND t.created_at >= :cutoff
        ),
        gaps AS (
            SELECT device_id, COUNT(*) AS reboot_count
            FROM heartbeats
            WHERE prev_ts IS NOT NULL
              AND EXTRACT(EPOCH FROM (created_at - prev_ts)) > :gap_seconds
            GROUP BY device_id
        )
        SELECT d.device_identifier, s.full_name AS senior_name, u.full_name AS guardian_name
        FROM gaps g
        JOIN devices d ON d.id = g.device_id
        JOIN seniors s ON s.id = d.senior_id
        LEFT JOIN users u ON u.id = s.guardian_id
        WHERE g.reboot_count >= :max_reboots
        LIMIT :lim
    """), {"cutoff": cutoff, "max_reboots": gap_count, "gap_seconds": gap_minutes * 60, "lim": MAX_MATCHED})).fetchall()

    return [{"device_identifier": r.device_identifier, "senior_name": r.senior_name, "guardian_name": r.guardian_name} for r in rows]


SIMULATORS = {
    "low_battery": simulate_low_battery,
    "signal_degradation": simulate_signal_degradation,
    "reboot_anomaly": simulate_reboot_anomaly,
}

EVALUATION_WINDOWS = {
    "low_battery": lambda t: t.get("sustain_minutes", 10),
    "signal_degradation": lambda t: t.get("sustain_minutes", 10),
    "reboot_anomaly": lambda t: t.get("window_minutes", 60),
}
