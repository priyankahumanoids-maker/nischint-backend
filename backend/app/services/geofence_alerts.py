"""
Geofence Alerts — Guardian-controlled safety zones with emotionally designed notifications.

Philosophy (per product spec):
    This is NOT a tracking tool. It is a care-based safety communication system.
    All copy is human-first, reassuring, and family-centered.
    NO technical terms like "geofence breach", "threshold crossed", "event triggered".

State machine:
    SAFE       → distance <= radius_m
    WARNING    → radius_m * 0.85 < distance <= radius_m   (near-boundary, still inside)
    BREACH     → distance > radius_m
    RECOVERY   → was BREACH, now inside again

Cooldown:
    One BREACH notification per user per 60s window (Redis-backed).
    RECOVERY and SAFE updates are idempotent (fire only on state transition).
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import GuardianSession
from app.models.safe_zone import SafeZone
from app.models.monitored_route import MonitoredRoute
from app.models.user import User

__all__ = [
    "haversine_m",
    "evaluate_user_location",
    "record_protected_telemetry",
    "EMOTIONAL_COPY",
]

logger = logging.getLogger(__name__)

# ── Emotional notification copy (per product spec) ──
# Tokens: {name} = protected user's full name (e.g. "Aarav").
EMOTIONAL_COPY = {
    "safe":      "All safe — {name} is within the trusted care circle.",
    "moving":    "On the move — {name} is staying within the safe area.",
    "warning":   "Care boundary nearby — {name} is staying close to the safe zone.",
    "breach":    "Attention: {name} has stepped outside the safe care circle.",
    "alert_sent": "Family notified — tracking {name}'s live location.",
    "family_alerted": "Family alerted — support circle informed.",
    "recovery":  "Back in safe area — {name} is well again.",
}

WARNING_BAND_RATIO = 0.85   # within 85-100% of radius → warning (still inside)
BREACH_COOLDOWN_SEC = 60    # one breach notification per user per minute

# Redis namespaces
_NS_STATE = "geofence:state"       # namespace → last known state per user
_NS_COOL = "geofence:breach_cool"  # namespace → cooldown flag


GeoState = Literal["safe", "moving", "warning", "breach", "recovery"]


# ── Haversine (mandatory per spec) ──
def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in meters."""
    R = 6371_000.0  # earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlamb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlamb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@dataclass
class GeofenceEvaluation:
    state: GeoState
    message: str
    distance_m: float
    radius_m: float
    zone_id: str | None
    zone_name: str | None
    center_lat: float | None
    center_lng: float | None
    transition: bool  # True if state changed from the last recorded state
    breach_alert_fired: bool  # True if this call emitted a guardian notification


async def _load_active_zone(session: AsyncSession, user_id: str) -> SafeZone | None:
    """Return the most recently updated active zone for a user, if any.

    Redis cache (namespace `geofence:zone`, TTL 5min). Invalidated by
    `invalidate_zone_cache(user_id)` on zone create/update/delete.
    """
    from app.services.redis_service import get_json, set_json
    cached = get_json("geofence:zone", user_id)
    if cached and cached.get("exists") is False:
        return None
    if cached and cached.get("id"):
        # Re-hydrate a minimal SafeZone-like object from cache (id + lat/lng/radius/name)
        # so the caller gets the same attribute access. Full ORM object is only needed
        # by the create/update writers, never here.
        class _ZoneLite:
            def __init__(self, d):
                self.id = uuid.UUID(d["id"])
                self.name = d["name"]
                self.lat = d["lat"]
                self.lng = d["lng"]
                self.radius_m = d["radius_m"]
                self.active = True
                self.zone_type = d.get("zone_type", "custom")
        return _ZoneLite(cached)  # type: ignore[return-value]
    res = await session.execute(
        select(SafeZone)
        .where(SafeZone.user_id == uuid.UUID(user_id), SafeZone.active.is_(True))
        .order_by(SafeZone.created_at.desc())
        .limit(1)
    )
    zone = res.scalar_one_or_none()
    if zone:
        set_json("geofence:zone", user_id, {
            "id": str(zone.id),
            "name": zone.name,
            "lat": zone.lat,
            "lng": zone.lng,
            "radius_m": zone.radius_m,
            "zone_type": zone.zone_type,
        }, ttl=300)
    else:
        set_json("geofence:zone", user_id, {"exists": False}, ttl=300)
    return zone


