# Behavioral Pattern AI Service
# Extracts behavioral features from telemetry, builds per-device per-hour baselines,
# detects deviations, and produces behavior_risk_scores.
#
# Approach C: Derives movement proxy from signal_strength variance, interaction_rate
# from heartbeat frequency, and location_switch from signal pattern changes.
# Schema supports real movement data when available.

import logging
import math
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# ── Constants ──
BEHAVIOR_WINDOW_HOURS = 24       # baseline lookback
MIN_SAMPLES_FOR_BASELINE = 3     # min heartbeats per hour to build baseline
INACTIVITY_THRESHOLD_MINUTES = 60  # flag if no heartbeat for this long
SCORE_CLAMP_MAX = 1.0
SCORE_CLAMP_MIN = 0.0


# ── SB-04 (dual-read) ────────────────────────────────────────────
#
# `behavior_baselines` (per-device per-hour, hardcoded EMA columns)
# is the legacy table. `device_baselines` (per-device per-metric,
# expected_value + lower_band + upper_band) is the newer model.
# Both coexist while the SB-02 matview still sources from the
# legacy table. This helper bridges them:
#
#   * If a `device_baselines` row exists for the (device, metric)
#     pair, we use it — `expected_value` becomes the avg, and we
#     synthesise a `std` from the band width via
#     `(upper - lower) / 4` (≈ ±2σ band → σ = width / 4).
#   * Otherwise we fall back to the legacy `behavior_baselines` row.
#
# The synthesised row keeps the legacy column names so callers
# don't change. When the SB-02 matview is finally reshaped to
# source from `device_baselines`, this shim disappears.
#
# `MIN_BAND_STD` is a floor that matches the `max(0.1, …)` clamp
# the legacy EMA writer uses — keeps z-scores numerically stable
# when a band is narrow.

_MIN_BAND_STD = 0.1


