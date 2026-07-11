# Incident Replay Engine
# Reconstructs a timeline of events around an incident for visual playback.

import json
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Replay windows per incident type (minutes before and after)
REPLAY_WINDOWS = {
    "route_deviation": (20, 5),
    "fall_detected": (5, 5),
    "sos_alert": (10, 5),
    "distress_signal": (10, 5),
    "device_offline": (15, 5),
    "low_battery": (10, 2),
    "geofence_breach": (15, 5),
}
DEFAULT_WINDOW = (15, 5)

FRAME_INTERVAL_S = 5  # 1 frame per 5 seconds


async def get_incident_replay(session: AsyncSession, incident_id: str) -> dict:
    """Build a full replay dataset for an incident."""

    # Get incident details
    incident = (await session.execute(text("""
        SELECT i.id, i.device_id, i.senior_id, i.incident_type, i.severity,
               i.status, i.escalation_level, i.created_at, i.resolved_at, i.is_test,
               d.device_identifier, s.full_name as senior_name
        FROM incidents i
        JOIN devices d ON i.device_id = d.id
        JOIN seniors s ON i.senior_id = s.id
        WHERE i.id = :iid
    """), {"iid": incident_id})).fetchone()

    if not incident:
        return None

    device_id = str(incident.device_id)
    incident_time = incident.created_at
    before_min, after_min = REPLAY_WINDOWS.get(incident.incident_type, DEFAULT_WINDOW)
    window_start = incident_time - timedelta(minutes=before_min)
    window_end = incident_time + timedelta(minutes=after_min)

    # Collect all data sources in parallel-safe sequential queries
    telemetry = await _get_telemetry_frames(session, device_id, window_start, window_end)
    anomalies = await _get_behavior_anomalies(session, device_id, window_start, window_end)
    notifications = await _get_notifications(session, device_id, window_start, window_end)
    related_incidents = await _get_related_incidents(session, device_id, window_start, window_end, incident_id)
    location_trail = await _get_location_trail(session, device_id, window_start, window_end)

    # Fetch risk overlay data (zones + environment snapshot)
    risk_zones = await _get_nearby_risk_zones(session, location_trail)
    env_snapshot = await _get_environment_snapshot(session, device_id, window_start, window_end)

    # Build timeline events
    events = _build_timeline_events(incident, telemetry, anomalies, notifications, related_incidents)

    # Build replay frames (1 per FRAME_INTERVAL_S)
    frames = _build_replay_frames(window_start, window_end, telemetry, anomalies, location_trail, events, risk_zones, env_snapshot)

    return {
        "incident_id": str(incident.id),
        "device_id": device_id,
        "device_identifier": incident.device_identifier,
        "senior_name": incident.senior_name,
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "status": incident.status,
        "escalation_level": incident.escalation_level,
        "incident_time": incident_time.isoformat(),
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "replay_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "before_minutes": before_min,
            "after_minutes": after_min,
        },
        "frames": frames,
        "events": events,
        "location_trail": location_trail,
        "stats": {
            "total_frames": len(frames),
            "total_events": len(events),
            "telemetry_points": len(telemetry),
            "anomalies": len(anomalies),
            "notifications_sent": len(notifications),
        },
    }


# ── Data collectors ──

async def _get_telemetry_frames(session, device_id, start, end):
    rows = (await session.execute(text("""
        SELECT metric_type, metric_value, created_at
        FROM telemetries
        WHERE device_id = :did AND created_at BETWEEN :s AND :e
        ORDER BY created_at
    """), {"did": device_id, "s": start, "e": end})).fetchall()

    return [{
        "type": r.metric_type,
        "value": r.metric_value if isinstance(r.metric_value, dict) else {},
        "timestamp": r.created_at.isoformat(),
        "ts": r.created_at,
    } for r in rows]


async def _get_behavior_anomalies(session, device_id, start, end):
    rows = (await session.execute(text("""
        SELECT behavior_score, anomaly_type, reason, created_at
        FROM behavior_anomalies
        WHERE device_id = :did AND created_at BETWEEN :s AND :e
        ORDER BY created_at
    """), {"did": device_id, "s": start, "e": end})).fetchall()

    return [{
        "score": float(r.behavior_score), "type": r.anomaly_type,
        "reason": r.reason, "timestamp": r.created_at.isoformat(),
        "ts": r.created_at,
    } for r in rows]


