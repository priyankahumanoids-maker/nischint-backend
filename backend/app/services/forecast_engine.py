# AI Risk Forecast Timeline Engine
# Generates 24-hour risk forecasts for devices using 6 time buckets.
# Aggregates: predictive signals, digital twin rhythm, telemetry trends, recent incidents.
#
# Bucket strategy:
#   early_morning  06-09
#   morning        09-12
#   afternoon      12-15
#   evening        15-18
#   night          18-21
#   late_night     21-24
#
# Scoring: risk_score = predictive_weight(0.5) + twin_weight(0.3) + trend_weight(0.2)

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

BUCKETS = [
    {"name": "early_morning", "label": "Early Morning", "start_hour": 6, "end_hour": 9},
    {"name": "morning", "label": "Morning", "start_hour": 9, "end_hour": 12},
    {"name": "afternoon", "label": "Afternoon", "start_hour": 12, "end_hour": 15},
    {"name": "evening", "label": "Evening", "start_hour": 15, "end_hour": 18},
    {"name": "night", "label": "Night", "start_hour": 18, "end_hour": 21},
    {"name": "late_night", "label": "Late Night", "start_hour": 21, "end_hour": 24},
]

# Risk classification thresholds
RISK_LOW = 0.3
RISK_MEDIUM = 0.6

# Scoring weights
W_PREDICTIVE = 0.5
W_TWIN = 0.3
W_TREND = 0.2


async def generate_forecast(session: AsyncSession, device_id: str) -> dict | None:
    """
    Generate a 24-hour risk forecast for a device.
    Returns forecast with 6 time buckets, each with risk_score, risk_level, and reason.
    """
    # 1. Fetch all data sources in parallel-ish
    twin = await _fetch_twin(session, device_id)
    predictions = await _fetch_predictions(session, device_id)
    trends = await _fetch_trends(session, device_id)
    recent_incidents = await _fetch_recent_incidents(session, device_id)

    # Check device exists
    device = (await session.execute(text(
        "SELECT device_identifier FROM devices WHERE id = :did"
    ), {"did": device_id})).fetchone()
    if not device:
        return None

    now = datetime.now(timezone.utc)

    # 2. Score each bucket
    buckets = []
    for bucket in BUCKETS:
        score, reasons = _score_bucket(
            bucket, twin, predictions, trends, recent_incidents, now
        )
        risk_level = _classify_risk(score)
        buckets.append({
            "bucket": bucket["name"],
            "label": bucket["label"],
            "start_hour": bucket["start_hour"],
            "end_hour": bucket["end_hour"],
            "risk_score": round(score, 3),
            "risk_level": risk_level,
            "reason": "; ".join(reasons) if reasons else "normal activity expected",
        })

    # 3. Compute summary
    max_bucket = max(buckets, key=lambda b: b["risk_score"])
    high_count = sum(1 for b in buckets if b["risk_level"] == "HIGH")
    medium_count = sum(1 for b in buckets if b["risk_level"] == "MEDIUM")

    return {
        "device_id": str(device_id),
        "device_identifier": device.device_identifier,
        "forecast_window_hours": 24,
        "generated_at": now.isoformat(),
        "buckets": buckets,
        "summary": {
            "peak_risk_bucket": max_bucket["label"],
            "peak_risk_score": max_bucket["risk_score"],
            "peak_risk_level": max_bucket["risk_level"],
            "high_risk_count": high_count,
            "medium_risk_count": medium_count,
        },
    }


