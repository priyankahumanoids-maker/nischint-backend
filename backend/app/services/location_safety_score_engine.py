# Location Safety Score Engine (Phase 40)
# Converts complex AI intelligence into a single trust metric (0-10).
# Architecture: Dynamic Risk Engine → Signal Normalization → Risk Index → Safety Score
#
# Score types: Location, Route, Journey
# Features: Percentile ranking, trend detection, signal breakdown

import logging
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Score Categories ──
CATEGORIES = [
    (8.0, "Very Safe", "very_safe"),
    (6.0, "Safe", "safe"),
    (4.0, "Moderate Risk", "moderate"),
    (2.0, "High Risk", "high"),
    (0.0, "Critical", "critical"),
]

WEIGHTS = {
    "zone_risk": 0.30,
    "dynamic_risk": 0.25,
    "incident_density": 0.20,
    "route_exposure": 0.15,
    "time_risk": 0.10,
}

RISK_PENALTY = {"CRITICAL": 2.0, "HIGH": 1.0, "MODERATE": 0.3, "SAFE": 0.0,
                "critical": 2.0, "high": 1.0, "moderate": 0.3, "safe": 0.0}
SEV_W = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}


def _normalize(value: float, min_val: float, max_val: float) -> float:
    if max_val <= min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def _classify(score: float) -> tuple[str, str]:
    for threshold, label, key in CATEGORIES:
        if score >= threshold:
            return label, key
    return "Critical", "critical"