async def _get_notifications(session, device_id, start, end):
    rows = (await session.execute(text("""
        SELECT event_type, severity, title, message, channel, status, sent_at
        FROM notifications_log
        WHERE device_id = :did AND sent_at BETWEEN :s AND :e
        ORDER BY sent_at
    """), {"did": device_id, "s": start, "e": end})).fetchall()

    return [{
        "event_type": r.event_type, "severity": r.severity,
        "title": r.title, "channel": r.channel, "status": r.status,
        "timestamp": r.sent_at.isoformat(), "ts": r.sent_at,
    } for r in rows]


async def _get_related_incidents(session, device_id, start, end, exclude_id):
    rows = (await session.execute(text("""
        SELECT id, incident_type, severity, status, created_at
        FROM incidents
        WHERE device_id = :did AND created_at BETWEEN :s AND :e AND id != :eid
        ORDER BY created_at
    """), {"did": device_id, "s": start, "e": end, "eid": exclude_id})).fetchall()

    return [{
        "id": str(r.id), "type": r.incident_type, "severity": r.severity,
        "status": r.status, "timestamp": r.created_at.isoformat(),
        "ts": r.created_at,
    } for r in rows]


async def _get_location_trail(session, device_id, start, end):
    """Get GPS trail from telemetry (location metric type) or device_locations."""
    # Try telemetry with location data first
    rows = (await session.execute(text("""
        SELECT metric_value, created_at
        FROM telemetries
        WHERE device_id = :did AND metric_type = 'location'
          AND created_at BETWEEN :s AND :e
        ORDER BY created_at
    """), {"did": device_id, "s": start, "e": end})).fetchall()

    trail = []
    for r in rows:
        val = r.metric_value if isinstance(r.metric_value, dict) else {}
        lat = val.get("latitude") or val.get("lat")
        lng = val.get("longitude") or val.get("lng") or val.get("lon")
        if lat and lng:
            trail.append({
                "lat": float(lat), "lng": float(lng),
                "speed": val.get("speed", 0),
                "timestamp": r.created_at.isoformat(),
                "ts": r.created_at,
            })

    # If no location telemetry, use device_locations (last known position only)
    if not trail:
        loc = (await session.execute(text("""
            SELECT ST_Y(geom) as lat, ST_X(geom) as lng, updated_at
            FROM device_locations WHERE device_id = :did LIMIT 1
        """), {"did": device_id})).fetchone()
        if loc:
            trail.append({
                "lat": float(loc.lat), "lng": float(loc.lng),
                "speed": 0, "timestamp": loc.updated_at.isoformat(),
                "ts": loc.updated_at,
            })

    return [{"lat": t["lat"], "lng": t["lng"], "speed": t.get("speed", 0),
             "timestamp": t["timestamp"]} for t in trail]


import math

def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _get_nearby_risk_zones(session, trail):
    """Fetch risk zones near the location trail for overlay scoring."""
    if not trail:
        return []
    lats = [t["lat"] for t in trail if "lat" in t]
    lngs = [t["lng"] for t in trail if "lng" in t]
    if not lats:
        return []
    bbox = {
        "min_lat": min(lats) - 0.01, "max_lat": max(lats) + 0.01,
        "min_lng": min(lngs) - 0.01, "max_lng": max(lngs) + 0.01,
    }
    rows = (await session.execute(text("""
        SELECT risk_score, zone_name, ST_Y(geom) as lat, ST_X(geom) as lng
        FROM location_risk_zones
        WHERE ST_Y(geom) BETWEEN :min_lat AND :max_lat
          AND ST_X(geom) BETWEEN :min_lng AND :max_lng
    """), bbox)).fetchall()
    return [(float(r.risk_score), r.zone_name, float(r.lat), float(r.lng)) for r in rows]


async def _get_environment_snapshot(session, device_id, start, end):
    """Get environment risk data from telemetry or generate time-based estimate."""
    # Check for environment telemetry
    rows = (await session.execute(text("""
        SELECT metric_value, created_at FROM telemetries
        WHERE device_id = :did AND metric_type = 'environment'
          AND created_at BETWEEN :s AND :e
        ORDER BY created_at
    """), {"did": device_id, "s": start, "e": end})).fetchall()

    if rows:
        return [{
            "timestamp": r.created_at.isoformat(),
            "ts": r.created_at,
            "data": r.metric_value if isinstance(r.metric_value, dict) else {},
        } for r in rows]

    # Fallback: time-based environment risk estimate
    hour = start.hour
    # Higher risk at night, early morning, extreme heat hours
    if 22 <= hour or hour < 5:
        base_env = 5.5  # night risk
    elif 12 <= hour < 15:
        base_env = 4.0  # peak heat
    elif 5 <= hour < 8:
        base_env = 3.0  # early morning
    else:
        base_env = 2.0  # normal
    return [{"base_score": base_env}]


