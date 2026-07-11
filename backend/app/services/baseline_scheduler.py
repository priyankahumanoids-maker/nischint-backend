# Baseline & Anomaly Detection Scheduler
# Runs every 5 minutes:
# 1. Computes rolling baselines for battery_level, battery_slope, and signal_strength per device
# 2. Detects anomalies when battery slope or signal strength falls outside baseline bands
# Production queries EXCLUDE simulated telemetry (is_simulated = false)
import json
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.device_baseline import DeviceBaseline
from app.models.device_anomaly import DeviceAnomaly

logger = logging.getLogger(__name__)

BASELINE_WINDOW_MINUTES = 60
SIGNAL_BASELINE_WINDOW_MINUTES = 1440  # 24 hours for signal
SLOPE_WINDOW_MINUTES = 15
SIGNAL_SUSTAIN_MINUTES = 10
SIGNAL_MIN_HEARTBEATS = 2
BAND_SIGMA_MULTIPLIER = 2.0
MIN_SAMPLES_FOR_BASELINE = 5
MIN_SAMPLES_FOR_SLOPE = 3
MIN_SAMPLES_FOR_SIGNAL = 5

_scheduler: AsyncIOScheduler | None = None

# ── SQL Templates ──

_BATTERY_LEVEL_SQL = """
    SELECT t.device_id,
           AVG((t.metric_value->>'battery_level')::float) AS avg_val,
           STDDEV_POP((t.metric_value->>'battery_level')::float) AS std_val,
           COUNT(*) AS cnt
    FROM telemetries t
    WHERE t.metric_type = 'heartbeat'
      AND t.created_at >= :cutoff
      AND (t.metric_value->>'battery_level') IS NOT NULL
      {sim_filter}
    GROUP BY t.device_id
    HAVING COUNT(*) >= :min_samples
"""

_SLOPE_SQL = """
    WITH ordered AS (
        SELECT t.device_id,
               (t.metric_value->>'battery_level')::float AS bat,
               t.created_at,
               ROW_NUMBER() OVER (PARTITION BY t.device_id ORDER BY t.created_at ASC) AS rn_asc,
               ROW_NUMBER() OVER (PARTITION BY t.device_id ORDER BY t.created_at DESC) AS rn_desc,
               COUNT(*) OVER (PARTITION BY t.device_id) AS cnt
        FROM telemetries t
        WHERE t.metric_type = 'heartbeat'
          AND t.created_at >= :cutoff
          AND (t.metric_value->>'battery_level') IS NOT NULL
          {sim_filter}
    ),
    slopes AS (
        SELECT device_id,
               MAX(CASE WHEN rn_desc = 1 THEN bat END) - MAX(CASE WHEN rn_asc = 1 THEN bat END) AS delta_bat,
               EXTRACT(EPOCH FROM (MAX(CASE WHEN rn_desc = 1 THEN created_at END) - MAX(CASE WHEN rn_asc = 1 THEN created_at END))) / 60.0 AS delta_min,
               MAX(cnt) AS cnt
        FROM ordered
        WHERE cnt >= :min_samples
        GROUP BY device_id
    )
    SELECT device_id,
           CASE WHEN delta_min > 0 THEN delta_bat / delta_min ELSE 0 END AS slope_per_min,
           cnt
    FROM slopes
    WHERE delta_min > 0
"""

_RECENT_SLOPE_SQL = """
    WITH ordered AS (
        SELECT t.device_id,
               (t.metric_value->>'battery_level')::float AS bat,
               t.created_at,
               ROW_NUMBER() OVER (PARTITION BY t.device_id ORDER BY t.created_at ASC) AS rn_asc,
               ROW_NUMBER() OVER (PARTITION BY t.device_id ORDER BY t.created_at DESC) AS rn_desc,
               COUNT(*) OVER (PARTITION BY t.device_id) AS cnt
        FROM telemetries t
        WHERE t.metric_type = 'heartbeat'
          AND t.created_at >= :cutoff
          AND (t.metric_value->>'battery_level') IS NOT NULL
          {sim_filter}
    )
    SELECT device_id,
           MAX(CASE WHEN rn_desc = 1 THEN bat END) AS latest_bat,
           MAX(CASE WHEN rn_asc = 1 THEN bat END) AS earliest_bat,
           MAX(CASE WHEN rn_desc = 1 THEN bat END) - MAX(CASE WHEN rn_asc = 1 THEN bat END) AS delta_bat,
           EXTRACT(EPOCH FROM (MAX(CASE WHEN rn_desc = 1 THEN created_at END) - MAX(CASE WHEN rn_asc = 1 THEN created_at END))) / 60.0 AS delta_min,
           MAX(cnt) AS cnt
    FROM ordered
    WHERE cnt >= :min_samples
    GROUP BY device_id
"""

_SIGNAL_BASELINE_SQL = """
    SELECT t.device_id,
           AVG((t.metric_value->>'signal_strength')::float) AS avg_val,
           STDDEV_POP((t.metric_value->>'signal_strength')::float) AS std_val,
           COUNT(*) AS cnt
    FROM telemetries t
    WHERE t.metric_type = 'heartbeat'
      AND t.created_at >= :cutoff
      AND (t.metric_value->>'signal_strength') IS NOT NULL
      {sim_filter}
    GROUP BY t.device_id
    HAVING COUNT(*) >= :min_samples
"""

