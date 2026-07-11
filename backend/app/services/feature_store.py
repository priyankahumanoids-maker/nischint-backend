"""
NISCHINT AI Learning Loop — Phase 1: Feature Store

Extracts structured training features from existing PostgreSQL data:
  telemetries, incidents, location_risk_zones, behavior_anomalies, city_risk_snapshots

Caches latest features in Redis with key features:user:{user_id} TTL 5 min.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.redis_service import set_json, get_json

logger = logging.getLogger(__name__)

FEATURE_CACHE_TTL = 300  # 5 minutes


async def extract_features_for_user(session: AsyncSession, user_id: str) -> list[dict]:
    """
    Extract training features for a specific user (guardian_id).
    Joins seniors → devices → telemetries + incidents + risk zones.
    Returns list of feature dicts (one per telemetry window).
    """
    cached = get_json("features", f"user:{user_id}")
    if cached:
        return cached

    features = await _extract_raw(session, user_id)

    if features:
        set_json("features", f"user:{user_id}", features, ttl=FEATURE_CACHE_TTL)

    return features


async def extract_all_training_data(session: AsyncSession) -> list[dict]:
    """Extract training features across ALL users for model training."""
    cached = get_json("features", "all_training")
    if cached:
        return cached

    features = await _extract_raw(session, user_id=None)

    if features:
        set_json("features", "all_training", features, ttl=FEATURE_CACHE_TTL)

    return features


async def _extract_raw(session: AsyncSession, user_id: Optional[str]) -> list[dict]:
    """
    Core feature extraction query. Builds feature vectors by:
    1. Getting all telemetry timestamps per device
    2. For each timestamp window, checking if an incident occurred within ±30 min
    3. Enriching with area risk score from nearest risk zone
    4. Adding behavioral anomaly count for context
    """
    user_filter = ""
    params = {}
    if user_id:
        user_filter = "AND s.guardian_id = :user_id"
        params["user_id"] = user_id

    query = text(f"""
        WITH device_telemetry AS (
            SELECT
                t.device_id,
                d.senior_id,
                s.guardian_id,
                t.created_at AS ts,
                EXTRACT(HOUR FROM t.created_at) AS hour_of_day,
                EXTRACT(DOW FROM t.created_at) AS day_of_week,
                t.metric_value
            FROM telemetries t
            JOIN devices d ON d.id = t.device_id
            JOIN seniors s ON s.id = d.senior_id
            WHERE t.metric_type IN ('heartbeat', 'location', 'accelerometer', 'activity')
            {user_filter}
        ),
        device_locations AS (
            SELECT DISTINCT ON (device_id)
                device_id, latitude, longitude
            FROM device_locations
            ORDER BY device_id, updated_at DESC
        ),
        incident_windows AS (
            SELECT
                i.device_id,
                i.created_at AS incident_at,
                i.incident_type,
                i.severity
            FROM incidents i
            WHERE i.status != 'false_alarm'
        ),
        nearest_risk AS (
            SELECT
                dl.device_id,
                dl.latitude,
                dl.longitude,
                COALESCE(
                    (SELECT lrz.risk_score
                     FROM location_risk_zones lrz
                     ORDER BY (
                        (lrz.latitude - dl.latitude) * (lrz.latitude - dl.latitude) +
                        (lrz.longitude - dl.longitude) * (lrz.longitude - dl.longitude)
                     ) ASC
                     LIMIT 1),
                    0.1
                ) AS area_risk_score,
                COALESCE(
                    (SELECT lrz.risk_level
                     FROM location_risk_zones lrz
                     ORDER BY (
                        (lrz.latitude - dl.latitude) * (lrz.latitude - dl.latitude) +
                        (lrz.longitude - dl.longitude) * (lrz.longitude - dl.longitude)
                     ) ASC
                     LIMIT 1),
                    'low'
                ) AS zone_type
            FROM device_locations dl
        ),
        anomaly_counts AS (
            SELECT
                device_id,
                COUNT(*) AS anomaly_count_30d
            FROM behavior_anomalies
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY device_id
        )
        SELECT
            dt.guardian_id::text AS user_id,
            dt.ts AS timestamp,
            dt.hour_of_day::int,
            dt.day_of_week::int,
            COALESCE(nr.latitude, 19.076) AS location_lat,
            COALESCE(nr.longitude, 72.877) AS location_lng,
            COALESCE(nr.area_risk_score, 0.1) AS area_risk_score,
            0.0 AS movement_speed,
            COALESCE(
                EXTRACT(EPOCH FROM (
                    dt.ts - (
                        SELECT MAX(iw.incident_at) FROM incident_windows iw
                        WHERE iw.device_id = dt.device_id AND iw.incident_at < dt.ts
                    )
                )) / 3600.0,
                720.0
            ) AS time_since_last_incident_hours,
            COALESCE(nr.zone_type, 'low') AS zone_type,
            COALESCE(ac.anomaly_count_30d, 0) AS anomaly_count,
            EXISTS (
                SELECT 1 FROM incident_windows iw
                WHERE iw.device_id = dt.device_id
                AND ABS(EXTRACT(EPOCH FROM (iw.incident_at - dt.ts))) < 1800
            ) AS incident_occurred
        FROM device_telemetry dt
        LEFT JOIN nearest_risk nr ON nr.device_id = dt.device_id
        LEFT JOIN anomaly_counts ac ON ac.device_id = dt.device_id
        ORDER BY dt.ts DESC
        LIMIT 10000
    """)

    result = await session.execute(query, params)
    rows = result.fetchall()

    features = []
    for r in rows:
        features.append({
            "user_id": r[0],
            "timestamp": r[1].isoformat() if r[1] else None,
            "hour_of_day": r[2],
            "day_of_week": r[3],
            "location_lat": float(r[4]),
            "location_lng": float(r[5]),
            "area_risk_score": float(r[6]),
            "movement_speed": float(r[7]),
            "time_since_last_incident": float(r[8]),
            "zone_type": r[9],
            "anomaly_count": int(r[10]),
            "incident_occurred": bool(r[11]),
        })

    logger.info(f"Feature store: extracted {len(features)} features (user={'all' if not user_id else user_id})")
    return features


async def get_live_features(session: AsyncSession, user_id: str) -> dict:
    """
    Get real-time feature vector for a single user (for live prediction).
    Uses latest device data, not historical.
    """
    cached = get_json("features", f"live:{user_id}")
    if cached:
        return cached

    query = text("""
        SELECT
            EXTRACT(HOUR FROM NOW()) AS hour_of_day,
            EXTRACT(DOW FROM NOW()) AS day_of_week,
            COALESCE(dl.latitude, 19.076) AS lat,
            COALESCE(dl.longitude, 72.877) AS lng,
            COALESCE(
                (SELECT lrz.risk_score FROM location_risk_zones lrz
                 ORDER BY ((lrz.latitude - COALESCE(dl.latitude,0))^2 + (lrz.longitude - COALESCE(dl.longitude,0))^2) ASC
                 LIMIT 1),
                0.1
            ) AS area_risk_score,
            COALESCE(
                (SELECT lrz.risk_level FROM location_risk_zones lrz
                 ORDER BY ((lrz.latitude - COALESCE(dl.latitude,0))^2 + (lrz.longitude - COALESCE(dl.longitude,0))^2) ASC
                 LIMIT 1),
                'low'
            ) AS zone_type,
            COALESCE(
                EXTRACT(EPOCH FROM (NOW() - (
                    SELECT MAX(i.created_at) FROM incidents i
                    JOIN devices dd ON dd.id = i.device_id
                    JOIN seniors ss ON ss.id = dd.senior_id
                    WHERE ss.guardian_id = :uid AND i.status != 'false_alarm'
                ))) / 3600.0,
                720.0
            ) AS time_since_last_incident,
            COALESCE(
                (SELECT COUNT(*) FROM behavior_anomalies ba
                 WHERE ba.device_id = d.id AND ba.created_at > NOW() - INTERVAL '30 days'),
                0
            ) AS anomaly_count
        FROM seniors s
        JOIN devices d ON d.senior_id = s.id
        LEFT JOIN device_locations dl ON dl.device_id = d.id
        WHERE s.guardian_id = :uid
        ORDER BY d.last_seen DESC NULLS LAST
        LIMIT 1
    """)

    result = await session.execute(query, {"uid": user_id})
    row = result.fetchone()

    if not row:
        return {}

    features = {
        "user_id": user_id,
        "hour_of_day": int(row[0]),
        "day_of_week": int(row[1]),
        "location_lat": float(row[2]),
        "location_lng": float(row[3]),
        "area_risk_score": float(row[4]),
        "zone_type": row[5],
        "time_since_last_incident": float(row[6]),
        "anomaly_count": int(row[7]),
        "movement_speed": 0.0,
    }

    set_json("features", f"live:{user_id}", features, ttl=FEATURE_CACHE_TTL)
    return features