def invalidate_zone_cache(user_id: str) -> None:
    """Called by the write endpoints whenever a user's active zone is mutated."""
    from app.services.redis_service import delete_key
    try:
        delete_key("geofence:zone", user_id)
    except Exception:
        pass


def clear_zone_runtime_state(user_id: str, zone_id: str) -> None:
    from app.services.redis_service import delete_key
    for namespace in (_NS_STATE, _NS_COOL):
        try:
            delete_key(namespace, f"{user_id}:{zone_id}")
        except Exception:
            pass


def clear_route_runtime_state(user_id: str, route_id: str) -> None:
    from app.services.redis_service import delete_key
    try:
        delete_key("geofence:route_state", f"{user_id}:{route_id}")
    except Exception:
        pass


def _distance_to_route_m(
    lat: float,
    lng: float,
    route: MonitoredRoute,
) -> float:
    """Shortest local-plane distance to the saved origin/destination segment."""
    mean_lat = math.radians((route.origin_lat + route.dest_lat + lat) / 3.0)
    metres_per_lat = 111_320.0
    metres_per_lng = max(1.0, 111_320.0 * math.cos(mean_lat))
    ax, ay = route.origin_lng * metres_per_lng, route.origin_lat * metres_per_lat
    bx, by = route.dest_lng * metres_per_lng, route.dest_lat * metres_per_lat
    px, py = lng * metres_per_lng, lat * metres_per_lat
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.001:
        return math.hypot(px - ax, py - ay)
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    closest_x, closest_y = ax + fraction * dx, ay + fraction * dy
    return math.hypot(px - closest_x, py - closest_y)


async def _get_user_name(session: AsyncSession, user_id: str) -> str:
    res = await session.execute(select(User.full_name, User.email).where(User.id == uuid.UUID(user_id)))
    row = res.first()
    if not row:
        return "Your loved one"
    name = row[0] or (row[1].split("@")[0] if row[1] else None) or "Your loved one"
    return name