class _BaselineRow:
    """Tiny shim so consumer code can keep using attribute access
    (`b.avg_movement`, `b.sample_count`) without conditionally
    indexing dicts. Mirrors the legacy SQLAlchemy `Row` surface."""
    __slots__ = (
        "avg_movement", "std_movement",
        "avg_location_switch", "std_location_switch",
        "avg_interaction_rate", "std_interaction_rate",
        "sample_count",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _band_std(lower: float, upper: float) -> float:
    """Synthesise σ from a (lower, upper) ±2σ band.

    A `device_baselines` row exposes `expected_value` with a
    `lower_band` / `upper_band` whose width is conventionally ≈ 4σ
    (mean ±2σ). Therefore σ ≈ (upper - lower) / 4. Clamped at
    `_MIN_BAND_STD` to mirror the legacy EMA writer's floor."""
    width = (upper or 0.0) - (lower or 0.0)
    return max(_MIN_BAND_STD, width / 4.0)


async def _load_baseline_dual(
    session: AsyncSession,
    device_id,
    hour: int,
):
    """Dual-read: prefer `device_baselines`, fall back to
    `behavior_baselines`. Returns a `_BaselineRow`-shaped object
    OR None (no baseline anywhere).

    Metric mapping (locked):
      `movement`         → avg_movement / std_movement
      `location_switch`  → avg_location_switch / std_location_switch
      `interaction_rate` → avg_interaction_rate / std_interaction_rate

    `sample_count` is sourced from the legacy row when present (the
    `MIN_SAMPLES_FOR_BASELINE` gate is still the primary readiness
    signal). When ONLY device_baselines rows exist, we synthesise
    `sample_count = MIN_SAMPLES_FOR_BASELINE` so the consumer's
    readiness gate doesn't reject a perfectly good baseline."""
    db_rows = (await session.execute(text("""
        SELECT metric, expected_value, lower_band, upper_band
          FROM device_baselines
         WHERE device_id = :device_id
           AND metric IN ('movement', 'location_switch', 'interaction_rate')
    """), {"device_id": device_id})).fetchall()
    by_metric = {r.metric: r for r in db_rows}

    legacy = (await session.execute(text("""
        SELECT avg_movement, std_movement,
               avg_location_switch, std_location_switch,
               avg_interaction_rate, std_interaction_rate,
               sample_count
          FROM behavior_baselines
         WHERE device_id = :device_id AND hour_of_day = :hour
    """), {"device_id": device_id, "hour": hour})).fetchone()

    # If neither source has anything → no baseline.
    if not by_metric and not legacy:
        return None

    def _pick(metric: str, legacy_avg, legacy_std):
        """Return (avg, std) — prefer device_baselines if present."""
        row = by_metric.get(metric)
        if row is not None and row.expected_value is not None:
            return (
                float(row.expected_value),
                _band_std(row.lower_band, row.upper_band),
            )
        if legacy_avg is None:
            return (None, None)
        return (float(legacy_avg), float(legacy_std or _MIN_BAND_STD))

    mv_avg, mv_std = _pick(
        "movement",
        legacy.avg_movement if legacy else None,
        legacy.std_movement if legacy else None,
    )
    ls_avg, ls_std = _pick(
        "location_switch",
        legacy.avg_location_switch if legacy else None,
        legacy.std_location_switch if legacy else None,
    )
    ir_avg, ir_std = _pick(
        "interaction_rate",
        legacy.avg_interaction_rate if legacy else None,
        legacy.std_interaction_rate if legacy else None,
    )

    # If movement OR interaction couldn't be filled, we don't have a
    # usable baseline for anomaly detection — return None so the
    # caller's `MIN_SAMPLES_FOR_BASELINE` gate trips cleanly.
    if mv_avg is None or ir_avg is None:
        return None

    sample_count = (
        legacy.sample_count if legacy and legacy.sample_count is not None
        else MIN_SAMPLES_FOR_BASELINE
    )
    return _BaselineRow(
        avg_movement=mv_avg,         std_movement=mv_std,
        avg_location_switch=ls_avg,  std_location_switch=ls_std,
        avg_interaction_rate=ir_avg, std_interaction_rate=ir_std,
        sample_count=int(sample_count),
    )


async def run_behavior_cycle():
    """Main cycle: extract features → update baselines → detect deviations."""
    async with async_session() as session:
        try:
            await _update_behavioral_baselines(session)
            await _detect_behavioral_anomalies(session)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Behavior AI cycle failed")


async def _update_behavioral_baselines(session: AsyncSession):
    """
    Build/update rolling behavioral baselines per device per hour-of-day.
    Features derived from telemetry:
      - movement_proxy: stddev of signal_strength in the hour (higher variance = more movement)
      - location_switch_proxy: count of significant signal changes (>5 units between consecutive readings)
      - interaction_rate: heartbeat count per hour (device activity indicator)
    """
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=BEHAVIOR_WINDOW_HOURS)

    # Compute behavioral features per device per hour from recent telemetry
    rows = (await session.execute(text("""
        WITH hourly AS (
            SELECT
                device_id,
                EXTRACT(HOUR FROM created_at)::int AS hour_of_day,
                STDDEV_POP((metric_value->>'signal_strength')::float) AS signal_stddev,
                COUNT(*) AS heartbeat_count,
                AVG((metric_value->>'signal_strength')::float) AS avg_signal,
                MAX((metric_value->>'signal_strength')::float) - MIN((metric_value->>'signal_strength')::float) AS signal_range
            FROM telemetries
            WHERE metric_type = 'heartbeat'
              AND is_simulated = false
              AND created_at >= :lookback
              AND created_at <= :now
            GROUP BY device_id, EXTRACT(HOUR FROM created_at)::int
            HAVING COUNT(*) >= :min_samples
        )
        SELECT
            device_id,
            hour_of_day,
            COALESCE(signal_stddev, 0) AS movement_proxy,
            COALESCE(signal_range / GREATEST(heartbeat_count, 1), 0) AS location_switch_proxy,
            heartbeat_count AS interaction_rate
        FROM hourly
    """), {
        "lookback": lookback,
        "now": now,
        "min_samples": MIN_SAMPLES_FOR_BASELINE,
    })).fetchall()

    if not rows:
        return

    # Upsert baselines with exponential moving average
    alpha = 0.3  # EMA smoothing factor
    for r in rows:
        # SB-04 dual-read: prefer device_baselines, fall back to
        # behavior_baselines. The EMA UPDATE/INSERT below still
        # writes to behavior_baselines (the matview source) — the
        # dual-read only affects EMA continuity, not the write side.
        existing = await _load_baseline_dual(
            session, r.device_id, r.hour_of_day,
        )

        movement = float(r.movement_proxy)
        loc_switch = float(r.location_switch_proxy)
        interaction = float(r.interaction_rate)

        if existing and existing.sample_count > 0:
            # EMA update
            new_avg_mov = (1 - alpha) * existing.avg_movement + alpha * movement
            new_std_mov = max(0.1, (1 - alpha) * existing.std_movement + alpha * abs(movement - existing.avg_movement))
            new_avg_loc = (1 - alpha) * existing.avg_location_switch + alpha * loc_switch
            new_std_loc = max(0.1, (1 - alpha) * existing.std_location_switch + alpha * abs(loc_switch - existing.avg_location_switch))
            new_avg_int = (1 - alpha) * existing.avg_interaction_rate + alpha * interaction
            new_std_int = max(0.1, (1 - alpha) * existing.std_interaction_rate + alpha * abs(interaction - existing.avg_interaction_rate))
            new_count = existing.sample_count + 1

            await session.execute(text("""
                UPDATE behavior_baselines
                SET avg_movement = :avg_mov, std_movement = :std_mov,
                    avg_location_switch = :avg_loc, std_location_switch = :std_loc,
                    avg_interaction_rate = :avg_int, std_interaction_rate = :std_int,
                    sample_count = :count, updated_at = :now
                WHERE device_id = :device_id AND hour_of_day = :hour
            """), {
                "avg_mov": new_avg_mov, "std_mov": new_std_mov,
                "avg_loc": new_avg_loc, "std_loc": new_std_loc,
                "avg_int": new_avg_int, "std_int": new_std_int,
                "count": new_count, "now": now,
                "device_id": r.device_id, "hour": r.hour_of_day,
            })
        else:
            # Insert new baseline
            await session.execute(text("""
                INSERT INTO behavior_baselines
                    (id, device_id, hour_of_day, avg_movement, std_movement,
                     avg_location_switch, std_location_switch,
                     avg_interaction_rate, std_interaction_rate,
                     sample_count, updated_at)
                VALUES (gen_random_uuid(), :device_id, :hour, :avg_mov, :std_mov,
                        :avg_loc, :std_loc, :avg_int, :std_int, 1, :now)
                ON CONFLICT (device_id, hour_of_day) DO UPDATE SET
                    avg_movement = EXCLUDED.avg_movement,
                    std_movement = EXCLUDED.std_movement,
                    avg_location_switch = EXCLUDED.avg_location_switch,
                    std_location_switch = EXCLUDED.std_location_switch,
                    avg_interaction_rate = EXCLUDED.avg_interaction_rate,
                    std_interaction_rate = EXCLUDED.std_interaction_rate,
                    sample_count = behavior_baselines.sample_count + 1,
                    updated_at = EXCLUDED.updated_at
            """), {
                "device_id": r.device_id, "hour": r.hour_of_day,
                "avg_mov": movement, "std_mov": max(0.1, movement * 0.3),
                "avg_loc": loc_switch, "std_loc": max(0.1, loc_switch * 0.3),
                "avg_int": interaction, "std_int": max(0.1, interaction * 0.3),
                "now": now,
            })

    updated = len(rows)
    if updated > 0:
        logger.info(f"Behavior baselines updated: {updated} device-hour entries")


