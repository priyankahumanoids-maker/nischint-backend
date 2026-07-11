# AI Life Pattern Engine
# Builds a 24-hour behavioral fingerprint from long-term telemetry.
#
# For each hour 0-23, computes probability of:
#   - sleep (inactivity)
#   - movement (activity level)
#   - interaction (device usage)
#   - location (movement between zones)
#   - anomaly (unusual behavior)
#
# Produces: hourly heatmap, behavioral fingerprint (wake/sleep/peak/rest),
# routine stability %, deviation detection, and AI insights.
# Caches results for 24h to avoid heavy recomputation.

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Fingerprint thresholds
WAKE_MOVEMENT_THRESHOLD = 0.5
SLEEP_PROBABILITY_THRESHOLD = 0.6
ACTIVE_THRESHOLD = 0.7
REST_THRESHOLD = 0.3

CACHE_TTL_HOURS = 24


async def build_life_pattern(session: AsyncSession, device_id: str, days: int = 30) -> dict | None:
    """
    Build a 24-hour life pattern profile for a device.
    Uses 24h cache — returns stored pattern if fresh enough.
    """
    device = (await session.execute(text(
        "SELECT id, device_identifier FROM devices WHERE id = :did"
    ), {"did": device_id})).fetchone()
    if not device:
        return None

    now = datetime.now(timezone.utc)

    # Check cache — if pattern was computed within TTL, return it
    cached = await _get_cached_pattern(session, device_id, now)
    if cached is not None:
        fingerprint = _build_fingerprint(cached)
        deviations = await _detect_deviations(session, device_id, cached, now)
        insights = _generate_insights(cached, fingerprint, deviations)
        days_observed = await _count_observed_days(session, device_id, now - timedelta(days=days))
        return _format_response(device, days_observed, days, now, cached, fingerprint, deviations, insights)

    cutoff = now - timedelta(days=days)

    # 1. Aggregate telemetry by hour
    hourly_telemetry = await _aggregate_hourly_telemetry(session, device_id, cutoff)

    # 2. Get behavior baselines (includes location_switch data)
    baselines = await _get_baselines(session, device_id)

    # 3. Get anomaly distribution by hour
    anomaly_dist = await _get_anomaly_distribution(session, device_id, cutoff)

    # 4. Count observed days
    days_observed = await _count_observed_days(session, device_id, cutoff)
    days_observed = max(days_observed, 1)

    # 5. Build hourly heatmap
    heatmap = []
    for hour in range(24):
        tel = hourly_telemetry.get(hour, {"count": 0})
        bl = baselines.get(hour, {})
        anom = anomaly_dist.get(hour, 0)

        event_count = tel.get("count", 0)
        movement_prob = min(1.0, event_count / max(days_observed, 1))

        # Enhance with baseline movement data
        baseline_mov = float(bl.get("avg_movement", 0))
        if baseline_mov > 0:
            baseline_prob = min(1.0, baseline_mov / 5.0)
            movement_prob = 0.5 * movement_prob + 0.5 * baseline_prob

        # Interaction probability
        baseline_interact = float(bl.get("avg_interaction_rate", 0))
        interaction_prob = min(1.0, baseline_interact / 3.0) if baseline_interact > 0 else movement_prob * 0.6

        # Location change probability (from baseline location_switch data)
        baseline_loc = float(bl.get("avg_location_switch", 0))
        location_prob = min(1.0, baseline_loc / 2.0) if baseline_loc > 0 else movement_prob * 0.4
        # Boost during typical commute/activity hours
        if 7 <= hour <= 10 or 15 <= hour <= 18:
            location_prob = min(1.0, location_prob * 1.3)

        # Sleep probability
        sleep_prob = max(0.0, 1.0 - movement_prob * 1.2)
        if hour >= 22 or hour <= 5:
            sleep_prob = max(sleep_prob, 0.5)
        if 0 <= hour <= 4:
            sleep_prob = max(sleep_prob, 0.7)

        # Anomaly probability
        anomaly_prob = min(1.0, anom / max(days_observed * 0.3, 1))

        avg_events = event_count / max(days_observed, 1)

        heatmap.append({
            "hour": hour,
            "sleep": round(sleep_prob, 3),
            "movement": round(movement_prob, 3),
            "interaction": round(interaction_prob, 3),
            "location": round(location_prob, 3),
            "anomaly": round(anomaly_prob, 3),
            "avg_events": round(avg_events, 2),
            "samples": event_count,
        })

    # 6. Build fingerprint
    fingerprint = _build_fingerprint(heatmap)

    # 7. Detect deviations against today
    deviations = await _detect_deviations(session, device_id, heatmap, now)

    # 8. Generate insights
    insights = _generate_insights(heatmap, fingerprint, deviations)

    # 9. Persist pattern (with cache timestamp)
    await _persist_pattern(session, device_id, heatmap)
    await session.commit()

    return _format_response(device, days_observed, days, now, heatmap, fingerprint, deviations, insights)