async def record_protected_telemetry(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    *,
    battery_pct: int | None = None,
    accuracy_m: float | None = None,
    speed_mps: float | None = None,
    captured_at: datetime | None = None,
) -> dict:
    """Record a real protected-device snapshot for guardian dashboards.

    The snapshot is never synthesized: battery remains ``None`` when the
    native battery API has no reading. Redis keeps the latest passive value,
    while an existing active GuardianSession receives the same snapshot so
    current staging dashboards continue to work if Redis is unavailable.
    """
    from app.services.redis_service import mark_user_ping, set_json

    now = datetime.now(timezone.utc)
    observed_at = captured_at or now
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    else:
        observed_at = observed_at.astimezone(timezone.utc)
    # A device clock too far in the future must not make an offline member look
    # perpetually live. Server receipt time is the safe upper bound.
    if observed_at > now:
        observed_at = now
    observation_age_s = max(0.0, (now - observed_at).total_seconds())

    # Persist one authoritative latest-known coordinate on the User row. This
    # survives Redis expiry/restarts and is the source Guardian screens can use
    # when a protected phone is temporarily offline. Delayed queue replay must
    # never replace a newer point.
    user_row = (
        await session.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
    ).scalar_one_or_none()
    accepted_as_latest = True
    if user_row is not None and user_row.last_known_at is not None:
        previous_at = user_row.last_known_at
        if previous_at.tzinfo is None:
            previous_at = previous_at.replace(tzinfo=timezone.utc)
        else:
            previous_at = previous_at.astimezone(timezone.utc)
        accepted_as_latest = observed_at >= previous_at

    is_current = observation_age_s <= 120 and accepted_as_latest
    normalized_battery = (
        int(battery_pct)
        if battery_pct is not None and 0 <= int(battery_pct) <= 100
        else None
    )
    snapshot = {
        "lat": float(lat),
        "lng": float(lng),
        "battery_pct": normalized_battery,
        "accuracy_m": float(accuracy_m) if accuracy_m is not None else None,
        "speed_mps": float(speed_mps) if speed_mps is not None else None,
        "updated_at": observed_at.isoformat(),
        "received_at": now.isoformat(),
        "is_current": is_current,
        "accepted_as_latest": accepted_as_latest,
        "source": "protected_device",
    }

    if not accepted_as_latest:
        # Keep the newer Redis/DB/session/SSE state untouched. The caller marks
        # this response stale and will not replay geofence transitions.
        snapshot["latest_preserved"] = True
        return snapshot

    if user_row is not None:
        user_row.last_known_lat = float(lat)
        user_row.last_known_lng = float(lng)
        user_row.last_known_at = observed_at

    set_json("protected_telemetry", user_id, snapshot, ttl=24 * 60 * 60)
    mark_user_ping(user_id, observed_at.isoformat())

    active_result = await session.execute(
        select(GuardianSession)
        .where(
            GuardianSession.user_id == uuid.UUID(user_id),
            GuardianSession.status == "active",
        )
        .order_by(GuardianSession.started_at.desc())
        .limit(1)
    )
    active_session = active_result.scalar_one_or_none()
    if active_session:
        current = (
            dict(active_session.current_location)
            if isinstance(active_session.current_location, dict)
            else {}
        )
        current.update(snapshot)
        active_session.current_location = current
        active_session.previous_update_at = observed_at
        if speed_mps is not None:
            active_session.speed_mps = max(0.0, float(speed_mps))

    if is_current and normalized_battery is not None and normalized_battery <= 20:
        try:
            from app.services.alert_trigger import trigger_alert

            await trigger_alert(
                session,
                kind="low_battery",
                user_id=user_id,
                severity="high" if normalized_battery <= 10 else "medium",
                message=f"Protected device battery is {normalized_battery}%.",
                details=(
                    "Battery level came from the protected phone's native "
                    "battery service with its latest GPS update."
                ),
                location={"lat": float(lat), "lng": float(lng)},
                sse_event_type="device_low_battery",
                sse_payload_extras={
                    "battery": normalized_battery,
                    "battery_pct": normalized_battery,
                    "source": "phone_battery_service",
                },
                idempotency_key="phone-battery-low",
                cooldown_s=60 * 60,
            )
        except Exception:
            # Location/geofence ingestion must remain available even when the
            # alert transport is temporarily degraded.
            pass

    # Fan the same real protected-device snapshot to every linked guardian
    # and co-guardian. This is an SSE state update, not a noisy system push;
    # system notifications remain reserved for safety transitions.
    try:
        from app.services.event_broadcaster import broadcaster

        guardian_ids = await _resolve_guardian_ids(session, user_id)
        child_name = await _get_user_name(session, user_id)
        live_payload = {
            "type": "LOCATION_UPDATE",
            "event_type": "location_update",
            "child_id": user_id,
            "user_id": user_id,
            "child_name": child_name,
            "lat": snapshot["lat"],
            "lng": snapshot["lng"],
            "battery": normalized_battery,
            "battery_pct": normalized_battery,
            "accuracy_m": snapshot["accuracy_m"],
            "speed_mps": snapshot["speed_mps"],
            "timestamp": snapshot["updated_at"],
            "updated_at": snapshot["updated_at"],
            "source": "protected_device",
        }
        if active_session:
            live_payload["session_id"] = str(active_session.id)
        for guardian_id in guardian_ids:
            await broadcaster.broadcast_to_user(
                guardian_id,
                "location_update",
                live_payload,
            )
    except Exception as exc:
        logger.warning(
            "[PROTECTED_TELEMETRY] live guardian fan-out skipped user=%s: %s",
            user_id,
            exc,
        )

    return snapshot


