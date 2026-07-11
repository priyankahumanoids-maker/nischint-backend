# Geofence Context Intelligence — zone detection, timeline, AI context
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safe_zone import SafeZone
from app.models.location_trail import LocationTrailPoint

logger = logging.getLogger(__name__)

UNKNOWN_AREA_TIMEOUT_S = 180  # 3 minutes outside all zones → "unknown area"


# ── Schemas ──

class ZoneOut(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    radius_metres: float
    type: str
    child_currently_inside: bool
    child_entered_at_ist: Optional[str] = None
    child_exited_at_ist: Optional[str] = None
    distance_m: float = 0.0


class TimelineEvent(BaseModel):
    time_ist: str
    event: str
    label: str
    severity: str  # info | safe | notice | warning | critical


class ContextResponse(BaseModel):
    zones: list[ZoneOut]
    current_zone: Optional[dict] = None
    timeline: list[TimelineEvent]
    ai_context: str


# ── Helpers ──

def _haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _to_ist(dt: datetime) -> str:
    ist = dt + timedelta(hours=5, minutes=30)
    return ist.strftime("%-I:%M %p")


def derive_zone_type(zone) -> str:
    """Derive zone type from zone_type field or name."""
    zt = getattr(zone, 'zone_type', None) or getattr(zone, 'type', None) or ''
    if zt and zt not in ('custom', 'frequent', ''):
        # Map existing zone_type values to our 4 types
        zt_lower = zt.lower()
        if zt_lower in ('home', 'school', 'danger', 'frequent'):
            return zt_lower
        if zt_lower == 'care_facility':
            return 'frequent'
    name = (getattr(zone, 'name', '') or '').lower()
    if any(w in name for w in ['home', 'house']):
        return 'home'
    if any(w in name for w in ['school', 'college', 'university', 'campus']):
        return 'school'
    if any(w in name for w in ['danger', 'unsafe', 'avoid', 'restricted']):
        return 'danger'
    return 'frequent'


def _is_inside(lat, lng, zone_lat, zone_lng, radius_m):
    return _haversine_m(lat, lng, zone_lat, zone_lng) <= radius_m


async def compute_geofence_context(
    session: AsyncSession,
    user_id: str,
    share_token: str,
    current_lat: Optional[float],
    current_lng: Optional[float],
    route_deviated: bool = False,
    total_distance_m: float = 0.0,
    total_duration_min: int = 0,
) -> ContextResponse:
    """Compute geofence context: zones, timeline, AI interpretation."""

    # 1. Fetch all active safe zones for this user
    zones_db = (await session.execute(
        select(SafeZone).where(and_(SafeZone.user_id == user_id, SafeZone.active.is_(True)))
    )).scalars().all()

    # 2. Fetch trail points for timeline construction
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    trail_points = (await session.execute(
        select(LocationTrailPoint)
        .where(and_(LocationTrailPoint.share_token == share_token, LocationTrailPoint.recorded_at >= cutoff))
        .order_by(LocationTrailPoint.recorded_at.asc())
    )).scalars().all()

    # 3. Compute distance from current location to each zone, filter within 2km, take top 3
    zone_data = []
    for z in zones_db:
        dist = _haversine_m(current_lat, current_lng, z.lat, z.lng) if current_lat and current_lng else 99999
        zone_data.append((z, dist, derive_zone_type(z)))

    zone_data.sort(key=lambda x: x[1])
    nearby = [(z, d, t) for z, d, t in zone_data if d <= 2000][:3]

    # 4. For each nearby zone, check if child is inside and compute entry/exit times
    zones_out = []
    current_zone_info = None

    for z, dist, ztype in nearby:
        inside = dist <= z.radius_m
        entered_at = None
        exited_at = None

        # Walk trail to find entry/exit times for this zone
        was_inside_prev = False
        for pt in trail_points:
            pt_inside = _is_inside(pt.lat, pt.lng, z.lat, z.lng, z.radius_m)
            if pt_inside and not was_inside_prev:
                entered_at = pt.recorded_at
            if not pt_inside and was_inside_prev:
                exited_at = pt.recorded_at
            was_inside_prev = pt_inside

        if inside:
            current_zone_info = {"name": z.name, "type": ztype}

        zones_out.append(ZoneOut(
            id=str(z.id), name=z.name, lat=z.lat, lng=z.lng,
            radius_metres=z.radius_m, type=ztype,
            child_currently_inside=inside,
            child_entered_at_ist=_to_ist(entered_at) if entered_at else None,
            child_exited_at_ist=_to_ist(exited_at) if exited_at else None,
            distance_m=round(dist, 1),
        ))

    # 5. Build timeline from trail points + zone transitions
    timeline = _build_timeline(trail_points, zones_db, route_deviated)

    # 6. AI context interpretation
    ai_context = _compute_ai_context(
        current_zone_info, zones_out, timeline, route_deviated,
        total_distance_m, total_duration_min, trail_points,
    )

    return ContextResponse(
        zones=zones_out,
        current_zone=current_zone_info,
        timeline=timeline[-10:],  # max 10 events, most recent last
        ai_context=ai_context,
    )


def _build_timeline(
    trail_points: list[LocationTrailPoint],
    zones_db: list[SafeZone],
    route_deviated: bool,
) -> list[TimelineEvent]:
    """Build a timeline of zone entry/exit + movement events from trail points."""
    events: list[TimelineEvent] = []
    if not trail_points:
        return events

    # Track zone state per zone
    zone_state = {str(z.id): False for z in zones_db}
    outside_all_since = None
    in_stop = False

    for i, pt in enumerate(trail_points):
        pt_in_any_zone = False

        for z in zones_db:
            zid = str(z.id)
            inside = _is_inside(pt.lat, pt.lng, z.lat, z.lng, z.radius_m)
            ztype = derive_zone_type(z)

            if inside and not zone_state[zid]:
                # Entered zone
                zone_state[zid] = True
                pt_in_any_zone = True
                if ztype == 'danger':
                    events.append(TimelineEvent(
                        time_ist=_to_ist(pt.recorded_at), event="entered_danger_zone",
                        label=f"Entered danger zone: {z.name}", severity="critical",
                    ))
                elif ztype in ('home', 'school'):
                    events.append(TimelineEvent(
                        time_ist=_to_ist(pt.recorded_at), event=f"entered_{ztype}",
                        label=f"Arrived {z.name}", severity="safe",
                    ))
                else:
                    events.append(TimelineEvent(
                        time_ist=_to_ist(pt.recorded_at), event="entered_zone",
                        label=f"Entered {z.name}", severity="info",
                    ))
            elif not inside and zone_state[zid]:
                # Exited zone
                zone_state[zid] = False
                if ztype in ('home', 'school'):
                    events.append(TimelineEvent(
                        time_ist=_to_ist(pt.recorded_at), event=f"exited_{ztype}",
                        label=f"Left {z.name}", severity="info",
                    ))
                else:
                    events.append(TimelineEvent(
                        time_ist=_to_ist(pt.recorded_at), event="exited_zone",
                        label=f"Left {z.name}", severity="info",
                    ))

            if inside:
                pt_in_any_zone = True

        # Track time outside all zones
        if not pt_in_any_zone:
            if outside_all_since is None:
                outside_all_since = pt.recorded_at
            elif (pt.recorded_at - outside_all_since).total_seconds() >= UNKNOWN_AREA_TIMEOUT_S:
                if not any(e.event == "entered_unknown_area" and e.time_ist == _to_ist(outside_all_since) for e in events):
                    events.append(TimelineEvent(
                        time_ist=_to_ist(outside_all_since), event="entered_unknown_area",
                        label="Entered unknown area", severity="warning",
                    ))
        else:
            outside_all_since = None

        # Stop detection
        if pt.is_stop and not in_stop:
            in_stop = True
            # Count consecutive stops to estimate duration
            stop_count = sum(1 for j in range(i, min(i + 20, len(trail_points))) if trail_points[j].is_stop)
            stop_min = max(2, round(stop_count * 30 / 60))
            severity = "warning" if not pt_in_any_zone else "notice"
            events.append(TimelineEvent(
                time_ist=_to_ist(pt.recorded_at), event="stop_detected",
                label=f"Stopped ({stop_min} min)", severity=severity,
            ))
        elif not pt.is_stop and in_stop:
            in_stop = False
            events.append(TimelineEvent(
                time_ist=_to_ist(pt.recorded_at), event="resumed_movement",
                label="Resumed movement", severity="info",
            ))

    # Add route deviation event if applicable
    if route_deviated and trail_points:
        mid = trail_points[len(trail_points) // 2]
        if not any(e.event == "route_deviation" for e in events):
            events.append(TimelineEvent(
                time_ist=_to_ist(mid.recorded_at), event="route_deviation",
                label="Route deviation detected", severity="warning",
            ))

    events.sort(key=lambda e: e.time_ist)
    return events


def _compute_ai_context(
    current_zone: Optional[dict],
    zones_out: list[ZoneOut],
    timeline: list[TimelineEvent],
    route_deviated: bool,
    total_distance_m: float,
    total_duration_min: int,
    trail_points: list[LocationTrailPoint],
) -> str:
    """Generate AI context string based on geofence state."""

    # Check for specific states
    has_danger_entry = any(e.event == "entered_danger_zone" for e in timeline)
    arrived_home = current_zone and current_zone.get("type") == "home"
    in_known_zone = current_zone is not None
    has_stops_outside = any(e.severity == "warning" and e.event == "stop_detected" for e in timeline)
    has_unknown_area = any(e.event == "entered_unknown_area" for e in timeline)

    # Get last zone exit if any
    exits = [e for e in timeline if e.event.startswith("exited_")]
    last_exit_label = exits[-1].label if exits else None

    if has_danger_entry:
        return "Entered flagged area \u00b7 Immediate guardian attention \u00b7 Risk: HIGH"

    if arrived_home:
        dist_km = round(total_distance_m / 1000, 1) if total_distance_m else 0
        return f"Arrived home safely \u00b7 Journey complete \u00b7 Total: {dist_km} km in {total_duration_min} min"

    if has_stops_outside and not in_known_zone:
        stop_events = [e for e in timeline if e.event == "stop_detected"]
        stop_dur = stop_events[-1].label if stop_events else "unknown duration"
        return f"Stopped at location outside safe zones \u00b7 Duration: {stop_dur} \u00b7 Guardian attention recommended"

    if route_deviated and has_unknown_area:
        return f"{last_exit_label or 'Left zone'} \u00b7 Not on usual route \u00b7 Entered unfamiliar area"

    if route_deviated:
        return f"{last_exit_label or 'In transit'} \u00b7 Route deviation detected \u00b7 Not on expected path \u00b7 Guardian notified"

    if in_known_zone and any(e.event == "stop_detected" for e in timeline):
        return f"Stopped inside {current_zone['name']} \u00b7 Expected location \u00b7 No concern"

    if last_exit_label and not route_deviated:
        return f"{last_exit_label} at expected time \u00b7 Following normal route"

    if not trail_points:
        return "Tracking started \u00b7 Awaiting movement data"

    return "Moving normally \u00b7 Within expected area \u00b7 No anomalies detected"


async def broadcast_zone_events(
    timeline: list[TimelineEvent],
    user_name: str,
    token: str,
    user_id: str,
    zones_out: list[ZoneOut],
    already_broadcast: set,
):
    """Broadcast zone-based events to Command Centre. Uses already_broadcast set to deduplicate."""
    try:
        from app.api.ws_command_center import broadcast_to_command_center
        now = datetime.now(timezone.utc)

        for ev in timeline:
            event_key = f"{ev.event}:{ev.time_ist}"
            if event_key in already_broadcast:
                continue

            cc_event = None

            if ev.event.startswith("exited_") and ev.severity == "info":
                cc_event = {
                    "type": "safe_zone_exit",
                    "data": {"user_name": user_name, "user_id": user_id, "token": token,
                             "detail": f"{ev.label} \u00b7 {ev.time_ist} \u00b7 Now in transit", "severity": "info"},
                    "timestamp": now.isoformat(),
                }
            elif ev.event == "entered_unknown_area":
                nearest = min(zones_out, key=lambda z: z.distance_m) if zones_out else None
                dist_info = f"{int(nearest.distance_m)}m from nearest zone" if nearest else "No zones nearby"
                cc_event = {
                    "type": "unknown_area_entry",
                    "data": {"user_name": user_name, "user_id": user_id, "token": token,
                             "detail": f"Outside all safe zones \u00b7 {ev.time_ist} \u00b7 {dist_info}", "severity": "warning"},
                    "timestamp": now.isoformat(),
                }
            elif ev.event in ("entered_home", "entered_school"):
                zone_name = ev.label.replace("Arrived ", "")
                cc_event = {
                    "type": "safe_zone_arrival",
                    "data": {"user_name": user_name, "user_id": user_id, "token": token,
                             "detail": f"Entered {zone_name} zone \u00b7 {ev.time_ist} \u00b7 Journey complete", "severity": "safe"},
                    "timestamp": now.isoformat(),
                }
            elif ev.event == "entered_danger_zone":
                cc_event = {
                    "type": "danger_zone_entry",
                    "data": {"user_name": user_name, "user_id": user_id, "token": token,
                             "detail": f"{ev.label} \u00b7 {ev.time_ist} \u00b7 Immediate attention", "severity": "critical"},
                    "timestamp": now.isoformat(),
                }

            if cc_event:
                already_broadcast.add(event_key)
                await broadcast_to_command_center(cc_event)

    except Exception as e:
        logger.warning(f"Failed to broadcast zone events: {e}")
