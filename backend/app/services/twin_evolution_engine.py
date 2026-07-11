# Twin Evolution Timeline Engine
# Detects long-term behavioral changes by analyzing weekly telemetry snapshots.
#
# Tracks: movement frequency, active hours, inactivity, battery, signal, anomalies.
# Detects: mobility decline, health deterioration, sleep disruption, device degradation.
#
# Analysis window: up to 8 weeks of history.

import logging
from datetime import datetime, timezone, timedelta, date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Shift detection thresholds
SHIFT_THRESHOLDS = {
    "movement_frequency": {"decline_pct": -20, "label": "mobility decline"},
    "active_hours": {"decline_pct": -20, "label": "reduced activity"},
    "avg_inactivity_minutes": {"increase_pct": 30, "label": "growing inactivity"},
    "avg_battery": {"decline_pct": -15, "label": "battery degradation"},
    "avg_signal": {"decline_pct": -20, "label": "signal deterioration"},
    "anomaly_count": {"increase_pct": 50, "label": "anomaly escalation"},
}

METRIC_LABELS = {
    "movement_frequency": "Movement Freq (events/day)",
    "active_hours": "Active Hours/Day",
    "avg_inactivity_minutes": "Avg Inactivity (min)",
    "avg_battery": "Avg Battery %",
    "avg_signal": "Signal Strength (dBm)",
    "anomaly_count": "Anomalies/Week",
    "behavior_score": "Behavior Score",
    "heartbeat_count": "Heartbeats/Week",
}


async def get_twin_evolution(session: AsyncSession, device_id: str, weeks: int = 8) -> dict | None:
    """
    Generate or fetch weekly evolution timeline for a device.
    Returns weekly snapshots with trend analysis and shift detection.
    """
    # Verify device
    device = (await session.execute(text(
        "SELECT id, device_identifier FROM devices WHERE id = :did"
    ), {"did": device_id})).fetchone()
    if not device:
        return None

    # Check for existing snapshots
    existing = (await session.execute(text("""
        SELECT week_start, week_end, week_number, movement_frequency, active_hours,
               avg_inactivity_minutes, avg_battery, avg_signal, heartbeat_count,
               anomaly_count, behavior_score
        FROM twin_evolution_snapshots
        WHERE device_id = :did
        ORDER BY week_start
    """), {"did": device_id})).fetchall()

    now = datetime.now(timezone.utc)

    # Compute snapshots from telemetry if fewer than expected
    if len(existing) < 2:
        snapshots = await _compute_weekly_snapshots(session, device_id, weeks, now)
        if snapshots:
            await _persist_snapshots(session, device_id, snapshots)
            await session.commit()
    else:
        # Check if latest week needs refresh
        latest_week_start = existing[-1].week_start
        current_week_start = (now.date() - timedelta(days=now.weekday()))
        if latest_week_start < current_week_start:
            snapshots = await _compute_weekly_snapshots(session, device_id, weeks, now)
            if snapshots:
                await _persist_snapshots(session, device_id, snapshots)
                await session.commit()

    # Re-fetch (may have been updated)
    rows = (await session.execute(text("""
        SELECT week_start, week_end, week_number, movement_frequency, active_hours,
               avg_inactivity_minutes, avg_battery, avg_signal, heartbeat_count,
               anomaly_count, behavior_score
        FROM twin_evolution_snapshots
        WHERE device_id = :did
        ORDER BY week_start
    """), {"did": device_id})).fetchall()

    if not rows:
        return {
            "device_id": str(device_id),
            "device_identifier": device.device_identifier,
            "weeks_analyzed": 0,
            "snapshots": [],
            "trends": [],
            "shifts": [],
            "interpretation": "Insufficient data for evolution analysis. At least 1 week of telemetry required.",
        }

    # Build snapshots list
    snapshots_list = []
    for r in rows:
        snapshots_list.append({
            "week_start": r.week_start.isoformat(),
            "week_end": r.week_end.isoformat(),
            "week_number": r.week_number,
            "week_label": f"W{r.week_number}",
            "movement_frequency": round(r.movement_frequency, 1) if r.movement_frequency else 0,
            "active_hours": round(r.active_hours, 1) if r.active_hours else 0,
            "avg_inactivity_minutes": round(r.avg_inactivity_minutes, 1) if r.avg_inactivity_minutes else 0,
            "avg_battery": round(r.avg_battery, 1) if r.avg_battery else 0,
            "avg_signal": round(r.avg_signal, 1) if r.avg_signal else 0,
            "heartbeat_count": r.heartbeat_count or 0,
            "anomaly_count": r.anomaly_count or 0,
            "behavior_score": round(r.behavior_score, 2) if r.behavior_score else 0,
        })

    # Compute trends + shift detection
    trends = _compute_trends(snapshots_list)
    shifts = _detect_shifts(snapshots_list)
    interpretation = _generate_interpretation(shifts, snapshots_list)

    return {
        "device_id": str(device_id),
        "device_identifier": device.device_identifier,
        "weeks_analyzed": len(snapshots_list),
        "generated_at": now.isoformat(),
        "snapshots": snapshots_list,
        "trends": trends,
        "shifts": shifts,
        "interpretation": interpretation,
    }