_SIGNAL_RECENT_SQL = """
    SELECT t.device_id,
           (t.metric_value->>'signal_strength')::float AS signal_val,
           t.created_at
    FROM telemetries t
    WHERE t.metric_type = 'heartbeat'
      AND t.created_at >= :cutoff
      AND (t.metric_value->>'signal_strength') IS NOT NULL
      {sim_filter}
    ORDER BY t.device_id, t.created_at DESC
"""


# ── Baseline Computation ──

async def _update_baselines(session: AsyncSession, *, simulation_run_id: str | None = None):
    """Compute rolling baselines for battery_level, battery_slope, and signal_strength."""
    bat_cutoff = datetime.now(timezone.utc) - timedelta(minutes=BASELINE_WINDOW_MINUTES)
    sig_cutoff = datetime.now(timezone.utc) - timedelta(minutes=SIGNAL_BASELINE_WINDOW_MINUTES)

    if simulation_run_id:
        sim_filter = "AND t.simulation_run_id = :run_id"
        bat_params = {"cutoff": bat_cutoff, "min_samples": MIN_SAMPLES_FOR_BASELINE, "run_id": simulation_run_id}
        sig_params = {"cutoff": sig_cutoff, "min_samples": MIN_SAMPLES_FOR_SIGNAL, "run_id": simulation_run_id}
    else:
        sim_filter = "AND t.is_simulated = false"
        bat_params = {"cutoff": bat_cutoff, "min_samples": MIN_SAMPLES_FOR_BASELINE}
        sig_params = {"cutoff": sig_cutoff, "min_samples": MIN_SAMPLES_FOR_SIGNAL}

    now = datetime.now(timezone.utc)

    # ── Battery Level Baselines ──
    rows = (await session.execute(
        text(_BATTERY_LEVEL_SQL.format(sim_filter=sim_filter)), bat_params
    )).fetchall()

    for r in rows:
        std = r.std_val or 0
        await session.execute(text("""
            INSERT INTO device_baselines (id, device_id, metric, window_minutes, expected_value, lower_band, upper_band, updated_at)
            VALUES (gen_random_uuid(), :did, 'battery_level', :window, :expected, :lower, :upper, :now)
            ON CONFLICT ON CONSTRAINT uq_device_baseline
            DO UPDATE SET expected_value = :expected, lower_band = :lower, upper_band = :upper,
                          window_minutes = :window, updated_at = :now
        """), {
            "did": r.device_id, "window": BASELINE_WINDOW_MINUTES,
            "expected": round(r.avg_val, 2),
            "lower": round(r.avg_val - BAND_SIGMA_MULTIPLIER * std, 2),
            "upper": round(r.avg_val + BAND_SIGMA_MULTIPLIER * std, 2),
            "now": now,
        })

    # ── Battery Slope Baselines ──
    slope_rows = (await session.execute(
        text(_SLOPE_SQL.format(sim_filter=sim_filter)), bat_params
    )).fetchall()

    if slope_rows:
        slopes = [float(r.slope_per_min) for r in slope_rows]
        n = len(slopes)
        mean_slope = sum(slopes) / n
        if n > 1:
            var = sum((s - mean_slope) ** 2 for s in slopes) / n
            std_slope = var ** 0.5
        else:
            std_slope = abs(mean_slope) * 0.5 if mean_slope != 0 else 0.5

        for r in slope_rows:
            await session.execute(text("""
                INSERT INTO device_baselines (id, device_id, metric, window_minutes, expected_value, lower_band, upper_band, updated_at)
                VALUES (gen_random_uuid(), :did, 'battery_slope', :window, :expected, :lower, :upper, :now)
                ON CONFLICT ON CONSTRAINT uq_device_baseline
                DO UPDATE SET expected_value = :expected, lower_band = :lower, upper_band = :upper,
                              window_minutes = :window, updated_at = :now
            """), {
                "did": r.device_id, "window": BASELINE_WINDOW_MINUTES,
                "expected": round(float(r.slope_per_min), 4),
                "lower": round(mean_slope - BAND_SIGMA_MULTIPLIER * std_slope, 4),
                "upper": round(mean_slope + BAND_SIGMA_MULTIPLIER * std_slope, 4),
                "now": now,
            })

    # ── Signal Strength Baselines ──
    sig_rows = (await session.execute(
        text(_SIGNAL_BASELINE_SQL.format(sim_filter=sim_filter)), sig_params
    )).fetchall()

    for r in sig_rows:
        std = r.std_val or 0
        await session.execute(text("""
            INSERT INTO device_baselines (id, device_id, metric, window_minutes, expected_value, lower_band, upper_band, updated_at)
            VALUES (gen_random_uuid(), :did, 'signal_strength', :window, :expected, :lower, :upper, :now)
            ON CONFLICT ON CONSTRAINT uq_device_baseline
            DO UPDATE SET expected_value = :expected, lower_band = :lower, upper_band = :upper,
                          window_minutes = :window, updated_at = :now
        """), {
            "did": r.device_id, "window": SIGNAL_BASELINE_WINDOW_MINUTES,
            "expected": round(r.avg_val, 2),
            "lower": round(r.avg_val - BAND_SIGMA_MULTIPLIER * std, 2),
            "upper": round(r.avg_val + BAND_SIGMA_MULTIPLIER * std, 2),
            "now": now,
        })

    await session.commit()
    return len(rows), len(slope_rows), len(sig_rows)