async def _detect_behavioral_anomalies(session: AsyncSession):
    """
    Detect behavioral deviations — Twin-Aware Risk Engine.

    If a digital twin exists (confidence >= 0.3), scoring is personalized:
      - Expected active but inactive → boosted score
      - Sleep time and inactive → suppressed score
      - Personal inactivity threshold instead of global

    Falls back to generic z-score if no twin is available.
    """
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    recent_window = now - timedelta(minutes=30)

    # Load all digital twins (keyed by device_id)
    twin_rows = (await session.execute(text("""
        SELECT device_id, wake_hour, sleep_hour, typical_inactivity_max_minutes,
               movement_interval_minutes, daily_rhythm, confidence_score
        FROM device_digital_twins
        WHERE confidence_score >= 0.15
    """))).fetchall()

    twins = {}
    for t in twin_rows:
        twins[str(t.device_id)] = {
            "wake_hour": t.wake_hour,
            "sleep_hour": t.sleep_hour,
            "inactivity_max": t.typical_inactivity_max_minutes,
            "movement_interval": t.movement_interval_minutes,
            "rhythm": t.daily_rhythm or {},
            "confidence": t.confidence_score,
        }

    # Get recent behavioral features per device
    recent_features = (await session.execute(text("""
        SELECT
            t.device_id,
            d.device_identifier,
            STDDEV_POP((t.metric_value->>'signal_strength')::float) AS movement_proxy,
            MAX((t.metric_value->>'signal_strength')::float) - MIN((t.metric_value->>'signal_strength')::float) AS signal_range,
            COUNT(*) AS heartbeat_count,
            MAX(t.created_at) AS last_heartbeat
        FROM telemetries t
        JOIN devices d ON t.device_id = d.id
        WHERE t.metric_type = 'heartbeat'
          AND t.is_simulated = false
          AND t.created_at >= :recent
          AND t.created_at <= :now
        GROUP BY t.device_id, d.device_identifier
    """), {"recent": recent_window, "now": now})).fetchall()

    # Also check for extended inactivity (devices with NO recent heartbeats)
    inactive_devices = (await session.execute(text("""
        SELECT d.id AS device_id, d.device_identifier,
               MAX(t.created_at) AS last_heartbeat
        FROM devices d
        LEFT JOIN telemetries t ON d.id = t.device_id
            AND t.metric_type = 'heartbeat'
            AND t.is_simulated = false
            AND t.created_at >= :inactivity_lookback
        GROUP BY d.id, d.device_identifier
        HAVING MAX(t.created_at) IS NULL
           OR MAX(t.created_at) < :inactivity_threshold
    """), {
        "inactivity_lookback": now - timedelta(hours=24),
        "inactivity_threshold": now - timedelta(minutes=INACTIVITY_THRESHOLD_MINUTES),
    })).fetchall()

    anomalies_created = 0

    # 1. Score active devices against baselines (+ twin context)
    for r in recent_features:
        # SB-04 dual-read: device_baselines first, behavior_baselines fallback.
        baseline = await _load_baseline_dual(
            session, r.device_id, current_hour,
        )

        if not baseline or baseline.sample_count < MIN_SAMPLES_FOR_BASELINE:
            continue

        movement = float(r.movement_proxy or 0)
        interaction = float(r.heartbeat_count)
        device_twin = twins.get(str(r.device_id))

        # Compute z-scores
        z_movement = abs(movement - baseline.avg_movement) / max(baseline.std_movement, 0.1)
        z_interaction = abs(interaction - baseline.avg_interaction_rate) / max(baseline.std_interaction_rate, 0.1)

        # Generic z-score based score
        raw_score = (z_movement * 0.5 + z_interaction * 0.5) / 3.0
        behavior_score = max(SCORE_CLAMP_MIN, min(SCORE_CLAMP_MAX, raw_score))

        # Twin-aware boost/suppression
        twin_context = None
        if device_twin and device_twin["confidence"] >= 0.3:
            twin_context = _apply_twin_context(
                behavior_score, device_twin, current_hour,
                movement, interaction, baseline,
            )
            behavior_score = twin_context["adjusted_score"]

        if behavior_score >= 0.3:
            anomaly_type = _classify_anomaly(z_movement, z_interaction, movement, interaction, baseline)
            # Override type if twin detected specific pattern
            if twin_context and twin_context.get("twin_anomaly_type"):
                anomaly_type = twin_context["twin_anomaly_type"]

            reason = _build_reason(anomaly_type, movement, interaction, baseline, twin_context)

            await session.execute(text("""
                INSERT INTO behavior_anomalies (id, device_id, behavior_score, anomaly_type, reason, is_simulated, created_at)
                VALUES (gen_random_uuid(), :device_id, :score, :type, :reason, false, :now)
            """), {
                "device_id": str(r.device_id), "score": round(behavior_score, 3),
                "type": anomaly_type, "reason": reason, "now": now,
            })
            anomalies_created += 1

    # 2. Score inactive devices (twin-aware inactivity detection)
    for r in inactive_devices:
        inactivity_minutes = INACTIVITY_THRESHOLD_MINUTES
        if r.last_heartbeat:
            inactivity_minutes = (now - r.last_heartbeat).total_seconds() / 60.0

        device_twin = twins.get(str(r.device_id))

        # Twin-aware inactivity scoring
        if device_twin and device_twin["confidence"] >= 0.3:
            inactivity_result = _twin_aware_inactivity(
                device_twin, current_hour, inactivity_minutes,
            )
            inactivity_score = inactivity_result["score"]
            reason = inactivity_result["reason"]
            anomaly_type = inactivity_result["anomaly_type"]
        else:
            # Generic inactivity scoring (fallback)
            inactivity_score = min(1.0, 0.5 + (inactivity_minutes / INACTIVITY_THRESHOLD_MINUTES - 1) * 0.25)
            reason = f"No heartbeat for {int(inactivity_minutes)} minutes (threshold: {INACTIVITY_THRESHOLD_MINUTES}min)"
            anomaly_type = "extended_inactivity"

        if inactivity_score < 0.1:
            continue  # Twin says this is expected (e.g. sleep time)

        await session.execute(text("""
            INSERT INTO behavior_anomalies (id, device_id, behavior_score, anomaly_type, reason, is_simulated, created_at)
            VALUES (gen_random_uuid(), :device_id, :score, :type, :reason, false, :now)
        """), {
            "device_id": str(r.device_id), "score": round(inactivity_score, 3),
            "type": anomaly_type, "reason": reason, "now": now,
        })
        anomalies_created += 1

    if anomalies_created > 0:
        logger.info(f"Behavior anomalies detected: {anomalies_created}")