def _score_bucket(bucket, twin, predictions, trends, recent_incidents, now):
    """Score a single time bucket from all data sources."""
    start_h = bucket["start_hour"]
    end_h = bucket["end_hour"]
    reasons = []

    # ── 1. Predictive signal contribution (weight 0.5) ──
    pred_score = 0.0
    for pred in predictions:
        ptype = pred["prediction_type"]
        pscore = pred["prediction_score"]

        # Map prediction types to relevant buckets
        if ptype == "activity_decline" and 9 <= start_h <= 18:
            pred_score = max(pred_score, pscore)
            if pscore >= 0.5:
                reasons.append(f"activity decline trend ({pscore:.0%})")

        elif ptype == "sleep_disruption" and (start_h >= 21 or end_h <= 9):
            pred_score = max(pred_score, pscore)
            if pscore >= 0.5:
                reasons.append(f"sleep disruption signal ({pscore:.0%})")

        elif ptype == "wandering_risk" and 12 <= start_h <= 18:
            pred_score = max(pred_score, pscore)
            if pscore >= 0.5:
                reasons.append(f"wandering risk detected ({pscore:.0%})")

        elif ptype == "health_decline":
            # Health decline affects all buckets
            pred_score = max(pred_score, pscore * 0.7)
            if pscore >= 0.6:
                reasons.append(f"health decline pattern ({pscore:.0%})")

    # ── 2. Twin deviation contribution (weight 0.3) ──
    twin_score = 0.0
    if twin:
        rhythm = twin.get("daily_rhythm", {})
        wake_h = twin.get("wake_hour")
        sleep_h = twin.get("sleep_hour")
        inactivity_max = twin.get("typical_inactivity_max_minutes")

        # Check if bucket hours overlap with twin's expected inactive period
        for h in range(start_h, end_h):
            h_str = str(h)
            if h_str in rhythm:
                entry = rhythm[h_str]
                if entry.get("expected_active") and entry.get("avg_interaction", 0) < 1.0:
                    # Twin expects activity but recent baseline shows low interaction
                    twin_score = max(twin_score, 0.4)
                    if "twin expectation mismatch" not in " ".join(reasons):
                        reasons.append("twin expectation mismatch")

        # Sleep/wake boundary risk
        if wake_h is not None and start_h <= wake_h < end_h:
            if any(p["prediction_type"] == "sleep_disruption" for p in predictions):
                twin_score = max(twin_score, 0.5)
                reasons.append("wake time at risk (sleep disruption)")

        # Extended inactivity risk during expected active hours
        if inactivity_max and inactivity_max < 45:
            # Person normally very active, but bucket is during quiet period
            for h in range(start_h, end_h):
                h_str = str(h)
                if h_str in rhythm and not rhythm[h_str].get("expected_active"):
                    twin_score = max(twin_score, 0.3)

    # ── 3. Trend contribution (weight 0.2) ──
    trend_score = 0.0
    if trends:
        mov_trend = trends.get("movement_trend", 0)
        int_trend = trends.get("interaction_trend", 0)
        variance = trends.get("activity_variance", 0)

        # Declining movement/interaction increases risk for active hours
        if 9 <= start_h <= 18:
            if mov_trend < -0.05:
                trend_score = max(trend_score, min(abs(mov_trend) / 0.2, 1.0))
                reasons.append(f"movement declining ({abs(mov_trend)*100:.0f}%/day)")
            if int_trend < -0.05:
                trend_score = max(trend_score, min(abs(int_trend) / 0.2, 1.0))

        # High variance increases risk for all buckets
        if variance > 3.0:
            variance_risk = min(variance / 8.0, 0.5)
            trend_score = max(trend_score, variance_risk)
            if variance > 5.0:
                reasons.append("high activity variance")

    # ── 4. Recent incident boost ──
    incident_boost = 0.0
    for inc in recent_incidents:
        inc_hour = inc.get("hour", 0)
        if start_h <= inc_hour < end_h:
            # Incident happened in this bucket recently
            incident_boost = max(incident_boost, 0.15)
            inc_type = inc.get("incident_type", "incident")
            reasons.append(f"recent {inc_type.replace('_',' ')}")
            break

    # ── Final weighted score ──
    raw_score = (
        W_PREDICTIVE * pred_score +
        W_TWIN * twin_score +
        W_TREND * trend_score +
        incident_boost
    )
    final_score = min(1.0, raw_score)

    # Deduplicate reasons
    seen = set()
    unique_reasons = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            unique_reasons.append(r)

    return final_score, unique_reasons