# ── Battery Slope Anomaly Detection ──

async def _detect_battery_slope_anomalies(
    session: AsyncSession,
    *,
    simulation_run_id: str | None = None,
):
    """Detect slope anomalies. If simulation_run_id set, scopes to that run."""
    slope_cutoff = datetime.now(timezone.utc) - timedelta(minutes=SLOPE_WINDOW_MINUTES)
    anomaly_cooldown = datetime.now(timezone.utc) - timedelta(minutes=10)

    if simulation_run_id:
        sim_filter = "AND t.simulation_run_id = :run_id"
        params = {"cutoff": slope_cutoff, "min_samples": MIN_SAMPLES_FOR_SLOPE, "run_id": simulation_run_id}
    else:
        sim_filter = "AND t.is_simulated = false"
        params = {"cutoff": slope_cutoff, "min_samples": MIN_SAMPLES_FOR_SLOPE}

    recent_rows = (await session.execute(
        text(_RECENT_SLOPE_SQL.format(sim_filter=sim_filter)), params
    )).fetchall()

    anomalies_created = 0
    now = datetime.now(timezone.utc)
    scores = []

    for r in recent_rows:
        if not r.delta_min or r.delta_min <= 0:
            continue
        current_slope = float(r.delta_bat) / float(r.delta_min)

        baseline = (await session.execute(text("""
            SELECT expected_value, lower_band, upper_band
            FROM device_baselines
            WHERE device_id = :did AND metric = 'battery_slope'
        """), {"did": r.device_id})).fetchone()

        if not baseline:
            continue

        if baseline.lower_band <= current_slope <= baseline.upper_band:
            continue

        if not simulation_run_id:
            existing = (await session.execute(text("""
                SELECT 1 FROM device_anomalies
                WHERE device_id = :did AND metric = 'battery_slope' AND created_at >= :cooldown
                  AND is_simulated = false
                LIMIT 1
            """), {"did": r.device_id, "cooldown": anomaly_cooldown})).fetchone()
            if existing:
                continue

        band_width = (baseline.upper_band - baseline.lower_band) / 2
        if band_width > 0:
            deviation = abs(current_slope - baseline.expected_value)
            score = round(min(deviation / band_width * 50, 100), 1)
        else:
            score = 75.0

        reason = {
            "type": "battery_drop_rate_anomaly",
            "current_slope": round(current_slope, 4),
            "expected_slope": baseline.expected_value,
            "lower_band": baseline.lower_band,
            "upper_band": baseline.upper_band,
            "latest_battery": r.latest_bat,
            "earliest_battery": r.earliest_bat,
            "window_minutes": SLOPE_WINDOW_MINUTES,
        }

        is_sim = simulation_run_id is not None
        await session.execute(text("""
            INSERT INTO device_anomalies (id, device_id, metric, score, reason_json, window_start, created_at, is_simulated, simulation_run_id)
            VALUES (gen_random_uuid(), :did, 'battery_slope', :score, CAST(:reason AS jsonb), :window_start, :now, :is_sim, :run_id)
        """), {
            "did": r.device_id, "score": score,
            "reason": json.dumps(reason),
            "window_start": slope_cutoff, "now": now,
            "is_sim": is_sim, "run_id": simulation_run_id,
        })
        anomalies_created += 1
        scores.append({"device_id": str(r.device_id), "score": score})

    await session.commit()
    if simulation_run_id:
        return anomalies_created, scores
    return anomalies_created


# ── Signal Strength Anomaly Detection (Sustained Deviation) ──