def _compute_state(distance_m: float, radius_m: float, prev_state: GeoState | None) -> GeoState:
    if distance_m > radius_m:
        return "breach"
    # Inside or on boundary
    if distance_m > radius_m * WARNING_BAND_RATIO:
        return "warning"
    # Safely inside
    if prev_state == "breach":
        return "recovery"
    return "safe"


async def _resolve_guardian_ids(session: AsyncSession, child_user_id: str) -> list[str]:
    """Resolve all guardian user_ids linked to a protected member.

    Redis cache (namespace `geofence:guardians`, TTL 10min).
    """
    from app.services.redis_service import get_json, set_json
    cached = get_json("geofence:guardians", child_user_id)
    if cached is not None and isinstance(cached, dict) and "ids" in cached:
        return cached["ids"]

    guardian_ids: list[str] = []
    seen: set[str] = set()

    child = (
        await session.execute(
            select(User).where(User.id == uuid.UUID(child_user_id))
        )
    ).scalar_one_or_none()

    # Source 0: direct primary guardian link.
    if child and child.guardian_id:
        gid = str(child.guardian_id)
        seen.add(gid)
        guardian_ids.append(gid)

    # Source 1: Guardian table (email-based)
    from app.models.guardian import Guardian
    g_rows = await session.execute(
        select(Guardian).where(Guardian.user_id == uuid.UUID(child_user_id), Guardian.is_active.is_(True))
    )
    for gc in g_rows.scalars().all():
        if gc.email:
            gu = await session.execute(select(User.id).where(User.email == gc.email))
            guid = gu.scalar_one_or_none()
            if guid and str(guid) not in seen:
                seen.add(str(guid))
                guardian_ids.append(str(guid))
    # Source 2: Relationship table (code-based)
    try:
        from app.models.relationship import Relationship
        rel_rows = await session.execute(
            select(Relationship).where(
                Relationship.child_id == uuid.UUID(child_user_id),
                Relationship.status == "accepted",
            )
        )
        for rel in rel_rows.scalars().all():
            gid = str(rel.guardian_id)
            if gid not in seen:
                seen.add(gid)
                guardian_ids.append(gid)
    except Exception:
        pass

    # Source 3: Guardian Network share-invite links (co-parent/co-guardian).
    try:
        from app.models.guardian_network import GuardianRelationship
        network_rows = await session.execute(
            select(GuardianRelationship).where(
                GuardianRelationship.user_id == uuid.UUID(child_user_id),
                GuardianRelationship.guardian_user_id.isnot(None),
                GuardianRelationship.is_active.is_(True),
            )
        )
        for rel in network_rows.scalars().all():
            gid = str(rel.guardian_user_id)
            if gid not in seen:
                seen.add(gid)
                guardian_ids.append(gid)
    except Exception:
        pass
    try:
        set_json("geofence:guardians", child_user_id, {"ids": guardian_ids}, ttl=600)
    except Exception:
        pass
    return guardian_ids


def invalidate_guardian_cache(child_user_id: str) -> None:
    from app.services.redis_service import delete_key
    try:
        delete_key("geofence:guardians", child_user_id)
    except Exception:
        pass