def _classify_risk(score: float) -> str:
    if score >= RISK_MEDIUM:
        return "HIGH"
    elif score >= RISK_LOW:
        return "MEDIUM"
    return "LOW"


async def _fetch_twin(session: AsyncSession, device_id: str) -> dict | None:
    """Fetch digital twin profile with daily rhythm."""
    row = (await session.execute(text("""
        SELECT wake_hour, sleep_hour, peak_activity_hour,
               typical_inactivity_max_minutes, confidence_score,
               daily_rhythm, activity_windows
        FROM device_digital_twins
        WHERE device_id = :did AND confidence_score >= 0.15
    """), {"did": device_id})).fetchone()

    if not row:
        return None

    return {
        "wake_hour": row.wake_hour,
        "sleep_hour": row.sleep_hour,
        "peak_activity_hour": row.peak_activity_hour,
        "typical_inactivity_max_minutes": row.typical_inactivity_max_minutes,
        "confidence": row.confidence_score,
        "daily_rhythm": row.daily_rhythm if isinstance(row.daily_rhythm, dict) else {},
        "activity_windows": row.activity_windows if isinstance(row.activity_windows, list) else [],
    }


async def _fetch_predictions(session: AsyncSession, device_id: str) -> list:
    """Fetch active predictive risk signals."""
    rows = (await session.execute(text("""
        SELECT prediction_type, prediction_score, prediction_window_hours, confidence
        FROM predictive_risks
        WHERE device_id = :did AND is_active = true
        ORDER BY prediction_score DESC
        LIMIT 10
    """), {"did": device_id})).fetchall()

    return [
        {
            "prediction_type": r.prediction_type,
            "prediction_score": float(r.prediction_score),
            "window_hours": r.prediction_window_hours,
            "confidence": float(r.confidence),
        }
        for r in rows
    ]


async def _fetch_trends(session: AsyncSession, device_id: str) -> dict | None:
    """Fetch recent telemetry trend features (7-day)."""
    lookback = datetime.now(timezone.utc) - timedelta(days=7)

    rows = (await session.execute(text("""
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS heartbeat_count,
            STDDEV_POP((metric_value->>'signal_strength')::float) AS movement_proxy,
            COUNT(DISTINCT EXTRACT(HOUR FROM created_at)) AS active_hours
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'heartbeat'
          AND is_simulated = false AND created_at >= :lookback
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
    """), {"did": device_id, "lookback": lookback})).fetchall()

    if len(rows) < 2:
        return None

    movements = [float(r.movement_proxy or 0) for r in rows]
    interactions = [int(r.heartbeat_count) for r in rows]
    active_hrs = [int(r.active_hours) for r in rows]

    return {
        "movement_trend": _compute_trend(movements),
        "interaction_trend": _compute_trend(interactions),
        "activity_variance": _compute_variance(active_hrs),
        "num_days": len(rows),
    }


async def _fetch_recent_incidents(session: AsyncSession, device_id: str) -> list:
    """Fetch incidents from the last 48 hours for this device."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = (await session.execute(text("""
        SELECT incident_type, severity, EXTRACT(HOUR FROM created_at) AS hour
        FROM incidents
        WHERE device_id = :did AND created_at >= :cutoff AND is_test = false
        ORDER BY created_at DESC
        LIMIT 10
    """), {"did": device_id, "cutoff": cutoff})).fetchall()

    return [
        {"incident_type": r.incident_type, "severity": r.severity, "hour": int(r.hour)}
        for r in rows
    ]


def _compute_trend(values: list) -> float:
    """Normalized linear trend (slope / mean)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_val = sum(values) / n
    if mean_val == 0:
        return 0.0
    x_mean = (n - 1) / 2.0
    numerator = sum((i - x_mean) * (v - mean_val) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    slope = numerator / denominator
    return slope / max(abs(mean_val), 0.001)


def _compute_variance(values: list) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)