def _apply_twin_context(
    base_score: float,
    twin: dict,
    current_hour: int,
    movement: float,
    interaction: float,
    baseline,
) -> dict:
    """
    Adjust behavior_score using the digital twin's personalized context.

    Boost: Twin expects activity now but metrics are low → amplify score
    Suppress: Twin expects inactivity (sleep) but metrics are slightly off → dampen score
    """
    rhythm = twin.get("rhythm", {})
    hour_data = rhythm.get(str(current_hour))
    expected_active = hour_data["expected_active"] if hour_data else None
    confidence = twin["confidence"]

    adjusted = base_score
    twin_anomaly_type = None
    boost_reason = None

    if expected_active is True:
        # Person SHOULD be active now per their twin
        if interaction < (baseline.avg_interaction_rate * 0.4):
            # Very low interaction during expected active period → significant boost
            boost = 0.25 * min(confidence, 1.0)
            adjusted = min(1.0, base_score + boost)
            twin_anomaly_type = "twin_active_expected"
            boost_reason = f"Twin expects activity at {current_hour:02d}:00 but interaction is very low ({interaction:.0f} vs expected {baseline.avg_interaction_rate:.1f})"
        elif movement < (baseline.avg_movement * 0.3):
            # Very low movement during active period
            boost = 0.15 * min(confidence, 1.0)
            adjusted = min(1.0, base_score + boost)
            twin_anomaly_type = "twin_active_expected"
            boost_reason = f"Twin expects movement at {current_hour:02d}:00 but movement is minimal ({movement:.2f} vs expected {baseline.avg_movement:.2f})"

    elif expected_active is False:
        # Person is expected to be inactive (sleep/rest)
        # Suppress minor deviations — they're normal for this time
        if base_score < 0.5:
            suppression = 0.15 * min(confidence, 1.0)
            adjusted = max(0.0, base_score - suppression)
            boost_reason = f"Twin expects rest at {current_hour:02d}:00 — minor deviation suppressed"
        # But if score is high during sleep time, that could mean distress
        elif base_score >= 0.6:
            boost = 0.1 * min(confidence, 1.0)
            adjusted = min(1.0, base_score + boost)
            twin_anomaly_type = "twin_sleep_disruption"
            boost_reason = f"Significant activity detected during expected rest period ({current_hour:02d}:00)"

    return {
        "adjusted_score": round(adjusted, 3),
        "twin_anomaly_type": twin_anomaly_type,
        "boost_reason": boost_reason,
        "expected_active": expected_active,
        "twin_confidence": confidence,
    }