async def _compute_weekly_snapshots(
    session: AsyncSession, device_id: str, weeks: int, now: datetime
) -> list[dict]:
    """Compute weekly metric snapshots from raw telemetry."""
    cutoff = now - timedelta(weeks=weeks)

    # Get daily telemetry aggregates
    daily_data = (await session.execute(text("""
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS heartbeat_count,
            COUNT(DISTINCT EXTRACT(HOUR FROM created_at)) AS active_hours,
            AVG((metric_value->>'battery_level')::float) AS avg_battery,
            AVG((metric_value->>'signal_strength')::float) AS avg_signal
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat'
          AND is_simulated = false AND created_at >= :cutoff
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
    """), {"did": device_id, "cutoff": cutoff})).fetchall()

    if not daily_data:
        return []

    # Get daily anomaly counts
    anomaly_data = (await session.execute(text("""
        SELECT DATE(created_at) AS day, COUNT(*) AS cnt
        FROM behavior_anomalies
        WHERE device_id = :did AND is_simulated = false AND created_at >= :cutoff
        GROUP BY DATE(created_at)
    """), {"did": device_id, "cutoff": cutoff})).fetchall()
    anomaly_by_day = {r.day: r.cnt for r in anomaly_data}

    # Get daily behavior baseline scores (avg movement)
    baseline_data = (await session.execute(text("""
        SELECT avg_movement, avg_interaction_rate
        FROM behavior_baselines
        WHERE device_id = :did
        ORDER BY hour_of_day
    """), {"did": device_id})).fetchall()

    avg_baseline_movement = (
        sum(float(b.avg_movement or 0) for b in baseline_data) / len(baseline_data)
        if baseline_data else 0
    )

    # Group by ISO week
    weekly_buckets = {}
    for d in daily_data:
        day = d.day
        # ISO week start (Monday)
        week_start = day - timedelta(days=day.weekday())
        week_end = week_start + timedelta(days=6)

        if week_start not in weekly_buckets:
            weekly_buckets[week_start] = {
                "week_start": week_start,
                "week_end": week_end,
                "days": [],
                "heartbeats": 0,
                "active_hours_sum": 0,
                "battery_sum": 0,
                "battery_count": 0,
                "signal_sum": 0,
                "signal_count": 0,
                "anomaly_count": 0,
            }

        bucket = weekly_buckets[week_start]
        bucket["days"].append(day)
        bucket["heartbeats"] += d.heartbeat_count
        bucket["active_hours_sum"] += d.active_hours
        if d.avg_battery is not None:
            bucket["battery_sum"] += float(d.avg_battery)
            bucket["battery_count"] += 1
        if d.avg_signal is not None:
            bucket["signal_sum"] += float(d.avg_signal)
            bucket["signal_count"] += 1
        bucket["anomaly_count"] += anomaly_by_day.get(day, 0)

    # Convert buckets to snapshots
    snapshots = []
    sorted_weeks = sorted(weekly_buckets.keys())

    for i, ws in enumerate(sorted_weeks):
        b = weekly_buckets[ws]
        n_days = max(len(b["days"]), 1)

        movement_freq = b["heartbeats"] / n_days  # heartbeats per day as movement proxy
        active_hours = b["active_hours_sum"] / n_days
        avg_battery = b["battery_sum"] / b["battery_count"] if b["battery_count"] else 0
        avg_signal = b["signal_sum"] / b["signal_count"] if b["signal_count"] else 0

        # Inactivity: estimate from inverse of heartbeat frequency
        # Higher heartbeat = lower inactivity
        avg_inactivity = max(0, (24 * 60) / max(b["heartbeats"] / n_days, 1) - 10)

        # Behavior score: composite of movement and activity
        behavior_score = min(1.0, (movement_freq / max(avg_baseline_movement * 24, 1)) * 0.6 +
                            (active_hours / 16) * 0.4)

        snapshots.append({
            "week_start": b["week_start"],
            "week_end": b["week_end"],
            "week_number": i + 1,
            "movement_frequency": round(movement_freq, 1),
            "active_hours": round(active_hours, 1),
            "avg_inactivity_minutes": round(avg_inactivity, 1),
            "avg_battery": round(avg_battery, 1),
            "avg_signal": round(avg_signal, 1),
            "heartbeat_count": b["heartbeats"],
            "anomaly_count": b["anomaly_count"],
            "behavior_score": round(behavior_score, 3),
        })

    return snapshots