async def _detect_signal_anomalies(
    session: AsyncSession,
    *,
    simulation_run_id: str | None = None,
):
    """
    Detect sustained signal strength degradation.
    A device is flagged if ALL signal readings in the last sustain_minutes are below the lower_band.
    Score = deviation_sigma × 25, clamped 0–100.
    """
    sustain_cutoff = datetime.now(timezone.utc) - timedelta(minutes=SIGNAL_SUSTAIN_MINUTES)
    anomaly_cooldown = datetime.now(timezone.utc) - timedelta(minutes=10)

    if simulation_run_id:
        sim_filter = "AND t.simulation_run_id = :run_id"
        params = {"cutoff": sustain_cutoff, "run_id": simulation_run_id}
    else:
        sim_filter = "AND t.is_simulated = false"
        params = {"cutoff": sustain_cutoff}

    # Fetch recent signal readings per device
    recent_rows = (await session.execute(
        text(_SIGNAL_RECENT_SQL.format(sim_filter=sim_filter)), params
    )).fetchall()

    # Group by device_id
    device_readings: dict = {}
    for r in recent_rows:
        did = str(r.device_id)
        if did not in device_readings:
            device_readings[did] = {"device_id": r.device_id, "readings": []}
        device_readings[did]["readings"].append(float(r.signal_val))

    anomalies_created = 0
    now = datetime.now(timezone.utc)
    scores = []

    for did, data in device_readings.items():
        readings = data["readings"]

        # Must have enough heartbeats
        if len(readings) < SIGNAL_MIN_HEARTBEATS:
            continue

        # Fetch baseline for this device
        baseline = (await session.execute(text("""
            SELECT expected_value, lower_band, upper_band
            FROM device_baselines
            WHERE device_id = :did AND metric = 'signal_strength'
        """), {"did": data["device_id"]})).fetchone()

        if not baseline:
            continue

        # Skip if stddev was 0 (no variance in baseline → can't detect anomaly)
        std_val = (baseline.upper_band - baseline.expected_value) / BAND_SIGMA_MULTIPLIER
        if std_val <= 0:
            continue

        # Sustained deviation: ALL readings must be below lower_band
        if not all(r < baseline.lower_band for r in readings):
            continue

        # Cooldown check
        if not simulation_run_id:
            existing = (await session.execute(text("""
                SELECT 1 FROM device_anomalies
                WHERE device_id = :did AND metric = 'signal_strength' AND created_at >= :cooldown
                  AND is_simulated = false
                LIMIT 1
            """), {"did": data["device_id"], "cooldown": anomaly_cooldown})).fetchone()
            if existing:
                continue

        # Compute score: deviation_sigma × 25, clamped 0–100
        observed_mean = sum(readings) / len(readings)
        deviation_sigma = abs(baseline.lower_band - observed_mean) / std_val
        score = round(min(deviation_sigma * 25, 100), 1)

        reason = {
            "type": "signal_strength_degradation",
            "expected_mean": baseline.expected_value,
            "lower_band": baseline.lower_band,
            "upper_band": baseline.upper_band,
            "observed_mean": round(observed_mean, 2),
            "sustain_minutes": SIGNAL_SUSTAIN_MINUTES,
            "sigma_deviation": round(deviation_sigma, 2),
            "readings_count": len(readings),
        }

        is_sim = simulation_run_id is not None
        await session.execute(text("""
            INSERT INTO device_anomalies (id, device_id, metric, score, reason_json, window_start, created_at, is_simulated, simulation_run_id)
            VALUES (gen_random_uuid(), :did, 'signal_strength', :score, CAST(:reason AS jsonb), :window_start, :now, :is_sim, :run_id)
        """), {
            "did": data["device_id"], "score": score,
            "reason": json.dumps(reason),
            "window_start": sustain_cutoff, "now": now,
            "is_sim": is_sim, "run_id": simulation_run_id,
        })
        anomalies_created += 1
        scores.append({"device_id": did, "score": score})

    await session.commit()
    if simulation_run_id:
        return anomalies_created, scores
    return anomalies_created


# ── Multi-Metric Combined Anomaly Detection ──