def _twin_aware_inactivity(twin: dict, current_hour: int, inactivity_minutes: float) -> dict:
    """
    Score inactivity using the twin's personalized context.

    Key insight: If twin says "should be active at 10:00" and person has been
    inactive for 90 minutes → that's much more alarming than the same inactivity
    at 02:00 when the twin expects sleep.
    """
    rhythm = twin.get("rhythm", {})
    hour_data = rhythm.get(str(current_hour))
    expected_active = hour_data["expected_active"] if hour_data else None
    personal_max = twin.get("inactivity_max") or INACTIVITY_THRESHOLD_MINUTES
    confidence = twin["confidence"]

    if expected_active is False:
        # Sleep/rest time — inactivity is expected
        if inactivity_minutes < personal_max * 3:
            # Even extended inactivity during sleep is normal
            return {
                "score": 0.05,
                "reason": f"Inactive for {int(inactivity_minutes)}min during expected rest ({current_hour:02d}:00) — normal per twin",
                "anomaly_type": "expected_inactivity",
            }
        else:
            # Very long inactivity even during sleep → could be concerning
            score = min(1.0, 0.3 + (inactivity_minutes / (personal_max * 4) - 0.5) * 0.3)
            return {
                "score": round(score, 3),
                "reason": f"Extended inactivity ({int(inactivity_minutes)}min) exceeds even sleep expectations (threshold: {int(personal_max * 3)}min)",
                "anomaly_type": "extended_inactivity",
            }

    elif expected_active is True:
        # Should be active but isn't — this is the critical twin insight
        # Score ramps faster than generic: personal_max is their actual limit
        if inactivity_minutes <= personal_max:
            # Within personal tolerance
            ratio = inactivity_minutes / max(personal_max, 1)
            score = 0.3 * ratio
        else:
            # Exceeded personal limit → escalate
            excess_ratio = inactivity_minutes / max(personal_max, 1)
            score = min(1.0, 0.5 + (excess_ratio - 1) * 0.3 * min(confidence, 1.0))

        return {
            "score": round(score, 3),
            "reason": f"Inactive for {int(inactivity_minutes)}min during expected active period ({current_hour:02d}:00). Personal limit: {int(personal_max)}min [TWIN-AWARE]",
            "anomaly_type": "twin_inactivity_exceeded" if inactivity_minutes > personal_max else "twin_active_expected",
        }

    # No twin data for this hour → generic fallback
    generic_score = min(1.0, 0.5 + (inactivity_minutes / INACTIVITY_THRESHOLD_MINUTES - 1) * 0.25)
    return {
        "score": round(generic_score, 3),
        "reason": f"No heartbeat for {int(inactivity_minutes)} minutes (threshold: {INACTIVITY_THRESHOLD_MINUTES}min)",
        "anomaly_type": "extended_inactivity",
    }


