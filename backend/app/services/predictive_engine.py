# Predictive Safety Engine
# Analyzes 7-day behavioral trends to forecast anomalies before they occur.
# Produces predictive_risks with score, window, confidence, and explanation.
#
# Prediction types:
#   activity_decline    - movement/interaction decreasing over days
#   sleep_disruption    - wake/sleep cycle shifting or destabilizing
#   wandering_risk      - location stability dropping
#   health_decline      - multi-signal deterioration pattern
#
# Runs every 6 hours. Only emits alerts when score > 0.7 AND confidence > 0.6.

import json
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
TREND_WINDOW_DAYS = 7
MIN_DAYS_FOR_PREDICTION = 3
ALERT_SCORE_THRESHOLD = 0.7
ALERT_CONFIDENCE_THRESHOLD = 0.6


async def run_prediction_cycle():
    """Main prediction cycle: extract features → analyze trends → generate predictions."""
    async with async_session() as session:
        try:
            count = await _predict_all_devices(session)
            await session.commit()
            if count > 0:
                logger.info(f"Predictive engine: generated {count} predictions")
        except Exception:
            await session.rollback()
            logger.exception("Predictive engine cycle failed")


async def _predict_all_devices(session: AsyncSession) -> int:
    """Run predictions for all devices with sufficient historical data."""
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=TREND_WINDOW_DAYS)

    # Deactivate old predictions
    await session.execute(text("""
        UPDATE predictive_risks SET is_active = false
        WHERE is_active = true AND created_at < :cutoff
    """), {"cutoff": now - timedelta(hours=12)})

    # Get all devices with telemetry in the trend window
    devices = (await session.execute(text("""
        SELECT DISTINCT d.id AS device_id, d.device_identifier
        FROM devices d
        JOIN telemetries t ON d.id = t.device_id
        WHERE t.created_at >= :lookback AND t.is_simulated = false
        GROUP BY d.id, d.device_identifier
        HAVING COUNT(DISTINCT DATE(t.created_at)) >= :min_days
    """), {"lookback": lookback, "min_days": MIN_DAYS_FOR_PREDICTION})).fetchall()

    predictions_created = 0

    for dev in devices:
        try:
            features = await _extract_features(session, dev.device_id, now, lookback)
            if not features:
                continue

            twin = await _get_twin_context(session, dev.device_id)
            predictions = _analyze_and_predict(features, twin, dev.device_identifier)

            for pred in predictions:
                if pred["score"] >= ALERT_SCORE_THRESHOLD and pred["confidence"] >= ALERT_CONFIDENCE_THRESHOLD:
                    await session.execute(text("""
                        INSERT INTO predictive_risks
                            (id, device_id, prediction_type, prediction_score,
                             prediction_window_hours, confidence, explanation,
                             feature_vector, trend_data, is_active, created_at)
                        VALUES (gen_random_uuid(), :device_id, :type, :score,
                                :window, :confidence, :explanation,
                                CAST(:features AS jsonb), CAST(:trends AS jsonb),
                                true, :now)
                    """), {
                        "device_id": dev.device_id,
                        "type": pred["type"],
                        "score": round(pred["score"], 3),
                        "window": pred["window_hours"],
                        "confidence": round(pred["confidence"], 3),
                        "explanation": pred["explanation"],
                        "features": json.dumps(pred["feature_vector"]),
                        "trends": json.dumps(pred["trend_data"]),
                        "now": now,
                    })
                    predictions_created += 1
        except Exception:
            logger.exception(f"Prediction failed for device {dev.device_id}")

    return predictions_created