def _compute_location_risk(lat, lng, risk_zones):
    """Compute location risk score (0-10) based on proximity to risk zones."""
    if not risk_zones:
        return 0.0
    max_risk = 0.0
    for z_risk, z_name, z_lat, z_lng in risk_zones:
        if abs(lat - z_lat) < 0.005 and abs(lng - z_lng) < 0.007:
            dist = _haversine(lat, lng, z_lat, z_lng)
            if dist <= 500:
                proximity_factor = 1.0 - (dist / 500.0)
                score = (z_risk / 10.0) * proximity_factor * 10.0
                max_risk = max(max_risk, score)
    return round(min(10.0, max_risk), 1)


def _compute_environment_risk(frame_time, env_snapshot):
    """Compute environment risk score (0-10) for a given frame time."""
    if not env_snapshot:
        return 0.0
    # If we have timestamped env data, find closest
    if "ts" in env_snapshot[0]:
        closest = min(env_snapshot, key=lambda e: abs((e["ts"] - frame_time).total_seconds()))
        data = closest.get("data", {})
        # Use env risk score if available
        return round(min(10.0, float(data.get("risk_score", data.get("env_risk", 2.0)))), 1)
    # Fallback: use base score
    return round(env_snapshot[0].get("base_score", 2.0), 1)


# ── Event builder ──

def _build_timeline_events(incident, telemetry, anomalies, notifications, related_incidents):
    events = []

    # Telemetry events (select significant ones)
    for t in telemetry:
        if t["type"] == "sos":
            events.append({"time": t["timestamp"], "ts": t["ts"], "type": "sos_trigger",
                           "label": "SOS Triggered", "severity": "critical", "icon": "alert"})
        elif t["type"] == "location":
            val = t["value"]
            if val.get("speed", 999) < 0.1:
                events.append({"time": t["timestamp"], "ts": t["ts"], "type": "stationary",
                               "label": "Device stationary", "severity": "low", "icon": "pause"})
        elif t["type"] == "heartbeat":
            val = t["value"]
            batt = val.get("battery_level", 100)
            if batt < 15:
                events.append({"time": t["timestamp"], "ts": t["ts"], "type": "low_battery",
                               "label": f"Battery critical ({batt:.0f}%)", "severity": "high", "icon": "battery"})

    # Anomalies
    for a in anomalies:
        events.append({"time": a["timestamp"], "ts": a["ts"], "type": "behavior_anomaly",
                       "label": f"{a['type']}: {a['reason'][:60]}", "severity": "medium", "icon": "brain"})

    # Notifications
    seen_notifs = set()
    for n in notifications:
        key = f"{n['event_type']}_{n['timestamp'][:16]}"
        if key not in seen_notifs:
            seen_notifs.add(key)
            events.append({"time": n["timestamp"], "ts": n["ts"], "type": "notification",
                           "label": f"Alert: {n['title']}", "severity": n["severity"], "icon": "bell"})

    # Related incidents
    for ri in related_incidents:
        events.append({"time": ri["timestamp"], "ts": ri["ts"], "type": "related_incident",
                       "label": f"Related: {ri['type']} ({ri['severity']})", "severity": ri["severity"], "icon": "flag"})

    # The main incident
    events.append({
        "time": incident.created_at.isoformat(), "ts": incident.created_at,
        "type": "incident_trigger",
        "label": f"Incident: {incident.incident_type.replace('_', ' ').title()} ({incident.severity})",
        "severity": incident.severity, "icon": "zap",
    })

    # Sort chronologically and strip internal ts
    events.sort(key=lambda e: e["ts"])
    return [{"time": e["time"], "type": e["type"], "label": e["label"],
             "severity": e["severity"], "icon": e["icon"]} for e in events]


# ── Frame builder ──