def _classify_anomaly(z_mov, z_int, movement, interaction, baseline):
    """Classify the type of behavioral anomaly."""
    if z_int > 2 and interaction < baseline.avg_interaction_rate:
        return "low_interaction"
    if z_mov > 2 and movement < baseline.avg_movement:
        return "movement_drop"
    if z_mov > 2 and movement > baseline.avg_movement:
        return "unusual_movement"
    if z_int > 2 and interaction > baseline.avg_interaction_rate:
        return "hyperactivity"
    return "routine_break"


def _build_reason(anomaly_type, movement, interaction, baseline, twin_context=None):
    """Build human-readable reason string."""
    # If twin provided a specific boost reason, prepend it
    twin_prefix = ""
    if twin_context and twin_context.get("boost_reason"):
        twin_prefix = f"[TWIN] {twin_context['boost_reason']} | "

    reasons = {
        "low_interaction": f"Interaction rate ({interaction:.0f}/30min) significantly below baseline ({baseline.avg_interaction_rate:.1f}/30min)",
        "movement_drop": f"Movement proxy ({movement:.2f}) dropped below baseline ({baseline.avg_movement:.2f})",
        "unusual_movement": f"Movement proxy ({movement:.2f}) unusually high vs baseline ({baseline.avg_movement:.2f})",
        "hyperactivity": f"Interaction rate ({interaction:.0f}/30min) unusually high vs baseline ({baseline.avg_interaction_rate:.1f}/30min)",
        "routine_break": "Multiple behavioral features deviated from expected baseline pattern",
        "twin_active_expected": f"Twin expects activity but metrics are low (movement={movement:.2f}, interaction={interaction:.0f})",
        "twin_sleep_disruption": f"Significant activity during expected rest period (movement={movement:.2f}, interaction={interaction:.0f})",
    }
    base_reason = reasons.get(anomaly_type, "Behavioral deviation detected")
    return f"{twin_prefix}{base_reason}"


def start_behavior_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_behavior_cycle, 'interval', minutes=10,
        id='behavior_ai_cycle',
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
        # Heavy + non-idempotent (writes baselines via EMA).
        # Keep max_instances=1 to avoid double-EMA, but coalesce piled-up
        # ticks and tolerate up to 30s misfires from event-loop stalls.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    _scheduler.start()
    logger.info("Behavior AI scheduler started — polling every 10 min")


def stop_behavior_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