async def _extract_features(session: AsyncSession, device_id, now, lookback) -> dict | None:
    """
    Extract time-series features from telemetry over the trend window.
    Returns daily aggregates for movement, interaction, and location indicators.
    """
    # Daily aggregates from telemetry
    daily_rows = (await session.execute(text("""
        SELECT
            DATE(t.created_at) AS day,
            COUNT(*) AS heartbeat_count,
            STDDEV_POP((t.metric_value->>'signal_strength')::float) AS movement_proxy,
            AVG((t.metric_value->>'signal_strength')::float) AS avg_signal,
            MAX(EXTRACT(HOUR FROM t.created_at)) AS last_active_hour,
            MIN(EXTRACT(HOUR FROM t.created_at)) AS first_active_hour,
            COUNT(DISTINCT EXTRACT(HOUR FROM t.created_at)) AS active_hours
        FROM telemetries t
        WHERE t.device_id = :device_id
          AND t.metric_type = 'heartbeat'
          AND t.is_simulated = false
          AND t.created_at >= :lookback
          AND t.created_at <= :now
        GROUP BY DATE(t.created_at)
        ORDER BY DATE(t.created_at)
    """), {"device_id": device_id, "lookback": lookback, "now": now})).fetchall()

    if len(daily_rows) < MIN_DAYS_FOR_PREDICTION:
        return None

    days = []
    for r in daily_rows:
        days.append({
            "day": str(r.day),
            "heartbeat_count": int(r.heartbeat_count),
            "movement_proxy": float(r.movement_proxy or 0),
            "avg_signal": float(r.avg_signal or 0),
            "first_active_hour": int(r.first_active_hour or 0),
            "last_active_hour": int(r.last_active_hour or 0),
            "active_hours": int(r.active_hours or 0),
        })

    # Compute derived features
    movements = [d["movement_proxy"] for d in days]
    interactions = [d["heartbeat_count"] for d in days]
    active_hrs = [d["active_hours"] for d in days]
    wake_times = [d["first_active_hour"] for d in days]

    return {
        "days": days,
        "num_days": len(days),
        "movement_trend_7d": _compute_trend(movements),
        "interaction_trend_7d": _compute_trend(interactions),
        "active_hours_trend": _compute_trend(active_hrs),
        "wake_time_shift": _compute_drift(wake_times),
        "movement_avg": sum(movements) / len(movements) if movements else 0,
        "movement_latest": movements[-1] if movements else 0,
        "interaction_avg": sum(interactions) / len(interactions) if interactions else 0,
        "interaction_latest": interactions[-1] if interactions else 0,
        "activity_variance": _compute_variance(active_hrs),
        "movement_variance": _compute_variance(movements),
    }


async def _get_twin_context(session: AsyncSession, device_id) -> dict | None:
    """Fetch digital twin context for enriching predictions."""
    twin = (await session.execute(text("""
        SELECT wake_hour, sleep_hour, typical_inactivity_max_minutes,
               movement_interval_minutes, confidence_score, profile_summary
        FROM device_digital_twins
        WHERE device_id = :device_id AND confidence_score >= 0.15
    """), {"device_id": device_id})).fetchone()

    if not twin:
        return None

    return {
        "wake_hour": twin.wake_hour,
        "sleep_hour": twin.sleep_hour,
        "inactivity_max": twin.typical_inactivity_max_minutes,
        "movement_interval": twin.movement_interval_minutes,
        "confidence": twin.confidence_score,
        "personality_tag": (twin.profile_summary or {}).get("personality_tag"),
    }


def _analyze_and_predict(features: dict, twin: dict | None, device_identifier: str) -> list:
    """
    Analyze features and generate predictions.
    Uses weighted rule-based scoring (upgradeable to ML later).
    """
    predictions = []

    # 1. Activity Decline Prediction
    pred = _predict_activity_decline(features, twin, device_identifier)
    if pred:
        predictions.append(pred)

    # 2. Sleep Disruption Prediction
    pred = _predict_sleep_disruption(features, twin, device_identifier)
    if pred:
        predictions.append(pred)

    # 3. Wandering Risk Prediction
    pred = _predict_wandering_risk(features, twin, device_identifier)
    if pred:
        predictions.append(pred)

    # 4. Health Decline Prediction (multi-signal)
    pred = _predict_health_decline(features, twin, device_identifier)
    if pred:
        predictions.append(pred)

    return predictions


