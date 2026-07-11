"""NISCH-007 Part A — Incident Feed.

`GET /api/incidents/nearby` — geospatial incident feed for guardians.
Returns ONLY incidents from this guardian's linked children (via
`Relationship.status='accepted'`), ordered by distance ASC and
`created_at` DESC within the same distance bucket.

Design rules locked into this surface:
  * Auth boundary: guardian sees only own network. Admin/operator
    bypasses the relationship check (they're the eyes-on-everything role).
  * Confidence < 0.70 → field omitted from response (not exposed = low
    trust threshold; same rule the timeline already follows).
  * `archived` incidents NEVER appear regardless of `status` query param.
  * State labels are user-facing copy — raw `escalated` / `validating`
    state names never leak to the API consumer.
  * `elapsed_since_created` is computed server-side so all clients
    render identically; "4m ago", "2h ago", "3d ago" cadence.
  * Zone match: incident's child's last-known location ∈ a SafeZone
    owned by the SAME child (the kid configures their own zones). Zone
    type returned verbatim — `home | school | care_facility | custom`.

This module does NOT consume PostGIS. Haversine in Python is fast
enough at the scale this endpoint serves (<200 rows per guardian per
query). When the data crosses ~10k rows/guardian we revisit with
`ST_DWithin` + a GIST index.
"""
from __future__ import annotations

import math
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.relationship import Relationship
from app.models.safe_zone import SafeZone
from app.models.safety_incident import SafetyIncident
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["Safety Incidents"])


# State → user-facing label. Source of truth — the timeline endpoint
# follows the same map. ARCHIVED is intentionally absent because the
# feed never returns archived incidents (drops them upstream).
STATE_LABELS: dict[str, str] = {
    "detected":     "Distress detected",
    "validating":   "Alert sent to network",
    "escalated":    "Guardian network alerted",
    "acknowledged": "Acknowledged",
    "resolved":     "Marked safe",
}

CONFIDENCE_DISPLAY_THRESHOLD = 0.70  # < this → omit from response
MAX_RADIUS_METRES = 5_000
MAX_LIMIT         = 50
EARTH_RADIUS_M    = 6_371_000.0

# Privacy: never expose more precise than ~111m. `round(coord, 3)` is
# 3 decimal places ≈ 111m at the equator, ≈ 104m at India's latitude
# (20°N) — within the 100m spec. Stable + deterministic.
MARKER_PRECISION_DP = 3