async def _detect_combined_anomalies(
    session: AsyncSession,
    *,
    simulation_run_id: str | None = None,
):
    """
    Compute combined anomaly score from active battery + signal + behavior anomalies.
    Layer 1: Weighted combined score = battery × w_bat + signal × w_sig + behavior × w_beh
    Layer 2: Correlation bonus when 2+ metrics active simultaneously
    Layer 3: Create multi_metric anomaly if combined_score > trigger_threshold

    Does NOT suppress individual anomalies. Only evaluates devices with >= 1 active anomaly.
    """
    anomaly_cooldown = datetime.now(timezone.utc) - timedelta(minutes=10)
    lookback = datetime.now(timezone.utc) - timedelta(minutes=15)
    behavior_lookback = datetime.now(timezone.utc) - timedelta(minutes=30)

    # Load config from device_health_rule_configs
    config_row = (await session.execute(text("""
        SELECT enabled, threshold_json FROM device_health_rule_configs
        WHERE rule_name = 'combined_anomaly'
    """))).fetchone()

    if not config_row or not config_row.enabled:
        return 0 if not simulation_run_id else (0, [])

    cfg = config_row.threshold_json
    w_bat = cfg.get("weight_battery", 0.5)
    w_sig = cfg.get("weight_signal", 0.3)
    w_beh = cfg.get("weight_behavior", 0.2)
    threshold = cfg.get("trigger_threshold", 60)
    bonus = cfg.get("correlation_bonus", 10)

    # Fetch recent battery_slope and signal_strength anomalies per device
    if simulation_run_id:
        sim_filter = "AND da.simulation_run_id = :run_id"
        params = {"lookback": lookback, "run_id": simulation_run_id}
    else:
        sim_filter = "AND da.is_simulated = false"
        params = {"lookback": lookback}

    anomaly_rows = (await session.execute(text("""
        SELECT da.device_id, d.device_identifier,
               da.metric, da.score, da.created_at
        FROM device_anomalies da
        JOIN devices d ON da.device_id = d.id
        WHERE da.created_at >= :lookback
          AND da.metric IN ('battery_slope', 'signal_strength')
          {sim_filter}
        ORDER BY da.device_id, da.metric, da.created_at DESC
    """.format(sim_filter=sim_filter)), params)).fetchall()

    # Group by device: pick latest score per metric
    device_scores: dict = {}
    for r in anomaly_rows:
        did = str(r.device_id)
        if did not in device_scores:
            device_scores[did] = {
                "device_id": r.device_id,
                "device_identifier": r.device_identifier,
                "battery_score": None,
                "signal_score": None,
                "behavior_score": None,
            }
        entry = device_scores[did]
        if r.metric == "battery_slope" and entry["battery_score"] is None:
            entry["battery_score"] = float(r.score)
        elif r.metric == "signal_strength" and entry["signal_score"] is None:
            entry["signal_score"] = float(r.score)

    # Fetch recent behavior anomalies per device (behavior_score is 0-1, normalize to 0-100)
    if simulation_run_id:
        beh_sim_filter = "AND ba.is_simulated = true"
        beh_params = {"beh_lookback": behavior_lookback}
    else:
        beh_sim_filter = "AND ba.is_simulated = false"
        beh_params = {"beh_lookback": behavior_lookback}

    behavior_rows = (await session.execute(text("""
        SELECT ba.device_id, d.device_identifier,
               ba.behavior_score, ba.anomaly_type, ba.created_at
        FROM behavior_anomalies ba
        JOIN devices d ON ba.device_id = d.id
        WHERE ba.created_at >= :beh_lookback
          {beh_sim_filter}
        ORDER BY ba.device_id, ba.created_at DESC
    """.format(beh_sim_filter=beh_sim_filter)), beh_params)).fetchall()

    # Merge behavior scores into device_scores (pick latest per device)
    for r in behavior_rows:
        did = str(r.device_id)
        if did not in device_scores:
            device_scores[did] = {
                "device_id": r.device_id,
                "device_identifier": r.device_identifier,
                "battery_score": None,
                "signal_score": None,
                "behavior_score": None,
            }
        entry = device_scores[did]
        if entry["behavior_score"] is None:
            # Normalize 0-1 → 0-100
            entry["behavior_score"] = round(float(r.behavior_score) * 100, 1)

    anomalies_created = 0
    now = datetime.now(timezone.utc)
    scores = []

    for did, data in device_scores.items():
        bat = data["battery_score"] or 0.0
        sig = data["signal_score"] or 0.0
        beh = data["behavior_score"] or 0.0

        # Must have at least 1 active anomaly
        if bat == 0.0 and sig == 0.0 and beh == 0.0:
            continue

        # Layer 1: Weighted combined score
        combined = bat * w_bat + sig * w_sig + beh * w_beh

        # Layer 2: Correlation bonus — awarded when 2+ metrics are active
        active_count = sum(1 for v in [bat, sig, beh] if v > 0)
        correlation_flag = active_count >= 2
        if correlation_flag:
            combined += bonus

        combined = round(min(combined, 100.0), 1)

        # Layer 3: Threshold check
        if combined <= threshold:
            continue

        # Cooldown check
        if not simulation_run_id:
            existing = (await session.execute(text("""
                SELECT 1 FROM device_anomalies
                WHERE device_id = :did AND metric = 'multi_metric' AND created_at >= :cooldown
                  AND is_simulated = false
                LIMIT 1
            """), {"did": data["device_id"], "cooldown": anomaly_cooldown})).fetchone()
            if existing:
                continue

        reason = {
            "type": "multi_metric_anomaly",
            "battery_score": bat,
            "signal_score": sig,
            "behavior_score": beh,
            "combined_score": combined,
            "weights": {"battery": w_bat, "signal": w_sig, "behavior": w_beh},
            "correlation_flag": correlation_flag,
            "correlation_bonus": bonus if correlation_flag else 0,
            "active_metrics": active_count,
            "trigger_threshold": threshold,
        }

        is_sim = simulation_run_id is not None
        await session.execute(text("""
            INSERT INTO device_anomalies (id, device_id, metric, score, reason_json, window_start, created_at, is_simulated, simulation_run_id)
            VALUES (gen_random_uuid(), :did, 'multi_metric', :score, CAST(:reason AS jsonb), :window_start, :now, :is_sim, :run_id)
        """), {
            "did": data["device_id"], "score": combined,
            "reason": json.dumps(reason),
            "window_start": lookback, "now": now,
            "is_sim": is_sim, "run_id": simulation_run_id,
        })
        anomalies_created += 1
        scores.append({
            "device_id": did,
            "device_identifier": data["device_identifier"],
            "score": combined,
            "battery_score": bat,
            "signal_score": sig,
            "behavior_score": beh,
            "correlation": correlation_flag,
        })

    await session.commit()
    if simulation_run_id:
        return anomalies_created, scores
    return anomalies_created


# ── Multi-Metric Instability Escalation (Gate 2 + Gate 3) ──

_TIER_SEVERITY_MAP = {
    "L1": "medium",
    "L2": "high",
    "L3": "critical",
}