def _format_response(device, days_observed, days, now, heatmap, fingerprint, deviations, insights):
    return {
        "device_id": str(device.id),
        "device_identifier": device.device_identifier,
        "days_analyzed": days,
        "days_observed": days_observed,
        "generated_at": now.isoformat(),
        "heatmap": heatmap,
        "fingerprint": fingerprint,
        "deviations": deviations,
        "insights": insights,
    }


def _build_fingerprint(heatmap: list[dict]) -> dict:
    """Extract key behavioral landmarks from the heatmap."""
    # Wake time
    wake_hour = None
    for h in range(4, 12):
        if heatmap[h]["movement"] >= WAKE_MOVEMENT_THRESHOLD:
            wake_hour = h
            break
    if wake_hour is None:
        wake_hour = 7

    # Sleep time
    sleep_hour = None
    for h in range(23, 18, -1):
        if heatmap[h]["sleep"] >= SLEEP_PROBABILITY_THRESHOLD:
            sleep_hour = h
            break
    if sleep_hour is None:
        sleep_hour = 23

    # Peak activity hour (6-22)
    active_hours = [(p["hour"], p["movement"]) for p in heatmap if 6 <= p["hour"] <= 22]
    peak_hour = max(active_hours, key=lambda x: x[1])[0] if active_hours else 10

    # Rest window (12-17)
    afternoon = [(p["hour"], p["movement"]) for p in heatmap if 12 <= p["hour"] <= 17]
    rest_hour = min(afternoon, key=lambda x: x[1])[0] if afternoon else 15

    # Active window
    active_start = wake_hour
    active_end = sleep_hour
    for h in range(wake_hour, 22):
        if heatmap[h]["movement"] >= ACTIVE_THRESHOLD:
            active_start = h
            break
    for h in range(21, wake_hour, -1):
        if heatmap[h]["movement"] >= REST_THRESHOLD:
            active_end = h
            break

    # Routine stability as percentage (0-100)
    active_probs = [heatmap[h]["movement"] for h in range(wake_hour, sleep_hour)]
    if active_probs:
        mean_p = sum(active_probs) / len(active_probs)
        variance = sum((p - mean_p) ** 2 for p in active_probs) / len(active_probs)
        # Convert variance to stability: low variance = high stability
        # variance range ~0 to ~0.25 → stability 100% to 0%
        stability_pct = max(0, min(100, round(100 * (1 - variance / 0.25))))
    else:
        stability_pct = 0

    stability_label = "Stable" if stability_pct >= 75 else "Monitor" if stability_pct >= 50 else "Attention"

    return {
        "wake_time": f"{wake_hour:02d}:00",
        "wake_hour": wake_hour,
        "sleep_time": f"{sleep_hour:02d}:00",
        "sleep_hour": sleep_hour,
        "peak_activity_time": f"{peak_hour:02d}:00",
        "peak_activity_hour": peak_hour,
        "rest_window_time": f"{rest_hour:02d}:00",
        "rest_window_hour": rest_hour,
        "active_window": f"{active_start:02d}:00 – {active_end:02d}:00",
        "routine_stability": stability_pct,
        "routine_stability_label": stability_label,
    }


