# Location Risk Intelligence Engine
# Evaluates safety of locations using PostGIS, incident density,
# time-of-day, and risk zone proximity.

import logging
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Risk score weights (sum = 1.0)
W_INCIDENT = 0.30
W_TIME = 0.20
W_ZONE = 0.25
W_ISOLATION = 0.15
W_HISTORY = 0.10

# Time-of-day risk multipliers (0-1 scale)
TIME_RISK = {
    0: 0.9, 1: 0.95, 2: 0.95, 3: 0.9, 4: 0.8, 5: 0.5,
    6: 0.3, 7: 0.2, 8: 0.15, 9: 0.1, 10: 0.1, 11: 0.1,
    12: 0.15, 13: 0.15, 14: 0.15, 15: 0.2, 16: 0.2, 17: 0.3,
    18: 0.4, 19: 0.55, 20: 0.65, 21: 0.75, 22: 0.8, 23: 0.85,
}


async def evaluate_location_risk(
    session: AsyncSession, lat: float, lng: float, timestamp: datetime | None = None
) -> dict:
    """Evaluate the safety risk score for a given lat/lng."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    hour = timestamp.hour

    # 1. Incident density within 500m radius (last 90 days)
    cutoff = timestamp - timedelta(days=90)
    incident_result = (await session.execute(text("""
        SELECT COUNT(*) as cnt,
               COALESCE(AVG(CASE WHEN severity='critical' THEN 1.0
                                 WHEN severity='high' THEN 0.7
                                 WHEN severity='medium' THEN 0.4
                                 ELSE 0.2 END), 0) as avg_sev
        FROM location_incidents
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            500
        ) AND created_at >= :cutoff
    """), {"lat": lat, "lng": lng, "cutoff": cutoff})).fetchone()

    incident_count = incident_result.cnt or 0
    avg_severity = float(incident_result.avg_sev or 0)
    # Normalize: 0 incidents=0, 10+=1.0
    incident_density = min(1.0, incident_count / 10.0) * (0.5 + 0.5 * avg_severity)

    # 2. Time-of-day risk
    time_risk = TIME_RISK.get(hour, 0.5)

    # 3. Nearest risk zone
    zone_result = (await session.execute(text("""
        SELECT zone_name, risk_score, risk_level, risk_type, factors,
               ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) as dist_m
        FROM location_risk_zones
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            1000
        )
        ORDER BY dist_m ASC
        LIMIT 3
    """), {"lat": lat, "lng": lng})).fetchall()

    zone_risk = 0.0
    zone_factors = []
    nearest_zone = None
    for z in zone_result:
        dist = float(z.dist_m)
        proximity = max(0, 1.0 - dist / 1000.0)
        # Extract trend multiplier from factors if present
        trend_mult = 1.0
        factors = z.factors
        if isinstance(factors, str):
            factors = json.loads(factors)
        if isinstance(factors, list):
            for item in factors:
                if isinstance(item, dict) and 'trend_multiplier' in item:
                    trend_mult = item['trend_multiplier']
                    break
        contribution = (float(z.risk_score) / 10.0) * proximity * trend_mult
        zone_risk = max(zone_risk, min(1.0, contribution))
        str_factors = [f for f in (factors or []) if isinstance(f, str)]
        if proximity > 0.3:
            zone_factors.extend(str_factors)
        if nearest_zone is None:
            nearest_zone = {"name": z.zone_name, "type": z.risk_type, "distance_m": round(dist)}

    # 4. Isolation score (inverse of device density nearby)
    nearby_devices = (await session.execute(text("""
        SELECT COUNT(*) FROM device_locations
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            500
        )
    """), {"lat": lat, "lng": lng})).scalar() or 0
    isolation = max(0, 1.0 - nearby_devices / 5.0)

    # 5. Device-specific history at this location
    history_score = min(1.0, incident_count / 20.0)

    # 6. Human activity risk signal: SOS/fall clustering → crowd/hazard proxy
    activity_signal = 0.0
    if incident_count > 0:
        sos_count = (await session.execute(text("""
            SELECT COUNT(*) FROM location_incidents li
            JOIN incidents i ON li.incident_id = i.id
            WHERE ST_DWithin(li.geom::geography, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, 500)
              AND li.created_at >= :cutoff
              AND li.incident_type IN ('sos_alert', 'fall_detected', 'fall_alert')
        """), {"lat": lat, "lng": lng, "cutoff": timestamp - timedelta(days=30)})).scalar() or 0
        activity_signal = min(1.0, sos_count / 10.0)

    # Compute weighted risk score (0-10)
    raw_score = (
        W_INCIDENT * incident_density
        + W_TIME * time_risk
        + W_ZONE * zone_risk
        + W_ISOLATION * isolation
        + W_HISTORY * history_score
        + 0.05 * activity_signal
    ) * 10.0
    risk_score = round(min(10.0, max(0.0, raw_score)), 1)

    risk_level = (
        "Critical" if risk_score >= 7
        else "High" if risk_score >= 5
        else "Moderate" if risk_score >= 3
        else "Low"
    )

    # Build factors list
    factors = []
    if time_risk >= 0.6:
        factors.append("Nighttime / low visibility hours")
    if incident_density > 0.3:
        factors.append(f"{incident_count} incidents nearby (90 days)")
    if isolation > 0.5:
        factors.append("Low device/crowd density")
    if activity_signal > 0.4:
        factors.append("Human activity risk (SOS/fall clustering)")
    factors.extend(zone_factors[:3])
    if not factors:
        factors.append("No significant risk factors detected")

    # Reverse geocode attempt (use zone name or generic)
    location_name = nearest_zone["name"] if nearest_zone else f"Location ({lat:.4f}, {lng:.4f})"

    return {
        "latitude": lat,
        "longitude": lng,
        "location_name": location_name,
        "safety_score": risk_score,
        "risk_level": risk_level,
        "factors": factors,
        "breakdown": {
            "incident_density": round(incident_density * 10, 1),
            "time_of_day": round(time_risk * 10, 1),
            "zone_proximity": round(zone_risk * 10, 1),
            "isolation": round(isolation * 10, 1),
            "history": round(history_score * 10, 1),
        },
        "nearby_incidents": incident_count,
        "nearest_zone": nearest_zone,
        "evaluated_at": timestamp.isoformat(),
    }


async def get_risk_heatmap_data(session: AsyncSession) -> dict:
    """Get all data needed for the Location Risk Heatmap visualization."""

    # 1. All risk zones
    zones = (await session.execute(text("""
        SELECT id, latitude, longitude, radius_meters, risk_score, risk_level,
               risk_type, factors, zone_name, incident_count
        FROM location_risk_zones
        ORDER BY risk_score DESC
    """))).fetchall()

    # 2. All device locations with latest position
    devices = (await session.execute(text("""
        SELECT dl.device_id, d.device_identifier, dl.latitude, dl.longitude, dl.updated_at
        FROM device_locations dl
        JOIN devices d ON dl.device_id = d.id
        ORDER BY d.device_identifier
    """))).fetchall()

    # 3. Recent incidents (last 30 days) for heatmap overlay
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    incidents = (await session.execute(text("""
        SELECT li.latitude, li.longitude, li.incident_type, li.severity, li.created_at,
               d.device_identifier
        FROM location_incidents li
        JOIN devices d ON li.device_id = d.id
        WHERE li.created_at >= :cutoff
        ORDER BY li.created_at DESC
        LIMIT 200
    """), {"cutoff": cutoff})).fetchall()

    # 4. Geofence rules
    geofences = (await session.execute(text("""
        SELECT gf.id, gf.device_id, d.device_identifier, gf.name,
               gf.latitude, gf.longitude, gf.radius_meters, gf.fence_type, gf.is_active
        FROM geofence_rules gf
        JOIN devices d ON gf.device_id = d.id
        WHERE gf.is_active = true
    """))).fetchall()

    # 5. Active geofence alerts (unacknowledged)
    alerts = (await session.execute(text("""
        SELECT ga.id, ga.device_id, d.device_identifier, ga.alert_type,
               ga.latitude, ga.longitude, ga.risk_score, ga.factors, ga.created_at
        FROM geofence_alerts ga
        JOIN devices d ON ga.device_id = d.id
        WHERE ga.acknowledged = false
        ORDER BY ga.created_at DESC
        LIMIT 20
    """))).fetchall()

    # Compute map bounds
    all_lats = [z.latitude for z in zones] + [d.latitude for d in devices]
    all_lngs = [z.longitude for z in zones] + [d.longitude for d in devices]
    center_lat = sum(all_lats) / len(all_lats) if all_lats else 12.97
    center_lng = sum(all_lngs) / len(all_lngs) if all_lngs else 77.59

    # Compute per-device risk scores
    device_list = []
    for d in devices:
        risk = await evaluate_location_risk(session, d.latitude, d.longitude)
        device_list.append({
            "device_id": str(d.device_id),
            "device_identifier": d.device_identifier,
            "lat": d.latitude,
            "lng": d.longitude,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "risk_score": risk["safety_score"],
            "risk_level": risk["risk_level"],
        })

    return {
        "center": {"lat": center_lat, "lng": center_lng},
        "zoom": 14,
        "risk_zones": [
            {
                "id": z.id,
                "lat": z.latitude,
                "lng": z.longitude,
                "radius": z.radius_meters,
                "risk_score": float(z.risk_score),
                "risk_level": z.risk_level,
                "risk_type": z.risk_type,
                "factors": json.loads(z.factors) if isinstance(z.factors, str) else (z.factors or []),
                "name": z.zone_name,
            }
            for z in zones
        ],
        "devices": device_list,
        "incidents": [
            {
                "lat": inc.latitude,
                "lng": inc.longitude,
                "type": inc.incident_type,
                "severity": inc.severity,
                "device": inc.device_identifier,
                "created_at": inc.created_at.isoformat(),
            }
            for inc in incidents
        ],
        "geofences": [
            {
                "id": gf.id,
                "device_id": str(gf.device_id),
                "device_identifier": gf.device_identifier,
                "name": gf.name,
                "lat": gf.latitude,
                "lng": gf.longitude,
                "radius": gf.radius_meters,
                "type": gf.fence_type,
            }
            for gf in geofences
        ],
        "active_alerts": [
            {
                "id": a.id,
                "device_id": str(a.device_id),
                "device_identifier": a.device_identifier,
                "alert_type": a.alert_type,
                "lat": a.latitude,
                "lng": a.longitude,
                "risk_score": float(a.risk_score) if a.risk_score else None,
                "factors": json.loads(a.factors) if isinstance(a.factors, str) else (a.factors or []),
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
    }


async def check_geofence_breach(
    session: AsyncSession, device_id: str, lat: float, lng: float
) -> list[dict]:
    """Check if a device position breaches any geofence rules."""
    breaches = []

    # Get active geofences for this device
    fences = (await session.execute(text("""
        SELECT id, name, latitude, longitude, radius_meters, fence_type,
               ST_Distance(
                   geom::geography,
                   ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
               ) as dist_m
        FROM geofence_rules
        WHERE device_id = :did AND is_active = true
    """), {"did": device_id, "lat": lat, "lng": lng})).fetchall()

    for f in fences:
        dist = float(f.dist_m)
        if f.fence_type == "safe" and dist > f.radius_meters:
            # Left safe zone
            risk = await evaluate_location_risk(session, lat, lng)
            alert = {
                "geofence_id": f.id,
                "geofence_name": f.name,
                "alert_type": "left_safe_zone",
                "distance_from_fence": round(dist - f.radius_meters),
                "risk_score": risk["safety_score"],
                "factors": risk["factors"],
            }
            # Persist alert
            await session.execute(text("""
                INSERT INTO geofence_alerts (device_id, geofence_id, alert_type, latitude, longitude, risk_score, factors)
                VALUES (:did, :gid, :atype, :lat, :lng, :score, :factors)
            """), {
                "did": device_id, "gid": f.id, "atype": "left_safe_zone",
                "lat": lat, "lng": lng, "score": risk["safety_score"],
                "factors": json.dumps(risk["factors"]),
            })
            breaches.append(alert)

        elif f.fence_type == "danger" and dist <= f.radius_meters:
            # Entered danger zone
            risk = await evaluate_location_risk(session, lat, lng)
            alert = {
                "geofence_id": f.id,
                "geofence_name": f.name,
                "alert_type": "entered_danger_zone",
                "distance_into_zone": round(f.radius_meters - dist),
                "risk_score": risk["safety_score"],
                "factors": risk["factors"],
            }
            await session.execute(text("""
                INSERT INTO geofence_alerts (device_id, geofence_id, alert_type, latitude, longitude, risk_score, factors)
                VALUES (:did, :gid, :atype, :lat, :lng, :score, :factors)
            """), {
                "did": device_id, "gid": f.id, "atype": "entered_danger_zone",
                "lat": lat, "lng": lng, "score": risk["safety_score"],
                "factors": json.dumps(risk["factors"]),
            })
            breaches.append(alert)

    if breaches:
        await session.commit()

    return breaches


async def create_geofence(
    session: AsyncSession, device_id: str, name: str,
    lat: float, lng: float, radius: float, fence_type: str = "safe"
) -> dict:
    """Create a new geofence rule for a device."""
    result = await session.execute(text("""
        INSERT INTO geofence_rules (device_id, name, latitude, longitude, geom, radius_meters, fence_type)
        VALUES (:did, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :radius, :ftype)
        RETURNING id
    """), {"did": device_id, "name": name, "lat": lat, "lng": lng, "radius": radius, "ftype": fence_type})
    gf_id = result.scalar()
    await session.commit()
    return {
        "id": gf_id,
        "device_id": device_id,
        "name": name,
        "lat": lat,
        "lng": lng,
        "radius": radius,
        "type": fence_type,
    }


async def update_device_location(
    session: AsyncSession, device_id: str, lat: float, lng: float, source: str = "gps"
) -> dict:
    """Update a device's latest known location and check geofences."""
    await session.execute(text("""
        INSERT INTO device_locations (device_id, latitude, longitude, geom, source, updated_at)
        VALUES (:did, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :src, NOW())
        ON CONFLICT (device_id) DO UPDATE SET
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            geom = EXCLUDED.geom,
            source = EXCLUDED.source,
            updated_at = NOW()
    """), {"did": device_id, "lat": lat, "lng": lng, "src": source})
    await session.commit()

    # Check geofence breaches
    breaches = await check_geofence_breach(session, device_id, lat, lng)

    return {
        "device_id": device_id,
        "latitude": lat,
        "longitude": lng,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "geofence_breaches": breaches,
    }