def _map_score_to_tier(score: float, escalation_tiers: dict) -> str | None:
    """
    Map an anomaly score to an escalation tier using the configurable tier ranges.
    escalation_tiers format: {"60-75": "L1", "75-90": "L2", "90-100": "L3"}
    """
    for range_str, tier in escalation_tiers.items():
        parts = range_str.split("-")
        if len(parts) != 2:
            continue
        try:
            lo, hi = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if lo <= score < hi:
            return tier
        # Inclusive upper bound for the highest tier (score == 100)
        if score == hi and hi == 100:
            return tier
    return None


async def _evaluate_instability_escalation(session: AsyncSession):
    """
    Gate 2 + Gate 3 of the 3-Gate Escalation Model.

    After multi_metric anomalies are detected (Gate 1), this function checks:
    - Gate 2: Has the anomaly persisted >= persistence_minutes?
    - Gate 3: Map score tier → severity → create device_instability incident

    CRITICAL SAFETY: Only considers is_simulated = false anomalies.
    """
    # Load config
    config_row = (await session.execute(text("""
        SELECT enabled, threshold_json, cooldown_minutes FROM device_health_rule_configs
        WHERE rule_name = 'combined_anomaly'
    """))).fetchone()

    if not config_row or not config_row.enabled:
        return 0

    cfg = config_row.threshold_json
    persistence_minutes = cfg.get("persistence_minutes", 15)
    escalation_tiers = cfg.get("escalation_tiers", {"60-75": "L1", "75-90": "L2", "90-100": "L3"})
    instability_cooldown = cfg.get("instability_cooldown_minutes", 30)

    now = datetime.now(timezone.utc)
    # Look back far enough to find the first anomaly in the persistence window
    lookback = now - timedelta(minutes=persistence_minutes * 3)

    # Find devices with persistent multi_metric anomalies (production only)
    persistence_rows = (await session.execute(text("""
        SELECT device_id,
               MIN(created_at) AS first_detected_at,
               MAX(created_at) AS last_seen_at,
               MAX(score) AS max_score,
               COUNT(*) AS anomaly_count
        FROM device_anomalies
        WHERE metric = 'multi_metric'
          AND is_simulated = false
          AND created_at >= :lookback
        GROUP BY device_id
        HAVING COUNT(*) >= 2
    """), {"lookback": lookback})).fetchall()

    if not persistence_rows:
        return 0

    incidents_created = 0

    for row in persistence_rows:
        # Gate 2: Check persistence duration
        persistence_duration = (now - row.first_detected_at).total_seconds() / 60.0
        if persistence_duration < persistence_minutes:
            continue

        # Gate 3: Map score to tier
        tier = _map_score_to_tier(row.max_score, escalation_tiers)
        if not tier:
            continue

        severity = _TIER_SEVERITY_MAP.get(tier, "medium")

        # Guardrail: No open device_instability incident for this device
        from sqlalchemy import select as sa_select, and_
        from app.models.incident import Incident
        existing_open = (await session.execute(
            sa_select(Incident).where(and_(
                Incident.device_id == row.device_id,
                Incident.incident_type == "device_instability",
                Incident.status == "open",
            ))
        )).scalar_one_or_none()
        if existing_open:
            # Audit: blocked by existing open incident
            from app.services.incident_events import log_event as _log_evt
            await _log_evt(session, existing_open.id, "device_instability_escalation_blocked", metadata={
                "reason": "open_incident_exists",
                "blocked_score": row.max_score,
                "blocked_tier": _map_score_to_tier(row.max_score, escalation_tiers),
            })
            continue

        # Guardrail: Cooldown — no recently resolved instability incident
        cooldown_cutoff = now - timedelta(minutes=instability_cooldown)
        recently_resolved = (await session.execute(
            sa_select(Incident).where(and_(
                Incident.device_id == row.device_id,
                Incident.incident_type == "device_instability",
                Incident.status == "resolved",
                Incident.resolved_at > cooldown_cutoff,
            ))
        )).scalar_one_or_none()
        if recently_resolved:
            # Audit: blocked by cooldown
            from app.services.incident_events import log_event as _log_evt
            await _log_evt(session, recently_resolved.id, "device_instability_escalation_blocked", metadata={
                "reason": "cooldown",
                "blocked_score": row.max_score,
                "cooldown_minutes_remaining": round(instability_cooldown - (now - recently_resolved.resolved_at).total_seconds() / 60.0, 1),
            })
            continue

        # Resolve device → senior mapping
        device_row = (await session.execute(text("""
            SELECT d.id, d.senior_id, d.device_identifier
            FROM devices d WHERE d.id = :did
        """), {"did": row.device_id})).fetchone()
        if not device_row:
            continue

        # Create device_instability incident
        from app.services.device_health_scheduler import _create_health_incident
        await _create_health_incident(
            session,
            device_id=device_row.id,
            senior_id=device_row.senior_id,
            incident_type="device_instability",
            severity=severity,
            event_type="device_instability_detected",
            metadata={
                "device_identifier": device_row.device_identifier,
                "source": "multi_metric",
                "max_score": row.max_score,
                "tier": tier,
                "persistence_minutes_actual": round(persistence_duration, 1),
                "persistence_minutes_threshold": persistence_minutes,
                "anomaly_count": row.anomaly_count,
                "first_detected_at": row.first_detected_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
            },
        )
        incidents_created += 1
        logger.warning(
            f">>> DEVICE INSTABILITY: {device_row.device_identifier} "
            f"(score={row.max_score}, tier={tier}, severity={severity}, "
            f"persistence={round(persistence_duration, 1)}min)"
        )

    if incidents_created:
        await session.commit()

    return incidents_created


