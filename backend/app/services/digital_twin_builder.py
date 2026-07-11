# Digital Twin Builder Service
# Aggregates behavior_baselines into a personalized per-device Digital Twin profile.
# Detects wake/sleep rhythms, activity windows, movement intervals, and
# personalized inactivity thresholds from accumulated behavioral data.

import logging
import math
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Minimum baseline sample_count per hour before twin is built
MIN_SAMPLES_FOR_TWIN = 3
# Confidence thresholds
LOW_CONFIDENCE = 0.3
MEDIUM_CONFIDENCE = 0.6
HIGH_CONFIDENCE = 0.85


async def run_twin_builder_cycle():
    """Main cycle: read baselines → build/update digital twins for all devices."""
    async with async_session() as session:
        try:
            count = await _build_all_twins(session)
            await session.commit()
            if count > 0:
                logger.info(f"Digital Twin builder: updated {count} device twins")
        except Exception:
            await session.rollback()
            logger.exception("Digital Twin builder cycle failed")


async def _build_all_twins(session: AsyncSession) -> int:
    """Build or update digital twins for all devices with sufficient baseline data."""
    now = datetime.now(timezone.utc)

    # Fetch all devices with behavior baselines
    device_rows = (await session.execute(text("""
        SELECT DISTINCT device_id FROM behavior_baselines
        WHERE sample_count >= :min_samples
    """), {"min_samples": MIN_SAMPLES_FOR_TWIN})).fetchall()

    updated = 0
    for row in device_rows:
        device_id = row.device_id
        try:
            twin_data = await _build_twin_for_device(session, device_id, now)
            if twin_data:
                await _upsert_twin(session, device_id, twin_data, now)
                updated += 1
        except Exception:
            logger.exception(f"Failed to build twin for device {device_id}")

    return updated


async def build_single_twin(session: AsyncSession, device_id) -> dict | None:
    """Build/rebuild a single device's digital twin. Used by the force-rebuild API."""
    now = datetime.now(timezone.utc)
    twin_data = await _build_twin_for_device(session, device_id, now)
    if twin_data:
        await _upsert_twin(session, device_id, twin_data, now)
        await session.commit()
    return twin_data


async def _build_twin_for_device(session: AsyncSession, device_id, now: datetime) -> dict | None:
    """
    Build a Digital Twin profile from behavior_baselines for a single device.

    Returns a dict with:
      - daily_rhythm: {hour: {avg_movement, avg_interaction, expected_active, ...}}
      - wake_hour, sleep_hour, peak_activity_hour
      - activity_windows: [{start_hour, end_hour, type, avg_movement}]
      - movement_interval_minutes
      - typical_inactivity_max_minutes
      - confidence_score
      - training_data_points
      - profile_summary
    """
    baselines = (await session.execute(text("""
        SELECT hour_of_day, avg_movement, std_movement,
               avg_location_switch, std_location_switch,
               avg_interaction_rate, std_interaction_rate,
               sample_count
        FROM behavior_baselines
        WHERE device_id = :device_id
        ORDER BY hour_of_day
    """), {"device_id": device_id})).fetchall()

    if not baselines:
        return None

    # Build 24-hour rhythm map
    rhythm = {}
    total_data_points = 0
    hours_with_data = 0

    for b in baselines:
        h = b.hour_of_day
        avg_mov = float(b.avg_movement)
        avg_int = float(b.avg_interaction_rate)
        count = b.sample_count
        total_data_points += count
        hours_with_data += 1

        rhythm[str(h)] = {
            "avg_movement": round(avg_mov, 3),
            "std_movement": round(float(b.std_movement), 3),
            "avg_interaction": round(avg_int, 2),
            "std_interaction": round(float(b.std_interaction_rate), 2),
            "avg_location_switch": round(float(b.avg_location_switch), 3),
            "sample_count": count,
            "expected_active": avg_int >= 2.0,  # at least 2 heartbeats/hour = active
        }

    # Detect wake/sleep from interaction pattern
    wake_hour, sleep_hour = _detect_wake_sleep(rhythm)
    peak_hour = _detect_peak_activity(rhythm)

    # Build activity windows (contiguous active periods)
    activity_windows = _detect_activity_windows(rhythm, wake_hour, sleep_hour)

    # Compute movement interval (avg time between significant movement changes)
    movement_interval = _compute_movement_interval(rhythm)

    # Compute personalized max inactivity
    typical_inactivity = _compute_typical_inactivity(rhythm, wake_hour, sleep_hour)

    # Confidence score based on data quality
    confidence = _compute_confidence(hours_with_data, total_data_points, baselines)

    # Profile summary (human-readable)
    profile_summary = {
        "wake_time": f"{wake_hour:02d}:00" if wake_hour is not None else "unknown",
        "sleep_time": f"{sleep_hour:02d}:00" if sleep_hour is not None else "unknown",
        "peak_activity": f"{peak_hour:02d}:00" if peak_hour is not None else "unknown",
        "active_hours": sum(1 for v in rhythm.values() if v["expected_active"]),
        "total_hours_profiled": hours_with_data,
        "data_quality": "high" if confidence >= HIGH_CONFIDENCE else ("medium" if confidence >= MEDIUM_CONFIDENCE else "low"),
        "personality_tag": _personality_tag(rhythm, wake_hour, sleep_hour),
    }

    return {
        "daily_rhythm": rhythm,
        "wake_hour": wake_hour,
        "sleep_hour": sleep_hour,
        "peak_activity_hour": peak_hour,
        "activity_windows": activity_windows,
        "movement_interval_minutes": movement_interval,
        "typical_inactivity_max_minutes": typical_inactivity,
        "confidence_score": round(confidence, 3),
        "training_data_points": total_data_points,
        "profile_summary": profile_summary,
    }


