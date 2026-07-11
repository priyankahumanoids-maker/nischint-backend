# AI Safety Score Engine
# Compresses complex AI signals into a single 0-100 safety score per device.
#
# Formula: SafetyScore = 100 - (predictive*25 + anomalies*20 + forecast*20 + twin*15 + instability*20)
# Clamped to [0, 100].
#
# Score → Status:
#   90-100  Excellent (Green)
#   75-89   Stable (Green)
#   60-74   Monitor (Amber)
#   40-59   Attention (Orange)
#   0-39    Critical (Red)

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Weights (sum = 100 when all inputs are 1.0)
W_PREDICTIVE = 25
W_ANOMALIES = 20
W_FORECAST = 20
W_TWIN = 15
W_INSTABILITY = 20

STATUS_THRESHOLDS = [
    (90, "EXCELLENT"),
    (75, "STABLE"),
    (60, "MONITOR"),
    (40, "ATTENTION"),
    (0, "CRITICAL"),
]


def classify_status(score: float) -> str:
    for threshold, label in STATUS_THRESHOLDS:
        if score >= threshold:
            return label
    return "CRITICAL"


async def calculate_safety_score(session: AsyncSession, device_id: str) -> dict | None:
    """Calculate a comprehensive safety score for a device."""
    # Verify device exists
    device = (await session.execute(text(
        "SELECT id, device_identifier FROM devices WHERE id = :did"
    ), {"did": device_id})).fetchone()
    if not device:
        return None

    # Gather all 5 signal inputs
    predictive_risk = await _get_predictive_risk(session, device_id)
    anomaly_count, anomaly_factor = await _get_active_anomalies(session, device_id)
    forecast_peak = await _get_forecast_peak(session, device_id)
    twin_deviation = await _get_twin_deviation(session, device_id)
    instability = await _get_device_instability(session, device_id)

    # Compute weighted score
    penalty = (
        W_PREDICTIVE * predictive_risk +
        W_ANOMALIES * anomaly_factor +
        W_FORECAST * forecast_peak +
        W_TWIN * twin_deviation +
        W_INSTABILITY * instability
    )
    score = max(0.0, min(100.0, 100.0 - penalty))
    score = round(score, 1)
    status = classify_status(score)

    return {
        "device_id": str(device_id),
        "device_identifier": device.device_identifier,
        "safety_score": score,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contributors": {
            "predictive_risk": round(predictive_risk, 3),
            "anomaly_count": anomaly_count,
            "anomaly_factor": round(anomaly_factor, 3),
            "forecast_peak_risk": round(forecast_peak, 3),
            "twin_deviation": round(twin_deviation, 3),
            "device_instability": round(instability, 3),
        },
    }