async def _detect_deviations(
    session: AsyncSession, device_id: str, heatmap: list[dict], now: datetime
) -> list[dict]:
    """Compare today's behavior against the life pattern to detect deviations."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current_hour = now.hour

    today_rows = (await session.execute(text("""
        SELECT EXTRACT(HOUR FROM created_at)::int AS hour, COUNT(*) AS cnt
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat'
          AND is_simulated = false AND created_at >= :start
        GROUP BY EXTRACT(HOUR FROM created_at)::int
    """), {"did": device_id, "start": today_start})).fetchall()

    today_by_hour = {int(r.hour): int(r.cnt) for r in today_rows}

    deviations = []
    for hour in range(min(current_hour + 1, 24)):
        expected = heatmap[hour]
        actual_events = today_by_hour.get(hour, 0)
        expected_movement = expected["movement"]

        if expected_movement >= 0.6 and actual_events == 0 and hour < current_hour:
            deviation_pct = round((expected_movement - 0) / max(expected_movement, 0.01) * 100, 1)
            deviations.append({
                "hour": hour,
                "type": "missing_activity",
                "expected_probability": expected_movement,
                "actual_events": actual_events,
                "deviation_percent": deviation_pct,
                "description": f"Expected activity at {hour:02d}:00 (prob {expected_movement:.0%}) but none detected",
            })

        if expected["sleep"] >= 0.7 and actual_events > 2:
            deviations.append({
                "hour": hour,
                "type": "unexpected_activity",
                "expected_probability": expected["sleep"],
                "actual_events": actual_events,
                "deviation_percent": round(actual_events / max(expected["avg_events"] + 1, 1) * 100, 1),
                "description": f"Unexpected activity at {hour:02d}:00 during expected sleep ({actual_events} events)",
            })

    return deviations


def _generate_insights(heatmap: list, fingerprint: dict, deviations: list) -> list[str]:
    """Generate human-readable AI insights from the heatmap."""
    insights = []

    wake = fingerprint.get("wake_hour", 7)
    sleep = fingerprint.get("sleep_hour", 23)
    peak = fingerprint.get("peak_activity_hour", 10)
    rest = fingerprint.get("rest_window_hour", 15)
    stability = fingerprint.get("routine_stability", 0)

    insights.append(f"Wake-up pattern: ~{wake:02d}:00")
    insights.append(f"Peak activity: {peak:02d}:00–{peak+2:02d}:00")

    if rest:
        insights.append(f"Rest window: ~{rest:02d}:00")

    evening_probs = [heatmap[h]["movement"] for h in range(17, 21)]
    if evening_probs:
        avg_evening = sum(evening_probs) / len(evening_probs)
        if avg_evening < 0.3:
            insights.append("Evening mobility slightly declining")
        elif avg_evening > 0.6:
            insights.append("Good evening mobility detected")

    insights.append(f"Sleep start: ~{sleep:02d}:00")
    insights.append(f"Routine stability: {stability}%")

    if deviations:
        missing = [d for d in deviations if d["type"] == "missing_activity"]
        unexpected = [d for d in deviations if d["type"] == "unexpected_activity"]
        if missing:
            insights.append(f"Today: {len(missing)} expected activity window(s) missed")
        if unexpected:
            insights.append(f"Today: unexpected activity during {len(unexpected)} sleep window(s)")

    return insights


async def get_fleet_life_pattern_alerts(session: AsyncSession) -> list[dict]:
    """Get life pattern deviation alerts across the fleet for Command Center."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current_hour = now.hour

    devices = (await session.execute(text("""
        SELECT DISTINCT lp.device_id, d.device_identifier
        FROM life_pattern_profiles lp
        JOIN devices d ON lp.device_id = d.id
    """))).fetchall()

    alerts = []
    for dev in devices:
        pattern_rows = (await session.execute(text("""
            SELECT hour_of_day, movement_probability, sleep_probability, avg_events
            FROM life_pattern_profiles
            WHERE device_id = :did
            ORDER BY hour_of_day
        """), {"did": str(dev.device_id)})).fetchall()

        if not pattern_rows:
            continue

        pattern_by_hour = {r.hour_of_day: r for r in pattern_rows}

        today_rows = (await session.execute(text("""
            SELECT EXTRACT(HOUR FROM created_at)::int AS hour, COUNT(*) AS cnt
            FROM telemetries
            WHERE device_id = :did AND metric_type = 'heartbeat'
              AND is_simulated = false AND created_at >= :start
            GROUP BY EXTRACT(HOUR FROM created_at)::int
        """), {"did": str(dev.device_id), "start": today_start})).fetchall()

        today_by_hour = {int(r.hour): int(r.cnt) for r in today_rows}

        for hour in range(min(current_hour + 1, 24)):
            p = pattern_by_hour.get(hour)
            if not p:
                continue
            actual = today_by_hour.get(hour, 0)

            if p.movement_probability >= 0.6 and actual == 0 and hour < current_hour:
                alerts.append({
                    "device_id": str(dev.device_id),
                    "device_identifier": dev.device_identifier,
                    "type": "routine_deviation",
                    "hour": hour,
                    "description": f"Expected activity at {hour:02d}:00 but none detected",
                    "severity": "high" if p.movement_probability >= 0.8 else "medium",
                })

            if p.sleep_probability >= 0.7 and actual > 2:
                alerts.append({
                    "device_id": str(dev.device_id),
                    "device_identifier": dev.device_identifier,
                    "type": "sleep_disruption",
                    "hour": hour,
                    "description": f"Unexpected activity at {hour:02d}:00 during sleep window",
                    "severity": "medium",
                })

    alerts.sort(key=lambda a: 0 if a["severity"] == "high" else 1)
    return alerts