def _detect_wake_sleep(rhythm: dict) -> tuple:
    """Detect wake and sleep hours from interaction_rate transitions."""
    # Build ordered activity array (0-23)
    active = [False] * 24
    for h_str, data in rhythm.items():
        h = int(h_str)
        active[h] = data["expected_active"]

    # Find first active hour (wake) and last active hour (sleep)
    wake_hour = None
    sleep_hour = None

    for h in range(24):
        if active[h]:
            if wake_hour is None:
                wake_hour = h
            sleep_hour = h

    # If sleep_hour found, sleep starts at sleep_hour + 1
    if sleep_hour is not None:
        sleep_hour = (sleep_hour + 1) % 24

    return wake_hour, sleep_hour


def _detect_peak_activity(rhythm: dict) -> int | None:
    """Find the hour with highest combined movement + interaction."""
    if not rhythm:
        return None
    peak_h = max(rhythm.keys(), key=lambda h: rhythm[h]["avg_movement"] + rhythm[h]["avg_interaction"])
    return int(peak_h)


def _detect_activity_windows(rhythm: dict, wake_hour: int | None, sleep_hour: int | None) -> list:
    """Identify contiguous active periods as named windows."""
    windows = []
    active_hours = sorted([int(h) for h, d in rhythm.items() if d["expected_active"]])

    if not active_hours:
        return windows

    # Group contiguous hours
    groups = []
    current_group = [active_hours[0]]
    for h in active_hours[1:]:
        if h == current_group[-1] + 1:
            current_group.append(h)
        else:
            groups.append(current_group)
            current_group = [h]
    groups.append(current_group)

    # Label windows
    for group in groups:
        start_h = group[0]
        end_h = group[-1]
        avg_mov = sum(rhythm[str(h)]["avg_movement"] for h in group) / len(group)

        window_type = _classify_window(start_h, end_h)
        windows.append({
            "start_hour": start_h,
            "end_hour": end_h + 1,  # exclusive
            "type": window_type,
            "hours": len(group),
            "avg_movement": round(avg_mov, 3),
        })

    return windows


def _classify_window(start_h: int, end_h: int) -> str:
    """Classify an activity window by time of day."""
    mid = (start_h + end_h) // 2
    if 5 <= mid < 10:
        return "morning_routine"
    elif 10 <= mid < 14:
        return "midday_activity"
    elif 14 <= mid < 18:
        return "afternoon_activity"
    elif 18 <= mid < 22:
        return "evening_routine"
    elif mid >= 22 or mid < 5:
        return "late_night"
    return "activity"


def _compute_movement_interval(rhythm: dict) -> float | None:
    """Estimate typical minutes between movement events from average interaction rate."""
    active_rates = [d["avg_interaction"] for d in rhythm.values() if d["expected_active"] and d["avg_interaction"] > 0]
    if not active_rates:
        return None
    avg_rate = sum(active_rates) / len(active_rates)
    # avg_rate = heartbeats per hour during active hours
    # movement_interval ≈ 60 / avg_rate (minutes between heartbeats)
    interval = 60.0 / max(avg_rate, 0.5)
    return round(interval, 1)


def _compute_typical_inactivity(rhythm: dict, wake_hour: int | None, sleep_hour: int | None) -> float | None:
    """
    Compute the personalized maximum expected inactivity during waking hours.
    Uses the lowest interaction rate during active hours as the baseline,
    then computes the implied gap: 60 / min_rate.
    """
    if wake_hour is None:
        return None

    active_rates = []
    for h_str, data in rhythm.items():
        if data["expected_active"] and data["avg_interaction"] > 0:
            active_rates.append(data["avg_interaction"])

    if not active_rates:
        return 60.0  # default fallback

    min_rate = min(active_rates)
    # Inactivity max = expected gap at the lowest-activity waking hour, with a buffer
    max_inactivity = (60.0 / max(min_rate, 0.5)) * 1.5  # 1.5x buffer
    return round(max(max_inactivity, 30.0), 1)  # floor at 30 minutes