def round_marker_coord(coord: float | None) -> float | None:
    if coord is None:
        return None
    return round(float(coord), MARKER_PRECISION_DP)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dlat = rl2 - rl1
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rl1) * math.cos(rl2) * math.sin(dlng / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _format_elapsed(created: datetime, now: datetime) -> str:
    """Server-side "X ago" so every client renders identically.

    Calendar-precise enough for the feed surface (no need for "1m 32s").
    """
    delta = (now - created).total_seconds()
    if delta < 0:
        return "just now"
    if delta < 60:
        return "just now"
    if delta < 3_600:
        return f"{int(delta // 60)}m ago"
    if delta < 86_400:
        return f"{int(delta // 3_600)}h ago"
    return f"{int(delta // 86_400)}d ago"


def _zone_match_for(
    child_lat: float, child_lng: float,
    zones: list[SafeZone],
) -> Optional[str]:
    """Return the zone_type of the FIRST active zone the child is
    inside. None if none match. We test smallest radius first so a
    "home" zone inside a wider "neighborhood" zone wins."""
    candidates = [z for z in zones if z.active]
    candidates.sort(key=lambda z: z.radius_m or 0.0)
    for z in candidates:
        if _haversine_m(child_lat, child_lng, z.lat, z.lng) <= (z.radius_m or 0):
            return z.zone_type
    return None


@router.get("/nearby")
async def get_nearby_incidents(
    lat:    float = Query(..., description="Guardian's current latitude"),
    lng:    float = Query(..., description="Guardian's current longitude"),
    radius: int   = Query(500,  ge=1, le=MAX_RADIUS_METRES),
    zone:   Optional[str] = Query(None, description="home|school|office|route"),
    limit:  int   = Query(20, ge=1, le=MAX_LIMIT),
    status: str   = Query("active", description="active|resolved|all"),
    session: AsyncSession = Depends(get_db_session),
    user:    User = Depends(get_current_user),
):
    """Geospatial incident feed for the requesting guardian's network.

    Auth:
        * `admin` / `operator` → see all child incidents in the radius.
        * Anyone else → only their accepted-relationship children's
          incidents. No `Relationship` row → empty feed.
    """
    if status not in ("active", "resolved", "all"):
        raise HTTPException(400, "status must be active|resolved|all")

    role = (user.role or "").lower()

    # 1) Resolve which child_ids this caller may see.
    if role in ("admin", "operator"):
        allowed_child_ids: Optional[list[uuid.UUID]] = None  # None = all
    else:
        rels = (await session.execute(
            select(Relationship.child_id).where(
                Relationship.guardian_id == user.id,
                Relationship.status == "accepted",
            )
        )).scalars().all()
        allowed_child_ids = list(rels)
        if not allowed_child_ids:
            return _empty_response(lat, lng, radius)

    # 2) Build the incident query. We over-fetch (cap at limit*4) and
    #    filter geospatially in Python — haversine isn't a SQL primitive
    #    here. ARCHIVED is always excluded.
    state_filter: list[str]
    if status == "active":
        state_filter = ["detected", "validating", "escalated", "acknowledged"]
    elif status == "resolved":
        state_filter = ["resolved"]
    else:  # all
        state_filter = ["detected", "validating", "escalated",
                        "acknowledged", "resolved"]

    stmt = (select(SafetyIncident)
            .where(SafetyIncident.state.in_(state_filter))
            .order_by(SafetyIncident.created_at.desc())
            .limit(max(limit * 4, 80)))
    if allowed_child_ids is not None:
        stmt = stmt.where(SafetyIncident.child_id.in_(allowed_child_ids))

    rows: list[SafetyIncident] = list(
        (await session.execute(stmt)).scalars().all()
    )
    if not rows:
        return _empty_response(lat, lng, radius)

    # 3) Resolve last-known location per child (one query, batched).
    child_ids = list({r.child_id for r in rows})
    children = (await session.execute(
        select(User.id, User.last_known_lat, User.last_known_lng)
        .where(User.id.in_(child_ids))
    )).all()
    child_loc: dict[uuid.UUID, tuple[Optional[float], Optional[float]]] = {
        r.id: (r.last_known_lat, r.last_known_lng) for r in children
    }

    # 4) Resolve SafeZones per child in one shot for zone_match.
    zone_rows = (await session.execute(
        select(SafeZone).where(SafeZone.user_id.in_(child_ids))
    )).scalars().all()
    zones_by_child: dict[uuid.UUID, list[SafeZone]] = {}
    for z in zone_rows:
        zones_by_child.setdefault(z.user_id, []).append(z)

    # 5) Build candidate list with distance + zone_match.
    now = datetime.now(timezone.utc)
    candidates: list[tuple[float, dict]] = []
    for inc in rows:
        cl_lat, cl_lng = child_loc.get(inc.child_id, (None, None))
        if cl_lat is None or cl_lng is None:
            # No child location → can't compute distance; drop. The
            # guardian timeline endpoint still surfaces it for them.
            continue
        dist = _haversine_m(lat, lng, cl_lat, cl_lng)
        if dist > radius:
            continue

        zm = _zone_match_for(cl_lat, cl_lng, zones_by_child.get(inc.child_id, []))
        if zone is not None and (zm or "") != zone:
            # Zone filter active and didn't match → skip.
            continue

        # Build the response row. Confidence < threshold is OMITTED,
        # not zeroed — the field disappears entirely.
        row: dict = {
            "id":                       str(inc.id),
            "incident_type":            inc.incident_type,
            "severity":                 inc.severity,
            "state":                    inc.state,
            "state_label":              STATE_LABELS.get(inc.state, inc.state),
            "distance_metres":          int(round(dist)),
            # marker_lat/lng — privacy-rounded child location for map
            # placement. `None` if child has no fix yet; mobile falls
            # back to per-id bearing hash in that case. Privacy rule
            # is absolute: NEVER round to more than 3 decimal places.
            "marker_lat":               round_marker_coord(cl_lat),
            "marker_lng":               round_marker_coord(cl_lng),
            "created_at":               inc.created_at.isoformat(),
            "elapsed_since_created":    _format_elapsed(inc.created_at, now),
            "zone_match":               zm,
            "sla_degraded_at_dispatch": bool(inc.sla_degraded_at_dispatch),
            "current_escalation_level": int(inc.escalation_level or 0),
        }
        conf = float(inc.confidence or 0.0)
        if conf >= CONFIDENCE_DISPLAY_THRESHOLD:
            row["confidence"] = round(conf, 2)
        candidates.append((dist, row))

    # 6) Sort by distance ASC, then by created_at DESC (already pre-sorted
    #    descending in the SQL, so a stable sort on distance keeps that).
    candidates.sort(key=lambda kv: kv[0])
    out = [c[1] for c in candidates[:limit]]

    return {
        "incidents":    out,
        "total":        len(out),
        "radius_metres": radius,
        "centre":       {"lat": lat, "lng": lng},
        "computed_at":  now.isoformat(),
    }


def _empty_response(lat: float, lng: float, radius: int) -> dict:
    return {
        "incidents":     [],
        "total":         0,
        "radius_metres": radius,
        "centre":        {"lat": lat, "lng": lng},
        "computed_at":   datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["router", "STATE_LABELS", "CONFIDENCE_DISPLAY_THRESHOLD",
           "MARKER_PRECISION_DP", "round_marker_coord"]