def _haversine(lat1, lng1, lat2, lng2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _time_risk(hour: int) -> float:
    if 6 <= hour < 18:
        return 1.5
    if 18 <= hour < 21:
        return 4.5
    if 21 <= hour < 24:
        return 7.0
    return 8.5


# ── Data Fetchers ──

async def _fetch_zones(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(text(
        "SELECT latitude, longitude, radius_meters, risk_score, risk_level "
        "FROM location_risk_zones WHERE risk_type = 'learned_hotspot'"
    ))).fetchall()
    return [{"lat": float(r.latitude), "lng": float(r.longitude),
             "radius": float(r.radius_meters), "score": float(r.risk_score),
             "level": r.risk_level} for r in rows]


async def _fetch_incidents(session: AsyncSession, lat: float, lng: float, radius_km: float = 2.0) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    deg = radius_km / 111.0
    rows = (await session.execute(text(
        "SELECT li.latitude, li.longitude, li.severity, li.created_at "
        "FROM location_incidents li JOIN incidents i ON li.incident_id = i.id "
        "WHERE li.created_at >= :cutoff "
        "AND li.latitude BETWEEN :min_lat AND :max_lat "
        "AND li.longitude BETWEEN :min_lng AND :max_lng"
    ), {"cutoff": cutoff, "min_lat": lat - deg, "max_lat": lat + deg,
        "min_lng": lng - deg, "max_lng": lng + deg})).fetchall()
    return [{"lat": float(r.latitude), "lng": float(r.longitude),
             "severity": r.severity} for r in rows]


def _zone_risk_at(lat, lng, zones) -> float:
    best = 0.0
    for z in zones:
        d = _haversine(lat, lng, z["lat"], z["lng"])
        r = z["radius"] * 1.5
        if d <= r:
            best = max(best, z["score"] * (1 - d / r))
    return min(10.0, best)


def _dynamic_risk_at(lat, lng) -> float:
    from app.services.dynamic_risk_engine import get_live_heatmap
    hm = get_live_heatmap()
    if not hm or not hm.get("cells"):
        return 0.0
    best, md = 0.0, 0.006
    for c in hm["cells"]:
        d = abs(c["lat"] - lat) + abs(c["lng"] - lng)
        if d < md:
            md = d
            best = c["composite_score"]
    return min(10.0, best)


def _incident_density_at(lat, lng, incidents) -> float:
    total = 0.0
    for inc in incidents:
        d = _haversine(lat, lng, inc["lat"], inc["lng"])
        if d <= 1000:
            total += SEV_W.get(inc["severity"], 1.0) * (1 - d / 1000)
    return total


def _percentile(score: float) -> int:
    """Calculate percentile using Redis-cached grid scores with in-memory fallback."""
    from app.services.redis_service import get_safety_score_grid

    # Try Redis first
    try:
        grid = get_safety_score_grid()
        if grid:
            cell_scores = [round(10.0 - min(1.0, cs / 10.0) * 10.0, 1) for cs in grid]
            if cell_scores:
                return min(99, max(1, round(sum(1 for cs in cell_scores if cs < score) / len(cell_scores) * 100)))
    except Exception:
        pass

    # Fallback: read from dynamic risk engine directly
    from app.services.dynamic_risk_engine import get_live_heatmap
    hm = get_live_heatmap()
    if not hm or not hm.get("cells"):
        return 50
    cell_scores = [round(10.0 - min(1.0, c["composite_score"] / 10.0) * 10.0, 1) for c in hm["cells"]]
    if not cell_scores:
        return 50
    return min(99, max(1, round(sum(1 for cs in cell_scores if cs < score) / len(cell_scores) * 100)))


def _trend() -> str:
    from app.services.dynamic_risk_engine import get_heatmap_timeline
    tl = get_heatmap_timeline()
    if len(tl) < 2:
        return "stable"
    recent = tl[-3:] if len(tl) >= 3 else tl
    older = tl[-6:-3] if len(tl) >= 6 else tl[:max(1, len(tl) // 2)]

    def _score(entries):
        t = 0
        for e in entries:
            s = e.get("stats", {})
            t += s.get("critical", 0) * 4 + s.get("high", 0) * 3 + s.get("moderate", 0)
        return t / max(len(entries), 1)

    diff = _score(recent) - _score(older)
    if diff > 5:
        return "rising"
    if diff < -5:
        return "falling"
    return "stable"


def _compute_score(zone_risk, dynamic_risk, incident_density, route_exposure, time_risk):
    """Core scoring: normalize → weighted risk index → safety score."""
    norm = {
        "zone_risk": _normalize(zone_risk, 0, 10),
        "dynamic_risk": _normalize(dynamic_risk, 0, 10),
        "incident_density": _normalize(incident_density, 0, 20),
        "route_exposure": _normalize(route_exposure, 0, 10),
        "time_risk": _normalize(time_risk, 0, 10),
    }
    risk_index = sum(norm[k] * WEIGHTS[k] for k in WEIGHTS)
    score = round(max(0, min(10, 10 - risk_index * 10)), 1)
    return score, risk_index, norm


# ── Location Safety Score ──

async def calculate_location_score(session: AsyncSession, lat: float, lng: float) -> dict:
    hour = datetime.now(timezone.utc).hour
    zones = await _fetch_zones(session)
    incidents = await _fetch_incidents(session, lat, lng)

    zr = _zone_risk_at(lat, lng, zones)
    dr = _dynamic_risk_at(lat, lng)
    idens = _incident_density_at(lat, lng, incidents)
    tr = _time_risk(hour)

    score, ri, norm = _compute_score(zr, dr, idens, 0, tr)
    label, key = _classify(score)

    # Night score (with max time risk)
    ns, _, _ = _compute_score(zr, dr, idens, 0, 8.5)

    return {
        "score": score,
        "night_score": ns,
        "label": label,
        "category": key,
        "risk_index": round(ri, 3),
        "percentile": _percentile(score),
        "percentile_text": f"Safer than {_percentile(score)}% of nearby areas",
        "trend": _trend(),
        "signals": {
            "zone_risk": {"raw": round(zr, 2), "normalized": round(norm["zone_risk"], 3), "weight": WEIGHTS["zone_risk"]},
            "dynamic_risk": {"raw": round(dr, 2), "normalized": round(norm["dynamic_risk"], 3), "weight": WEIGHTS["dynamic_risk"]},
            "incident_density": {"raw": round(idens, 2), "normalized": round(norm["incident_density"], 3), "weight": WEIGHTS["incident_density"]},
            "route_exposure": {"raw": 0.0, "normalized": 0.0, "weight": WEIGHTS["route_exposure"]},
            "time_risk": {"raw": round(tr, 2), "normalized": round(norm["time_risk"], 3), "weight": WEIGHTS["time_risk"]},
        },
        "nearby_incidents": len(incidents),
        "nearby_zones": sum(1 for z in zones if _haversine(lat, lng, z["lat"], z["lng"]) <= z["radius"] * 1.5),
        "location": {"lat": lat, "lng": lng},
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Route Safety Score ──

async def calculate_route_score(session: AsyncSession, origin: dict, destination: dict) -> dict:
    hour = datetime.now(timezone.utc).hour
    zones = await _fetch_zones(session)
    cl = ((origin["lat"] + destination["lat"]) / 2, (origin["lng"] + destination["lng"]) / 2)
    incidents = await _fetch_incidents(session, cl[0], cl[1], radius_km=5.0)

    # Sample every 100m
    dist = _haversine(origin["lat"], origin["lng"], destination["lat"], destination["lng"])
    n = max(2, int(dist / 100))
    points = [{"lat": round(origin["lat"] + i / n * (destination["lat"] - origin["lat"]), 6),
               "lng": round(origin["lng"] + i / n * (destination["lng"] - origin["lng"]), 6)} for i in range(n + 1)]

    scores, zone_ids, max_risk, max_risk_val = [], set(), "safe", 0.0
    tr = _time_risk(hour)

    for pt in points:
        zr = _zone_risk_at(pt["lat"], pt["lng"], zones)
        dr = _dynamic_risk_at(pt["lat"], pt["lng"])
        idens = _incident_density_at(pt["lat"], pt["lng"], incidents)
        re = (zr * 0.5 + dr * 0.5)
        s, _, _ = _compute_score(zr, dr, idens, re, tr)
        scores.append(s)

        for z in zones:
            if _haversine(pt["lat"], pt["lng"], z["lat"], z["lng"]) <= z["radius"]:
                zone_ids.add(id(z))
                p = RISK_PENALTY.get(z["level"], 0)
                if p > max_risk_val:
                    max_risk_val = p
                    max_risk = z["level"]

    avg = round(sum(scores) / max(len(scores), 1), 1)
    label, key = _classify(avg)

    return {
        "score": avg,
        "min_score": round(min(scores) if scores else 0, 1),
        "label": label,
        "category": key,
        "percentile": _percentile(avg),
        "percentile_text": f"Safer than {_percentile(avg)}% of nearby routes",
        "trend": _trend(),
        "risk_zones_crossed": len(zone_ids),
        "max_risk": max_risk,
        "total_distance_m": round(dist),
        "sample_points": len(points),
        "point_scores": scores[:60],
        "origin": origin,
        "destination": destination,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Journey Safety Score ──

async def calculate_journey_score(session: AsyncSession, session_id: str) -> dict:
    from app.models.guardian import GuardianSession, GuardianAlert
    import uuid

    gs = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == uuid.UUID(session_id))
    )).scalar_one_or_none()
    if not gs:
        return {"error": "Session not found"}

    alerts = (await session.execute(
        select(GuardianAlert).where(GuardianAlert.session_id == gs.id)
    )).scalars().all()

    # Base route score
    base = 7.0
    rz = 0
    if gs.current_location and gs.destination:
        loc, dest = gs.current_location, gs.destination
        if isinstance(loc, dict) and "lat" in loc and isinstance(dest, dict) and "lat" in dest:
            rd = await calculate_route_score(session, loc, dest)
            base = rd["score"]
            rz = rd["risk_zones_crossed"]

    # Penalties
    sev = defaultdict(int)
    for a in alerts:
        sev[a.severity] += 1

    penalties = []
    if sev.get("critical", 0):
        penalties.append({"reason": "Critical alert triggered", "amount": -2.0, "count": sev["critical"]})
    if sev.get("high", 0):
        penalties.append({"reason": "High severity alert", "amount": -1.0, "count": sev["high"]})
    if sev.get("medium", 0):
        penalties.append({"reason": "Medium alert", "amount": -0.5, "count": sev["medium"]})
    if gs.route_deviated:
        penalties.append({"reason": "Route deviation detected", "amount": -0.5, "count": 1})
    rp = RISK_PENALTY.get(gs.risk_level or "safe", 0) * 0.5
    if rp > 0:
        penalties.append({"reason": f"Max risk: {gs.risk_level}", "amount": -rp, "count": 1})

    total_pen = sum(p["amount"] * p["count"] for p in penalties)
    final = round(max(0, min(10, base + total_pen)), 1)
    label, key = _classify(final)

    dur = 0.0
    if gs.ended_at and gs.started_at:
        dur = round((gs.ended_at - gs.started_at).total_seconds() / 60, 1)
    elif gs.started_at:
        dur = round((datetime.now(timezone.utc) - gs.started_at).total_seconds() / 60, 1)

    return {
        "score": final,
        "base_score": base,
        "label": label,
        "category": key,
        "penalties": penalties,
        "total_penalty": round(total_pen, 1),
        "session_id": session_id,
        "status": gs.status,
        "duration_minutes": dur,
        "max_risk_level": gs.risk_level,
        "alert_count": len(alerts),
        "alert_breakdown": dict(sev),
        "risk_zones_crossed": rz,
        "route_deviated": gs.route_deviated,
        "escalation_level": gs.escalation_level,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