def _predict_activity_decline(features: dict, twin: dict | None, device_id: str) -> dict | None:
    """
    Detect declining movement/interaction trend → predict inactivity anomaly.
    Key signals: movement_trend_7d < -0.05, interaction_trend_7d < -0.05
    """
    mov_trend = features["movement_trend_7d"]
    int_trend = features["interaction_trend_7d"]
    hrs_trend = features["active_hours_trend"]

    # Score: weighted combination of decline signals
    decline_signals = []
    explanations = []

    if mov_trend < -0.03:
        strength = min(abs(mov_trend) / 0.20, 1.0)  # -20%/day = max
        decline_signals.append(strength * 0.4)
        explanations.append(f"Movement declining {abs(mov_trend)*100:.0f}%/day over {features['num_days']} days")

    if int_trend < -0.03:
        strength = min(abs(int_trend) / 0.20, 1.0)
        decline_signals.append(strength * 0.35)
        explanations.append(f"Interaction rate declining {abs(int_trend)*100:.0f}%/day")

    if hrs_trend < -0.02:
        strength = min(abs(hrs_trend) / 0.15, 1.0)
        decline_signals.append(strength * 0.25)
        explanations.append(f"Active hours shrinking {abs(hrs_trend)*100:.0f}%/day")

    if not decline_signals:
        return None

    score = min(1.0, sum(decline_signals))
    confidence = _compute_prediction_confidence(features, len(decline_signals))

    # Twin boost: if twin says person should be more active
    if twin and twin.get("confidence", 0) >= 0.3:
        score = min(1.0, score * 1.15)  # 15% boost with twin validation
        confidence = min(1.0, confidence * 1.1)

    # Predict window based on decline rate
    avg_decline = abs(mov_trend + int_trend) / 2
    window_hours = max(24, min(168, int(48 / max(avg_decline * 10, 0.1))))

    return {
        "type": "activity_decline",
        "score": score,
        "window_hours": window_hours,
        "confidence": confidence,
        "explanation": ". ".join(explanations),
        "feature_vector": {
            "movement_trend_7d": round(mov_trend, 4),
            "interaction_trend_7d": round(int_trend, 4),
            "active_hours_trend": round(hrs_trend, 4),
            "movement_latest": round(features["movement_latest"], 3),
        },
        "trend_data": {
            "daily_movement": [d["movement_proxy"] for d in features["days"]],
            "daily_interaction": [d["heartbeat_count"] for d in features["days"]],
            "days": [d["day"] for d in features["days"]],
        },
    }


def _predict_sleep_disruption(features: dict, twin: dict | None, device_id: str) -> dict | None:
    """
    Detect wake time drift or activity variance increase → predict sleep disruption.
    """
    wake_shift = features["wake_time_shift"]
    act_variance = features["activity_variance"]

    signals = []
    explanations = []

    if abs(wake_shift) > 0.5:  # > 30 min shift over window
        strength = min(abs(wake_shift) / 3.0, 1.0)  # 3 hours = max
        signals.append(strength * 0.5)
        direction = "later" if wake_shift > 0 else "earlier"
        explanations.append(f"Wake time shifting {abs(wake_shift)*60:.0f} min {direction} over {features['num_days']} days")

    if act_variance > 2.0:  # high daily variance in active hours
        strength = min(act_variance / 6.0, 1.0)
        signals.append(strength * 0.35)
        explanations.append(f"Daily activity pattern becoming unstable (variance: {act_variance:.1f})")

    # Twin context: compare with established wake time
    if twin and twin.get("wake_hour") is not None and abs(wake_shift) > 0.3:
        signals.append(0.15)
        explanations.append(f"Deviating from established wake time ({twin['wake_hour']:02d}:00)")

    if not signals:
        return None

    score = min(1.0, sum(signals))
    confidence = _compute_prediction_confidence(features, len(signals))

    return {
        "type": "sleep_disruption",
        "score": score,
        "window_hours": 72,
        "confidence": confidence,
        "explanation": ". ".join(explanations),
        "feature_vector": {
            "wake_time_shift": round(wake_shift, 3),
            "activity_variance": round(act_variance, 3),
        },
        "trend_data": {
            "daily_wake_hour": [d["first_active_hour"] for d in features["days"]],
            "daily_active_hours": [d["active_hours"] for d in features["days"]],
            "days": [d["day"] for d in features["days"]],
        },
    }


def _predict_wandering_risk(features: dict, twin: dict | None, device_id: str) -> dict | None:
    """
    Detect increasing movement variance with location instability.
    """
    mov_var = features["movement_variance"]
    mov_trend = features["movement_trend_7d"]

    signals = []
    explanations = []

    # High movement variance = erratic patterns
    if mov_var > 1.5:
        strength = min(mov_var / 5.0, 1.0)
        signals.append(strength * 0.5)
        explanations.append(f"Movement pattern becoming erratic (variance: {mov_var:.2f})")

    # Movement increasing while activity hours stable/declining = wandering
    if mov_trend > 0.05 and features["active_hours_trend"] <= 0:
        strength = min(mov_trend / 0.15, 1.0)
        signals.append(strength * 0.35)
        explanations.append(f"Movement increasing ({mov_trend*100:.0f}%/day) while active hours declining")

    if twin and twin.get("movement_interval") and features["movement_latest"] > 0:
        # Check if current movement is way above twin's typical
        ratio = features["movement_latest"] / max(twin["movement_interval"], 0.1)
        if ratio > 2.0:
            signals.append(0.15)
            explanations.append("Movement significantly exceeds personal baseline")

    if not signals:
        return None

    score = min(1.0, sum(signals))
    confidence = _compute_prediction_confidence(features, len(signals))

    return {
        "type": "wandering_risk",
        "score": score,
        "window_hours": 48,
        "confidence": confidence,
        "explanation": ". ".join(explanations),
        "feature_vector": {
            "movement_variance": round(mov_var, 3),
            "movement_trend_7d": round(mov_trend, 4),
            "active_hours_trend": round(features["active_hours_trend"], 4),
        },
        "trend_data": {
            "daily_movement": [d["movement_proxy"] for d in features["days"]],
            "days": [d["day"] for d in features["days"]],
        },
    }