def _build_replay_frames(start, end, telemetry, anomalies, trail, events, risk_zones, env_snapshot):
    total_seconds = int((end - start).total_seconds())
    frames = []

    # Build lookup maps by timestamp (rounded to nearest 5s)
    def round_ts(dt):
        return dt.replace(second=dt.second - dt.second % FRAME_INTERVAL_S, microsecond=0)

    telem_map = {}
    for t in telemetry:
        key = round_ts(t["ts"]).isoformat()
        telem_map.setdefault(key, []).append(t)

    anom_map = {}
    for a in anomalies:
        key = round_ts(a["ts"]).isoformat()
        anom_map[key] = a["score"]

    trail_positions = [(t.get("ts", start), t["lat"], t["lng"], t.get("speed", 0))
                       for t in [dict(**tr, ts=datetime.fromisoformat(tr["timestamp"])) for tr in trail]
                       ] if trail else []

    # Latest known location
    last_lat = trail[0]["lat"] if trail else 12.9716
    last_lng = trail[0]["lng"] if trail else 77.5946
    last_speed = 0

    for sec in range(0, total_seconds, FRAME_INTERVAL_S):
        frame_time = start + timedelta(seconds=sec)
        frame_key = round_ts(frame_time).isoformat()

        # Interpolate location from trail
        for ts, lat, lng, spd in trail_positions:
            if ts <= frame_time:
                last_lat, last_lng, last_speed = lat, lng, spd

        # Get telemetry at this frame
        frame_telemetry = telem_map.get(frame_key, [])
        battery = None
        signal = None
        for ft in frame_telemetry:
            val = ft["value"]
            if ft["type"] == "heartbeat":
                battery = val.get("battery_level")
                signal = val.get("signal_strength")

        # Get anomaly score at this frame
        anomaly_score = anom_map.get(frame_key, 0)

        # Get events at this frame
        frame_events = [e for e in events
                        if e["time"][:19] >= frame_time.isoformat()[:19]
                        and e["time"][:19] < (frame_time + timedelta(seconds=FRAME_INTERVAL_S)).isoformat()[:19]]

        frames.append({
            "timestamp": frame_time.isoformat(),
            "elapsed_s": sec,
            "location": {"lat": last_lat, "lng": last_lng},
            "speed": last_speed,
            "battery": battery,
            "signal": signal,
            "anomaly_score": anomaly_score,
            "risk_overlay": {
                "location_risk": _compute_location_risk(last_lat, last_lng, risk_zones),
                "environment_risk": _compute_environment_risk(frame_time, env_snapshot),
                "behavior_score": round(anomaly_score * 10, 1) if anomaly_score else 0.0,
            },
            "events": [{"type": e["type"], "label": e["label"], "severity": e["severity"]} for e in frame_events],
        })

    return frames


# ── AI Narrative ──

async def generate_replay_narrative(session: AsyncSession, replay_data: dict) -> str:
    """Generate AI narrative for the incident replay using GPT-5.2."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return _template_narrative(replay_data)

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        events_text = "\n".join(
            f"  {e['time'][11:19]} — {e['label']}" for e in replay_data["events"]
        )

        prompt = f"""Analyze this incident and generate a concise, professional narrative.

Incident: {replay_data['incident_type'].replace('_', ' ').title()}
Device: {replay_data['device_identifier']}
Senior: {replay_data['senior_name']}
Severity: {replay_data['severity']}
Time: {replay_data['incident_time']}

Timeline of Events:
{events_text}

Stats: {replay_data['stats']['telemetry_points']} telemetry points, {replay_data['stats']['anomalies']} anomalies, {replay_data['stats']['notifications_sent']} notifications sent.

Write a 3-4 sentence analysis explaining:
1. What happened chronologically
2. What signals preceded the incident
3. How the system responded
Keep it factual and professional. No markdown formatting."""

        chat = LlmChat(
            api_key=api_key,
            session_id=f"replay-{uuid.uuid4().hex[:8]}",
            system_message="You are a safety intelligence analyst for NISCHINT, an elderly care monitoring platform. Provide concise, professional incident analysis.",
        ).with_model("openai", "gpt-5.2")

        from app.services.ai_metrics import track
        async with track("incident_replay_engine.summarize"):
            response = await chat.send_message(UserMessage(text=prompt))
        return response.text.strip()

    except Exception as e:
        logger.warning(f"AI narrative generation failed: {e}")
        return _template_narrative(replay_data)


def _template_narrative(data):
    """Fallback template narrative."""
    events = data.get("events", [])
    stats = data.get("stats", {})
    event_count = len(events)
    first_event = events[0]["label"] if events else "Unknown"
    last_event = events[-1]["label"] if events else "Unknown"

    return (
        f"Incident '{data['incident_type'].replace('_', ' ')}' occurred on device {data['device_identifier']} "
        f"({data['senior_name']}). The replay window captured {event_count} events and "
        f"{stats.get('telemetry_points', 0)} telemetry points. "
        f"The sequence began with '{first_event}' and culminated in '{last_event}'. "
        f"{stats.get('notifications_sent', 0)} notifications were dispatched to the guardian."
    )