# ── Instability Recovery (RECOVERING → RESOLVED) ──

async def _evaluate_instability_recovery(session: AsyncSession):
    """
    Auto-resolve open device_instability incidents when:
    - Case A: No multi_metric anomaly in last recovery_minutes
    - Case B: Latest score < (trigger_threshold - recovery_buffer) for >= min_clear_cycles

    Uses hysteresis to prevent flapping around the trigger threshold.
    CRITICAL: Only considers is_simulated = false anomalies.
    """
    # Load config
    config_row = (await session.execute(text("""
        SELECT enabled, threshold_json FROM device_health_rule_configs
        WHERE rule_name = 'combined_anomaly'
    """))).fetchone()

    if not config_row or not config_row.enabled:
        return 0

    cfg = config_row.threshold_json
    trigger_threshold = cfg.get("trigger_threshold", 60)
    recovery_minutes = cfg.get("recovery_minutes", 15)
    recovery_buffer = cfg.get("recovery_buffer", 5)
    min_clear_cycles = cfg.get("min_clear_cycles", 2)
    recovery_score_ceiling = trigger_threshold - recovery_buffer  # e.g. 60 - 5 = 55

    now = datetime.now(timezone.utc)

    # Find all open device_instability incidents
    from sqlalchemy import select as sa_select, and_
    from app.models.incident import Incident
    from app.models.senior import Senior

    open_incidents = (await session.execute(
        sa_select(Incident).where(and_(
            Incident.incident_type == "device_instability",
            Incident.status == "open",
        ))
    )).scalars().all()

    if not open_incidents:
        return 0

    resolved_count = 0

    for inc in open_incidents:
        device_id = inc.device_id

        # Fetch recent multi_metric anomalies for this device (production only)
        recent_anomalies = (await session.execute(text("""
            SELECT score, created_at
            FROM device_anomalies
            WHERE device_id = :did
              AND metric = 'multi_metric'
              AND is_simulated = false
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"did": device_id, "limit": max(min_clear_cycles + 1, 5)})).fetchall()

        should_resolve = False
        resolution_reason = {}

        if not recent_anomalies:
            # Case A: No anomalies at all → resolve
            should_resolve = True
            resolution_reason = {
                "case": "A",
                "reason": "no_multi_metric_anomalies_found",
                "recovery_minutes_config": recovery_minutes,
            }
        else:
            latest = recent_anomalies[0]
            latest_age_minutes = (now - latest.created_at).total_seconds() / 60.0

            if latest_age_minutes >= recovery_minutes:
                # Case A: No anomaly in recovery window → resolve
                should_resolve = True
                resolution_reason = {
                    "case": "A",
                    "reason": "no_anomaly_in_recovery_window",
                    "clear_duration_minutes": round(latest_age_minutes, 1),
                    "recovery_minutes_config": recovery_minutes,
                    "last_anomaly_score": latest.score,
                }
            else:
                # Case B: Check if recent scores are below hysteresis ceiling
                clear_cycles = 0
                for anom in recent_anomalies:
                    if anom.score < recovery_score_ceiling:
                        clear_cycles += 1
                    else:
                        break  # Consecutive clear cycles from most recent

                if clear_cycles >= min_clear_cycles:
                    should_resolve = True
                    resolution_reason = {
                        "case": "B",
                        "reason": "score_below_hysteresis_for_min_cycles",
                        "clear_cycles": clear_cycles,
                        "min_clear_cycles_config": min_clear_cycles,
                        "recovery_score_ceiling": recovery_score_ceiling,
                        "trigger_threshold": trigger_threshold,
                        "recovery_buffer": recovery_buffer,
                        "last_anomaly_score": latest.score,
                    }

        if not should_resolve:
            continue

        # Resolve the incident
        inc.status = "resolved"
        inc.resolved_at = datetime.now(timezone.utc)
        await session.flush()

        # Audit event
        from app.services.incident_events import log_event
        await log_event(session, inc.id, "device_instability_recovered", metadata=resolution_reason)

        # SSE broadcast
        senior = (await session.execute(
            sa_select(Senior).where(Senior.id == inc.senior_id)
        )).scalar_one_or_none()
        if senior:
            from app.services.event_broadcaster import broadcaster, serialize_for_sse
            data = serialize_for_sse({
                "id": inc.id, "senior_id": inc.senior_id,
                "device_id": inc.device_id, "incident_type": inc.incident_type,
                "severity": inc.severity, "status": inc.status,
                "resolved_at": inc.resolved_at, "created_at": inc.created_at,
            })
            await broadcaster.broadcast_incident_updated(str(senior.guardian_id), data)

        resolved_count += 1

        # Get device identifier for logging
        dev_row = (await session.execute(text(
            "SELECT device_identifier FROM devices WHERE id = :did"
        ), {"did": device_id})).fetchone()
        dev_name = dev_row.device_identifier if dev_row else str(device_id)

        logger.info(
            f">>> INSTABILITY RECOVERED: {dev_name} "
            f"(case={resolution_reason.get('case')}, "
            f"reason={resolution_reason.get('reason')})"
        )

    if resolved_count:
        await session.commit()

    return resolved_count


async def run_baseline_and_anomaly_cycle():
    """Main scheduler entry point — production only (excludes simulated data)."""
    async with async_session() as session:
        try:
            bat_count, slope_count, sig_count = await _update_baselines(session)
            logger.info(f"Baselines updated: {bat_count} battery_level, {slope_count} battery_slope, {sig_count} signal_strength")
        except Exception:
            logger.exception("Baseline update failed")

    async with async_session() as session:
        try:
            bat_anomalies = await _detect_battery_slope_anomalies(session)
            if bat_anomalies > 0:
                logger.info(f"Battery slope anomalies detected: {bat_anomalies}")
        except Exception:
            logger.exception("Battery anomaly detection failed")

    async with async_session() as session:
        try:
            sig_anomalies = await _detect_signal_anomalies(session)
            if sig_anomalies > 0:
                logger.info(f"Signal strength anomalies detected: {sig_anomalies}")
        except Exception:
            logger.exception("Signal anomaly detection failed")

    async with async_session() as session:
        try:
            combined_anomalies = await _detect_combined_anomalies(session)
            if combined_anomalies > 0:
                logger.info(f"Multi-metric combined anomalies detected: {combined_anomalies}")
        except Exception:
            logger.exception("Combined anomaly detection failed")

    # Gate 2 + Gate 3: Evaluate instability escalation (production only)
    async with async_session() as session:
        try:
            instability_incidents = await _evaluate_instability_escalation(session)
            if instability_incidents > 0:
                logger.info(f"Device instability incidents created: {instability_incidents}")
        except Exception:
            logger.exception("Instability escalation evaluation failed")

    # Recovery: Auto-resolve device_instability when anomaly clears
    async with async_session() as session:
        try:
            recovered = await _evaluate_instability_recovery(session)
            if recovered > 0:
                logger.info(f"Device instability incidents auto-resolved: {recovered}")
        except Exception:
            logger.exception("Instability recovery evaluation failed")


def start_baseline_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_baseline_and_anomaly_cycle, 'interval', minutes=5, id='baseline_anomaly_cycle',
                       next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30))
    # AI Learning Loop: retrain risk model daily at midnight UTC
    _scheduler.add_job(_retrain_risk_model, 'cron', hour=0, minute=0, id='risk_model_retrain')

    # NISCH-008 retention sweeper — daily at 03:00 IST (= 21:30 UTC).
    # Deletes chunks where expires_at <= now() + the underlying object
    # (local file in stub mode, S3 object in real mode). Cascade FK
    # nukes the audit rows as a side effect.
    from app.services.emergency_stream_retention import (
        run_emergency_stream_retention_sweep,
    )
    _scheduler.add_job(
        run_emergency_stream_retention_sweep,
        'cron', hour=21, minute=30,
        id='nisch008_retention_sweep',
    )

    # DPDP-01 erasure scheduler — daily at 02:00 UTC. Hard-deletes
    # pending erasure_requests whose 30-day grace window has expired.
    # Idempotent: pending requests stay pending until their deadline;
    # a failed run just retries next day. Audit rows survive (ON DELETE
    # SET NULL on user_id).
    _scheduler.add_job(
        _run_due_erasures,
        'cron', hour=2, minute=0,
        id='dpdp01_erasure_sweep',
    )

    _scheduler.start()
    logger.info("Baseline & Anomaly scheduler started — polling every 5 min")
    logger.info("Risk model retrain scheduled — daily at 00:00 UTC")
    logger.info("[NISCH-008-SWEEP] retention sweep scheduled — daily at 21:30 UTC (03:00 IST)")
    logger.info("[DPDP-01-SWEEP] erasure sweep scheduled — daily at 02:00 UTC")


async def _run_due_erasures():
    """Scheduled hard-delete of due DPDP erasure requests."""
    try:
        from app.services.erasure_service import run_due_erasures

        async with async_session() as session:
            completed = await run_due_erasures(session)
            await session.commit()
            if completed:
                logger.info(f"[DPDP-01-SWEEP] completed {completed} erasure(s)")
    except Exception as e:
        logger.error(f"[DPDP-01-SWEEP] failed: {e}")


async def _retrain_risk_model():
    """Scheduled retrain of the AI risk prediction model."""
    try:
        from app.core.database import async_session
        from app.services.feature_store import extract_all_training_data
        from app.services.risk_model import train_model

        async with async_session() as session:
            data = await extract_all_training_data(session)
            if data and len(data) >= 20:
                meta = train_model(data)
                logger.info(f"Risk model retrained: {meta.get('version', 'unknown')}, {len(data)} samples")
            else:
                logger.info(f"Risk model retrain skipped — only {len(data) if data else 0} samples")
    except Exception as e:
        logger.error(f"Risk model retrain failed: {e}")


def stop_baseline_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