async def _persist_snapshots(session: AsyncSession, device_id: str, snapshots: list[dict]):
    """Upsert weekly snapshots into the DB."""
    for s in snapshots:
        await session.execute(text("""
            INSERT INTO twin_evolution_snapshots
            (device_id, week_start, week_end, week_number, movement_frequency,
             active_hours, avg_inactivity_minutes, avg_battery, avg_signal,
             heartbeat_count, anomaly_count, behavior_score)
            VALUES (:did, :ws, :we, :wn, :mf, :ah, :ai, :ab, :as_, :hc, :ac, :bs)
            ON CONFLICT (device_id, week_start) DO UPDATE SET
                movement_frequency = EXCLUDED.movement_frequency,
                active_hours = EXCLUDED.active_hours,
                avg_inactivity_minutes = EXCLUDED.avg_inactivity_minutes,
                avg_battery = EXCLUDED.avg_battery,
                avg_signal = EXCLUDED.avg_signal,
                heartbeat_count = EXCLUDED.heartbeat_count,
                anomaly_count = EXCLUDED.anomaly_count,
                behavior_score = EXCLUDED.behavior_score,
                created_at = NOW()
        """), {
            "did": device_id,
            "ws": s["week_start"],
            "we": s["week_end"],
            "wn": s["week_number"],
            "mf": s["movement_frequency"],
            "ah": s["active_hours"],
            "ai": s["avg_inactivity_minutes"],
            "ab": s["avg_battery"],
            "as_": s["avg_signal"],
            "hc": s["heartbeat_count"],
            "ac": s["anomaly_count"],
            "bs": s["behavior_score"],
        })


def _compute_trends(snapshots: list[dict]) -> list[dict]:
    """Compute per-metric trend direction and magnitude over the full window."""
    if len(snapshots) < 2:
        return []

    metrics = ["movement_frequency", "active_hours", "avg_inactivity_minutes",
               "avg_battery", "avg_signal", "anomaly_count"]
    trends = []

    for metric in metrics:
        values = [s[metric] for s in snapshots if s[metric] is not None]
        if len(values) < 2:
            continue

        first_half = sum(values[:len(values)//2]) / max(len(values)//2, 1)
        second_half = sum(values[len(values)//2:]) / max(len(values) - len(values)//2, 1)

        if first_half == 0:
            change_pct = 0
        else:
            change_pct = ((second_half - first_half) / abs(first_half)) * 100

        direction = "increasing" if change_pct > 5 else "decreasing" if change_pct < -5 else "stable"

        trends.append({
            "metric": metric,
            "label": METRIC_LABELS.get(metric, metric),
            "direction": direction,
            "change_percent": round(change_pct, 1),
            "first_value": round(values[0], 1),
            "latest_value": round(values[-1], 1),
        })

    return trends


def _detect_shifts(snapshots: list[dict]) -> list[dict]:
    """Detect significant behavioral shifts between consecutive weeks."""
    if len(snapshots) < 2:
        return []

    shifts = []

    for metric, config in SHIFT_THRESHOLDS.items():
        values = [s.get(metric, 0) for s in snapshots]

        # Check overall shift (first vs last)
        if len(values) >= 2 and values[0] != 0:
            overall_change = ((values[-1] - values[0]) / abs(values[0])) * 100
        else:
            overall_change = 0

        # For "decline" metrics (movement, battery, signal, active_hours)
        if "decline_pct" in config and overall_change <= config["decline_pct"]:
            shifts.append({
                "metric": metric,
                "label": METRIC_LABELS.get(metric, metric),
                "type": "decline",
                "interpretation": config["label"],
                "change_percent": round(overall_change, 1),
                "from_value": round(values[0], 1),
                "to_value": round(values[-1], 1),
                "severity": "high" if abs(overall_change) > 40 else "medium",
                "week_detected": snapshots[-1].get("week_label", ""),
            })

        # For "increase" metrics (inactivity, anomalies)
        if "increase_pct" in config and overall_change >= config["increase_pct"]:
            shifts.append({
                "metric": metric,
                "label": METRIC_LABELS.get(metric, metric),
                "type": "increase",
                "interpretation": config["label"],
                "change_percent": round(overall_change, 1),
                "from_value": round(values[0], 1),
                "to_value": round(values[-1], 1),
                "severity": "high" if overall_change > 80 else "medium",
                "week_detected": snapshots[-1].get("week_label", ""),
            })

    # Sort by severity (high first)
    shifts.sort(key=lambda s: 0 if s["severity"] == "high" else 1)
    return shifts


def _generate_interpretation(shifts: list[dict], snapshots: list[dict]) -> str:
    """Generate a human-readable interpretation summary."""
    if not snapshots:
        return "Insufficient data for evolution analysis."

    if len(snapshots) < 2:
        return f"Only {len(snapshots)} week of data available. Need at least 2 weeks for trend analysis."

    if not shifts:
        return f"No significant behavioral shifts detected over {len(snapshots)} weeks. Patterns remain stable."

    high_shifts = [s for s in shifts if s["severity"] == "high"]
    medium_shifts = [s for s in shifts if s["severity"] == "medium"]

    parts = []
    if high_shifts:
        labels = ", ".join(s["interpretation"] for s in high_shifts)
        parts.append(f"Significant changes detected: {labels}.")

    if medium_shifts:
        labels = ", ".join(s["interpretation"] for s in medium_shifts)
        parts.append(f"Moderate shifts: {labels}.")

    parts.append(f"Analysis covers {len(snapshots)} weeks of behavioral data.")
    return " ".join(parts)