async def evaluate_user_location(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
) -> GeofenceEvaluation:
    """Evaluate every active zone and route assigned to this protected user."""
    from app.services.redis_service import get_json, set_json, delete_key
    from app.services.event_broadcaster import broadcaster
    from app.services.alert_trigger import trigger_alert

    zones = (
        await session.execute(
            select(SafeZone)
            .where(
                SafeZone.user_id == uuid.UUID(user_id),
                SafeZone.active.is_(True),
            )
            .order_by(SafeZone.created_at.asc())
        )
    ).scalars().all()
    routes = (
        await session.execute(
            select(MonitoredRoute)
            .where(
                MonitoredRoute.user_id == uuid.UUID(user_id),
                MonitoredRoute.active.is_(True),
            )
            .order_by(MonitoredRoute.created_at.asc())
        )
    ).scalars().all()

    if not zones and not routes:
        return GeofenceEvaluation(
            state="safe",
            message="",
            distance_m=0.0,
            radius_m=0.0,
            zone_id=None,
            zone_name=None,
            center_lat=None,
            center_lng=None,
            transition=False,
            breach_alert_fired=False,
        )

    name = await _get_user_name(session, user_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    assignment_states: list[dict] = []
    any_transition = False
    any_alert = False

    for zone in zones:
        zone_id = str(zone.id)
        state_key = f"{user_id}:{zone_id}"
        distance_m = haversine_m(lat, lng, zone.lat, zone.lng)
        is_restricted = zone.zone_type == "restricted"
        inside = distance_m <= zone.radius_m
        state = (
            "restricted_inside" if is_restricted and inside
            else "restricted_clear" if is_restricted
            else "safe" if inside
            else "breach"
        )
        previous = get_json(_NS_STATE, state_key) or {}
        transition = previous.get("state") != state
        payload = {
            "user_id": user_id, "child_id": user_id, "user_name": name,
            "state": state, "zone_id": zone_id, "zone_name": zone.name,
            "zone_category": "restricted" if is_restricted else "safe",
            "distance_m": round(distance_m, 1), "radius_m": zone.radius_m,
            "center_lat": zone.lat, "center_lng": zone.lng,
            "lat": lat, "lng": lng, "updated_at": now_iso,
        }
        set_json(_NS_STATE, state_key, payload, ttl=None)
        assignment_states.append(payload)
        any_transition = any_transition or transition

        if transition:
            await broadcaster.broadcast_to_user(user_id, "geofence_status", payload)
            alert_kind = None
            alert_event = None
            alert_message = None
            details = None
            if not is_restricted and not inside:
                alert_kind, alert_event = "geofence_breach", "geofence_breach"
                alert_message = f"{name} left safe zone {zone.name}."
                details = f"Currently {round(distance_m)} metres from the zone centre."
            elif not is_restricted and inside and previous.get("state") == "breach":
                alert_kind, alert_event = "geofence_recovery", "geofence_recovery"
                alert_message = f"{name} returned to safe zone {zone.name}."
                details = "The latest protected-device GPS fix is back inside the saved area."
            elif is_restricted and inside:
                alert_kind, alert_event = "geofence_breach", "geofence_breach"
                alert_message = f"{name} entered restricted zone {zone.name}."
                details = "The latest protected-device GPS fix is inside this restricted area."
            elif is_restricted and not inside and previous.get("state") == "restricted_inside":
                alert_kind, alert_event = "geofence_recovery", "geofence_recovery"
                alert_message = f"{name} left restricted zone {zone.name}."
                details = "The latest protected-device GPS fix is now outside this restricted area."
            if alert_kind and alert_message:
                try:
                    result = await trigger_alert(
                        session, kind=alert_kind, user_id=user_id,
                        severity="high" if alert_kind == "geofence_breach" else "low",
                        message=alert_message, details=details,
                        location={"lat": lat, "lng": lng},
                        sse_event_type=alert_event,
                        sse_payload_extras={**payload, "message": alert_message},
                        idempotency_key=f"{zone_id}:{state}", cooldown_s=BREACH_COOLDOWN_SEC,
                        suppress_co_located=False,
                    )
                    any_alert = any_alert or result.dispatched
                except Exception as exc:
                    logger.warning("[GEOFENCE] zone alert failed zone=%s: %s", zone_id, exc)

    for route in routes:
        route_id = str(route.id)
        state_key = f"{user_id}:{route_id}"
        distance_m = _distance_to_route_m(lat, lng, route)
        state = "on_route" if distance_m <= route.corridor_width_m else "route_deviation"
        previous = get_json("geofence:route_state", state_key) or {}
        transition = previous.get("state") != state
        payload = {
            "user_id": user_id, "child_id": user_id, "user_name": name,
            "state": state, "route_id": route_id, "route_name": route.name,
            "distance_m": round(distance_m, 1),
            "corridor_width_m": route.corridor_width_m,
            "lat": lat, "lng": lng, "updated_at": now_iso,
        }
        set_json("geofence:route_state", state_key, payload, ttl=None)
        assignment_states.append(payload)
        any_transition = any_transition or transition
        if transition and (
            state == "route_deviation" or
            (state == "on_route" and previous.get("state") == "route_deviation")
        ):
            is_recovery = state == "on_route"
            alert_kind = "route_recovery" if is_recovery else "route_deviation"
            alert_message = (
                f"{name} returned to monitored route {route.name}."
                if is_recovery
                else f"{name} moved outside monitored route {route.name}."
            )
            try:
                result = await trigger_alert(
                    session, kind=alert_kind, user_id=user_id,
                    severity="low" if is_recovery else "high",
                    message=alert_message,
                    details=(
                        "The latest protected-device GPS fix is back inside the saved route corridor."
                        if is_recovery
                        else f"Latest GPS fix is {round(distance_m)} metres from the saved route corridor."
                    ),
                    location={"lat": lat, "lng": lng},
                    sse_event_type=alert_kind,
                    sse_payload_extras={**payload, "message": alert_message},
                    idempotency_key=f"{route_id}:{state}", cooldown_s=BREACH_COOLDOWN_SEC,
                    suppress_co_located=False,
                )
                any_alert = any_alert or result.dispatched
            except Exception as exc:
                logger.warning("[GEOFENCE] route alert failed route=%s: %s", route_id, exc)

    priority = next(
        (item for item in assignment_states if item["state"] in ("restricted_inside", "route_deviation", "breach")),
        assignment_states[0],
    )
    set_json(_NS_STATE, user_id, {**priority, "assignments": assignment_states}, ttl=3600)
    return GeofenceEvaluation(
        state="breach" if priority["state"] in ("restricted_inside", "route_deviation", "breach") else "safe",
        message=str(priority.get("message") or ""),
        distance_m=float(priority.get("distance_m") or 0),
        radius_m=float(priority.get("radius_m") or priority.get("corridor_width_m") or 0),
        zone_id=priority.get("zone_id") or priority.get("route_id"),
        zone_name=priority.get("zone_name") or priority.get("route_name"),
        center_lat=priority.get("center_lat"), center_lng=priority.get("center_lng"),
        transition=any_transition, breach_alert_fired=any_alert,
    )


async def evaluate_environmental_hazard(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
) -> dict:
    """Notify guardians when a real external hazard overlaps this GPS fix.

    NDMA/SACHET and OpenWeather remain explicitly labelled area signals.
    They never claim to have detected a personal fall or incident.
    """
    from app.services.env_hazard_matcher import match_env_hazards

    env = await match_env_hazards(lat, lng)
    strongest = env.get("strongest")
    if not env.get("matched") or not strongest:
        return env

    source = str(strongest.get("source") or "external").lower()
    source_label = (
        "NDMA/SACHET"
        if source == "ndma_sachet"
        else "OpenWeather"
        if source == "openweather"
        else source.replace("_", " ").upper()
    )
    title = str(strongest.get("title") or strongest.get("type") or "Safety warning")
    severity_name = str(strongest.get("severity") or "unknown").lower()
    severity = "critical" if severity_name == "extreme" else "high"
    state = env.get("state")
    message = (
        f"{source_label} area warning near the protected member"
        f"{f' in {state}' if state else ''}: {title}"
    )

    try:
        from app.services.alert_trigger import trigger_alert
        result = await trigger_alert(
            session,
            kind="environmental_hazard",
            user_id=user_id,
            severity=severity,
            message=message,
            details=(
                "External area alert matched against the protected member's "
                "latest real GPS fix; it is not a personal incident detection."
            ),
            location={"lat": lat, "lng": lng},
            sse_event_type="environmental_hazard",
            sse_payload_extras={
                "hazard_source": source,
                "hazard_title": title,
                "hazard_severity": severity_name,
                "state": state,
                "hazards": env.get("hazards") or [],
            },
            idempotency_key=f"{source}:{state or 'unknown'}:{title}",
            cooldown_s=1800,
        )
        env["guardian_alert_dispatched"] = result.dispatched
        env["guardian_alert_id"] = result.alert_id
    except Exception:
        env["guardian_alert_dispatched"] = False
    return env