async def calculate_fleet_safety(session: AsyncSession) -> dict:
    """Calculate safety scores for all active devices using batch queries."""
    devices = (await session.execute(text("""
        SELECT d.id, d.device_identifier
        FROM devices d
        JOIN seniors s ON d.senior_id = s.id
        ORDER BY d.device_identifier
    """))).fetchall()

    if not devices:
        return {"fleet_score": 0, "fleet_status": "MONITOR", "device_count": 0,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status_breakdown": {}, "devices": []}

    device_ids = [str(d.id) for d in devices]
    id_map = {str(d.id): d.device_identifier for d in devices}

    # Batch-fetch all signals in parallel-safe way (7 queries instead of 72+)
    pred_data = await _batch_predictive_risk(session, device_ids)
    dev_anom, beh_anom = await _batch_active_anomalies(session, device_ids)
    forecast_data = await _batch_forecast_peak(session, device_ids)
    twin_data = await _batch_twin_deviation(session, device_ids)
    offline_data, heartbeat_data = await _batch_device_instability(session, device_ids)

    device_scores = []
    now = datetime.now(timezone.utc)
    current_hour = now.hour

    for did in device_ids:
        predictive_risk = pred_data.get(did, 0.0)

        # Anomalies
        total_anom = dev_anom.get(did, 0) + beh_anom.get(did, 0)
        anomaly_factor = min(total_anom / 5.0, 1.0)

        forecast_peak = forecast_data.get(did, 0.0)

        # Twin deviation
        twin_dev = 0.0
        twin_info = twin_data.get(did)
        if twin_info and twin_info["confidence"] >= 0.15 and twin_info["rhythm"]:
            rhythm = twin_info["rhythm"]
            hour_data = rhythm.get(str(current_hour))
            if hour_data:
                expected_active = hour_data.get("expected_active", False)
                expected_interaction = hour_data.get("avg_interaction", 0)
                actual_interaction = twin_info.get("recent_hb", 0)
                if expected_active and expected_interaction > 1:
                    if actual_interaction == 0:
                        twin_dev = 0.8
                    else:
                        ratio = actual_interaction / expected_interaction
                        if ratio < 0.3:
                            twin_dev = 0.6
                        elif ratio < 0.6:
                            twin_dev = 0.3
                elif not expected_active and actual_interaction > expected_interaction * 2 and expected_interaction > 0:
                    twin_dev = 0.4

        # Instability
        offline_count = offline_data.get(did, 0)
        latest_hb_ts = heartbeat_data.get(did)
        stale_factor = 1.0
        if latest_hb_ts:
            minutes_since = (now - latest_hb_ts).total_seconds() / 60
            if minutes_since > 120: stale_factor = 0.8
            elif minutes_since > 60: stale_factor = 0.5
            elif minutes_since > 30: stale_factor = 0.2
            else: stale_factor = 0.0
        instability = min(1.0, min(offline_count / 3.0, 1.0) * 0.5 + stale_factor * 0.5)

        penalty = (
            W_PREDICTIVE * predictive_risk +
            W_ANOMALIES * anomaly_factor +
            W_FORECAST * forecast_peak +
            W_TWIN * twin_dev +
            W_INSTABILITY * instability
        )
        score = round(max(0.0, min(100.0, 100.0 - penalty)), 1)
        status = classify_status(score)

        device_scores.append({
            "device_id": did,
            "device_identifier": id_map[did],
            "safety_score": score,
            "status": status,
            "generated_at": now.isoformat(),
            "contributors": {
                "predictive_risk": round(predictive_risk, 3),
                "anomaly_count": total_anom,
                "anomaly_factor": round(anomaly_factor, 3),
                "forecast_peak_risk": round(forecast_peak, 3),
                "twin_deviation": round(twin_dev, 3),
                "device_instability": round(instability, 3),
            },
        })

    total_score = sum(d["safety_score"] for d in device_scores)
    fleet_score = round(total_score / len(device_scores), 1) if device_scores else 0.0
    fleet_status = classify_status(fleet_score)
    device_scores.sort(key=lambda d: d["safety_score"])

    return {
        "fleet_score": fleet_score,
        "fleet_status": fleet_status,
        "device_count": len(device_scores),
        "generated_at": now.isoformat(),
        "status_breakdown": {
            "excellent": sum(1 for d in device_scores if d["status"] == "EXCELLENT"),
            "stable": sum(1 for d in device_scores if d["status"] == "STABLE"),
            "monitor": sum(1 for d in device_scores if d["status"] == "MONITOR"),
            "attention": sum(1 for d in device_scores if d["status"] == "ATTENTION"),
            "critical": sum(1 for d in device_scores if d["status"] == "CRITICAL"),
        },
        "devices": device_scores,
    }


# ── Batch Signal Fetchers ──

async def _batch_predictive_risk(session, device_ids):
    """Highest active predictive risk per device."""
    rows = (await session.execute(text("""
        SELECT device_id, MAX(prediction_score) AS max_score
        FROM predictive_risks
        WHERE device_id = ANY(:ids) AND is_active = true
        GROUP BY device_id
    """), {"ids": device_ids})).fetchall()
    return {str(r.device_id): float(r.max_score) for r in rows}


async def _batch_active_anomalies(session, device_ids):
    """Count active anomalies per device (device + behavior)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)

    dev_rows = (await session.execute(text("""
        SELECT device_id, COUNT(*) AS cnt
        FROM device_anomalies
        WHERE device_id = ANY(:ids) AND created_at >= :cutoff
        GROUP BY device_id
    """), {"ids": device_ids, "cutoff": cutoff})).fetchall()
    dev_map = {str(r.device_id): r.cnt for r in dev_rows}

    beh_rows = (await session.execute(text("""
        SELECT device_id, COUNT(*) AS cnt
        FROM behavior_anomalies
        WHERE device_id = ANY(:ids) AND created_at >= :cutoff AND is_simulated = false
        GROUP BY device_id
    """), {"ids": device_ids, "cutoff": cutoff})).fetchall()
    beh_map = {str(r.device_id): r.cnt for r in beh_rows}

    return dev_map, beh_map


async def _batch_forecast_peak(session, device_ids):
    """Peak forecast risk per device."""
    rows = (await session.execute(text("""
        SELECT device_id, MAX(risk_score) AS peak
        FROM risk_forecasts
        WHERE device_id = ANY(:ids) AND created_at > NOW() - INTERVAL '30 minutes'
        GROUP BY device_id
    """), {"ids": device_ids})).fetchall()
    return {str(r.device_id): float(r.peak) for r in rows}


async def _batch_twin_deviation(session, device_ids):
    """Twin data + recent heartbeat count for all devices."""
    twin_rows = (await session.execute(text("""
        SELECT device_id, daily_rhythm, confidence_score
        FROM device_digital_twins
        WHERE device_id = ANY(:ids)
    """), {"ids": device_ids})).fetchall()

    hb_rows = (await session.execute(text("""
        SELECT device_id, COUNT(*) AS cnt
        FROM telemetries
        WHERE device_id = ANY(:ids) AND metric_type = 'heartbeat'
          AND is_simulated = false
          AND created_at >= NOW() - INTERVAL '1 hour'
        GROUP BY device_id
    """), {"ids": device_ids})).fetchall()
    hb_map = {str(r.device_id): r.cnt for r in hb_rows}

    result = {}
    for r in twin_rows:
        did = str(r.device_id)
        rhythm = r.daily_rhythm if isinstance(r.daily_rhythm, dict) else {}
        result[did] = {
            "confidence": float(r.confidence_score or 0),
            "rhythm": rhythm,
            "recent_hb": hb_map.get(did, 0),
        }
    return result


async def _batch_device_instability(session, device_ids):
    """Offline incidents + latest heartbeat per device."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)

    offline_rows = (await session.execute(text("""
        SELECT device_id, COUNT(*) AS cnt
        FROM incidents
        WHERE device_id = ANY(:ids) AND incident_type = 'device_offline'
          AND created_at >= :cutoff AND is_test = false
        GROUP BY device_id
    """), {"ids": device_ids, "cutoff": cutoff})).fetchall()
    offline_map = {str(r.device_id): r.cnt for r in offline_rows}

    hb_rows = (await session.execute(text("""
        SELECT DISTINCT ON (device_id) device_id, created_at
        FROM telemetries
        WHERE device_id = ANY(:ids) AND metric_type = 'heartbeat' AND is_simulated = false
        ORDER BY device_id, created_at DESC
    """), {"ids": device_ids})).fetchall()
    hb_map = {str(r.device_id): r.created_at for r in hb_rows}

    return offline_map, hb_map