def _predict_health_decline(features: dict, twin: dict | None, device_id: str) -> dict | None:
    """
    Multi-signal health decline: movement dropping + interaction dropping + active hours shrinking.
    Requires at least 2 declining signals to trigger.
    """
    declining = []
    explanations = []

    if features["movement_trend_7d"] < -0.02:
        declining.append("movement")
        explanations.append(f"Movement declining {abs(features['movement_trend_7d'])*100:.0f}%/day")

    if features["interaction_trend_7d"] < -0.02:
        declining.append("interaction")
        explanations.append(f"Interaction declining {abs(features['interaction_trend_7d'])*100:.0f}%/day")

    if features["active_hours_trend"] < -0.01:
        declining.append("active_hours")
        explanations.append("Active hours declining")

    if abs(features["wake_time_shift"]) > 0.5:
        declining.append("sleep_pattern")
        explanations.append("Sleep pattern destabilizing")

    if len(declining) < 2:
        return None

    # Multi-signal score: more signals = higher confidence
    base_score = 0.3 * len(declining)
    avg_decline = (abs(features["movement_trend_7d"]) + abs(features["interaction_trend_7d"])) / 2
    intensity_boost = min(avg_decline / 0.15, 0.4)

    score = min(1.0, base_score + intensity_boost)
    confidence = _compute_prediction_confidence(features, len(declining))
    confidence = min(1.0, confidence * (1 + 0.1 * len(declining)))  # more signals = more confident

    return {
        "type": "health_decline",
        "score": score,
        "window_hours": 72,
        "confidence": confidence,
        "explanation": "Multi-signal deterioration: " + ". ".join(explanations),
        "feature_vector": {
            "declining_signals": declining,
            "signal_count": len(declining),
            "movement_trend_7d": round(features["movement_trend_7d"], 4),
            "interaction_trend_7d": round(features["interaction_trend_7d"], 4),
        },
        "trend_data": {
            "daily_movement": [d["movement_proxy"] for d in features["days"]],
            "daily_interaction": [d["heartbeat_count"] for d in features["days"]],
            "daily_active_hours": [d["active_hours"] for d in features["days"]],
            "days": [d["day"] for d in features["days"]],
        },
    }


# ── Utility Functions ──

def _compute_trend(values: list) -> float:
    """Compute normalized linear trend (slope / mean). Negative = declining."""
    n = len(values)
    if n < 2:
        return 0.0

    mean_val = sum(values) / n
    if mean_val == 0:
        return 0.0

    # Simple linear regression slope
    x_mean = (n - 1) / 2.0
    numerator = sum((i - x_mean) * (v - mean_val) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return 0.0

    slope = numerator / denominator
    # Normalize by mean to get percentage change per day
    return slope / max(abs(mean_val), 0.001)


def _compute_drift(values: list) -> float:
    """Compute drift in hours (positive = shifting later)."""
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / max(len(values) - 1, 1)


def _compute_variance(values: list) -> float:
    """Compute variance of a list of values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def _compute_prediction_confidence(features: dict, signal_count: int) -> float:
    """
    Confidence based on data quality and signal strength.
    More days + more signals = higher confidence.
    """
    days_factor = min(features["num_days"] / 7.0, 1.0)
    signal_factor = min(signal_count / 3.0, 1.0)
    return 0.5 * days_factor + 0.5 * signal_factor


# ── For single-device prediction (used by API) ──

async def predict_for_device(session: AsyncSession, device_id, device_identifier: str) -> list:
    """Run prediction for a single device. Returns list of prediction dicts."""
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=TREND_WINDOW_DAYS)

    features = await _extract_features(session, device_id, now, lookback)
    if not features:
        return []

    twin = await _get_twin_context(session, device_id)
    return _analyze_and_predict(features, twin, device_identifier)


def start_prediction_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_prediction_cycle, 'interval', hours=6,
        id='predictive_engine_cycle',
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    _scheduler.start()
    logger.info("Predictive Safety Engine scheduler started — polling every 6 hours")


def stop_prediction_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