# ── Cache ──

async def _get_cached_pattern(session, device_id, now):
    """Return cached heatmap if computed within CACHE_TTL_HOURS, else None."""
    cutoff = now - timedelta(hours=CACHE_TTL_HOURS)
    rows = (await session.execute(text("""
        SELECT hour_of_day, movement_probability, interaction_probability,
               sleep_probability, anomaly_probability, location_change_probability,
               avg_events, samples, updated_at
        FROM life_pattern_profiles
        WHERE device_id = :did
        ORDER BY hour_of_day
    """), {"did": device_id})).fetchall()

    if not rows or len(rows) < 24:
        return None

    # Check if most recent update is within TTL
    latest = max(r.updated_at for r in rows)
    if latest.tzinfo is None:
        from datetime import timezone as tz
        latest = latest.replace(tzinfo=tz.utc)
    if latest < cutoff:
        return None

    return [
        {
            "hour": r.hour_of_day,
            "sleep": round(float(r.sleep_probability), 3),
            "movement": round(float(r.movement_probability), 3),
            "interaction": round(float(r.interaction_probability), 3),
            "location": round(float(r.location_change_probability), 3),
            "anomaly": round(float(r.anomaly_probability), 3),
            "avg_events": round(float(r.avg_events), 2),
            "samples": int(r.samples),
        }
        for r in rows
    ]


# ── Data Fetchers ──

async def _aggregate_hourly_telemetry(session, device_id, cutoff):
    rows = (await session.execute(text("""
        SELECT EXTRACT(HOUR FROM created_at)::int AS hour, COUNT(*) AS cnt
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat'
          AND is_simulated = false AND created_at >= :cutoff
        GROUP BY EXTRACT(HOUR FROM created_at)::int
    """), {"did": device_id, "cutoff": cutoff})).fetchall()
    return {int(r.hour): {"count": int(r.cnt)} for r in rows}


async def _get_baselines(session, device_id):
    rows = (await session.execute(text("""
        SELECT hour_of_day, avg_movement, avg_location_switch, avg_interaction_rate
        FROM behavior_baselines
        WHERE device_id = :did
        ORDER BY hour_of_day
    """), {"did": device_id})).fetchall()
    return {
        r.hour_of_day: {
            "avg_movement": r.avg_movement,
            "avg_location_switch": r.avg_location_switch,
            "avg_interaction_rate": r.avg_interaction_rate,
        }
        for r in rows
    }


async def _get_anomaly_distribution(session, device_id, cutoff):
    rows = (await session.execute(text("""
        SELECT EXTRACT(HOUR FROM created_at)::int AS hour, COUNT(*) AS cnt
        FROM behavior_anomalies
        WHERE device_id = :did AND is_simulated = false AND created_at >= :cutoff
        GROUP BY EXTRACT(HOUR FROM created_at)::int
    """), {"did": device_id, "cutoff": cutoff})).fetchall()
    return {int(r.hour): int(r.cnt) for r in rows}


async def _count_observed_days(session, device_id, cutoff):
    r = (await session.execute(text("""
        SELECT COUNT(DISTINCT DATE(created_at))
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat'
          AND is_simulated = false AND created_at >= :cutoff
    """), {"did": device_id, "cutoff": cutoff})).scalar()
    return int(r) if r else 0


async def _persist_pattern(session, device_id, heatmap):
    for p in heatmap:
        await session.execute(text("""
            INSERT INTO life_pattern_profiles
            (device_id, hour_of_day, movement_probability, interaction_probability,
             sleep_probability, anomaly_probability, location_change_probability,
             avg_events, samples, updated_at)
            VALUES (:did, :hour, :mov, :inter, :sleep, :anom, :loc, :avg, :samples, NOW())
            ON CONFLICT (device_id, hour_of_day) DO UPDATE SET
                movement_probability = EXCLUDED.movement_probability,
                interaction_probability = EXCLUDED.interaction_probability,
                sleep_probability = EXCLUDED.sleep_probability,
                anomaly_probability = EXCLUDED.anomaly_probability,
                location_change_probability = EXCLUDED.location_change_probability,
                avg_events = EXCLUDED.avg_events,
                samples = EXCLUDED.samples,
                updated_at = NOW()
        """), {
            "did": device_id,
            "hour": p["hour"],
            "mov": p["movement"],
            "inter": p["interaction"],
            "sleep": p["sleep"],
            "anom": p["anomaly"],
            "loc": p["location"],
            "avg": p["avg_events"],
            "samples": p["samples"],
        })