def _compute_confidence(hours_with_data: int, total_points: int, baselines) -> float:
    """
    Confidence = f(hours_coverage, data_density, consistency).
    0.0 = no data, 1.0 = full 24h coverage with dense, consistent data.
    """
    # Factor 1: Hour coverage (24h full = 1.0)
    coverage = min(hours_with_data / 24.0, 1.0)

    # Factor 2: Data density (avg samples per hour)
    if hours_with_data > 0:
        avg_samples = total_points / hours_with_data
        density = min(avg_samples / 10.0, 1.0)  # 10+ samples/hour = full
    else:
        density = 0.0

    # Factor 3: Consistency (low std relative to avg = consistent)
    consistencies = []
    for b in baselines:
        if b.avg_movement > 0.01:
            cv = b.std_movement / max(b.avg_movement, 0.01)
            consistencies.append(max(0, 1 - cv / 2))  # cv=0 → 1.0, cv=2 → 0
    consistency = sum(consistencies) / len(consistencies) if consistencies else 0.5

    # Weighted combination
    confidence = 0.4 * coverage + 0.35 * density + 0.25 * consistency
    return min(max(confidence, 0.0), 1.0)


def _personality_tag(rhythm: dict, wake_hour: int | None, sleep_hour: int | None) -> str:
    """Generate a human-friendly personality tag based on the profile."""
    if wake_hour is None:
        return "Emerging Profile"

    active_count = sum(1 for d in rhythm.values() if d["expected_active"])

    if wake_hour <= 6:
        tag = "Early Riser"
    elif wake_hour >= 9:
        tag = "Late Starter"
    else:
        tag = "Regular Schedule"

    if active_count >= 14:
        tag += " · Very Active"
    elif active_count >= 8:
        tag += " · Moderately Active"
    else:
        tag += " · Low Activity"

    return tag


async def _upsert_twin(session: AsyncSession, device_id, twin_data: dict, now: datetime):
    """Insert or update the device's digital twin in the database."""
    import json

    existing = (await session.execute(text("""
        SELECT id, twin_version FROM device_digital_twins WHERE device_id = :device_id
    """), {"device_id": device_id})).fetchone()

    if existing:
        await session.execute(text("""
            UPDATE device_digital_twins
            SET twin_version = twin_version + 1,
                wake_hour = :wake_hour,
                sleep_hour = :sleep_hour,
                peak_activity_hour = :peak_hour,
                movement_interval_minutes = :mov_interval,
                typical_inactivity_max_minutes = :inactivity_max,
                daily_rhythm = CAST(:rhythm AS jsonb),
                activity_windows = CAST(:windows AS jsonb),
                profile_summary = CAST(:summary AS jsonb),
                confidence_score = :confidence,
                training_data_points = :data_points,
                last_trained_at = :now,
                updated_at = :now
            WHERE device_id = :device_id
        """), {
            "device_id": device_id,
            "wake_hour": twin_data["wake_hour"],
            "sleep_hour": twin_data["sleep_hour"],
            "peak_hour": twin_data["peak_activity_hour"],
            "mov_interval": twin_data["movement_interval_minutes"],
            "inactivity_max": twin_data["typical_inactivity_max_minutes"],
            "rhythm": json.dumps(twin_data["daily_rhythm"]),
            "windows": json.dumps(twin_data["activity_windows"]),
            "summary": json.dumps(twin_data["profile_summary"]),
            "confidence": twin_data["confidence_score"],
            "data_points": twin_data["training_data_points"],
            "now": now,
        })
    else:
        await session.execute(text("""
            INSERT INTO device_digital_twins
                (id, device_id, twin_version, wake_hour, sleep_hour, peak_activity_hour,
                 movement_interval_minutes, typical_inactivity_max_minutes,
                 daily_rhythm, activity_windows, profile_summary,
                 confidence_score, training_data_points, last_trained_at, created_at, updated_at)
            VALUES (gen_random_uuid(), :device_id, 1, :wake_hour, :sleep_hour, :peak_hour,
                    :mov_interval, :inactivity_max,
                    CAST(:rhythm AS jsonb), CAST(:windows AS jsonb), CAST(:summary AS jsonb),
                    :confidence, :data_points, :now, :now, :now)
        """), {
            "device_id": device_id,
            "wake_hour": twin_data["wake_hour"],
            "sleep_hour": twin_data["sleep_hour"],
            "peak_hour": twin_data["peak_activity_hour"],
            "mov_interval": twin_data["movement_interval_minutes"],
            "inactivity_max": twin_data["typical_inactivity_max_minutes"],
            "rhythm": json.dumps(twin_data["daily_rhythm"]),
            "windows": json.dumps(twin_data["activity_windows"]),
            "summary": json.dumps(twin_data["profile_summary"]),
            "confidence": twin_data["confidence_score"],
            "data_points": twin_data["training_data_points"],
            "now": now,
        })


def start_twin_builder_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_twin_builder_cycle, 'interval', minutes=30,
        id='twin_builder_cycle',
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    _scheduler.start()
    logger.info("Digital Twin builder scheduler started — polling every 30 min")


def stop_twin_builder_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
