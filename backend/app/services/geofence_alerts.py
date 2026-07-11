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

import math
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safe_zone import SafeZone
from app.models.user import User

__all__ = [
    "haversine_m",
    "evaluate_user_location",
    "EMOTIONAL_COPY",
]

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


async def _get_user_name(session: AsyncSession, user_id: str) -> str:
    res = await session.execute(select(User.full_name, User.email).where(User.id == uuid.UUID(user_id)))
    row = res.first()
    if not row:
        return "Your loved one"
    name = row[0] or (row[1].split("@")[0] if row[1] else None) or "Your loved one"
    return name


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
    """Resolve all guardian user_ids linked to a child via Guardian table + Relationship table.

    Redis cache (namespace `geofence:guardians`, TTL 10min).
    """
    from app.services.redis_service import get_json, set_json
    cached = get_json("geofence:guardians", child_user_id)
    if cached is not None and isinstance(cached, dict) and "ids" in cached:
        return cached["ids"]

    guardian_ids: list[str] = []
    # Source 1: Guardian table (email-based)
    from app.models.guardian import Guardian
    g_rows = await session.execute(
        select(Guardian).where(Guardian.user_id == uuid.UUID(child_user_id), Guardian.is_active.is_(True))
    )
    for gc in g_rows.scalars().all():
        if gc.email:
            gu = await session.execute(select(User.id).where(User.email == gc.email))
            guid = gu.scalar_one_or_none()
            if guid:
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
            if gid not in guardian_ids:
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
    """
    Evaluate a user's location against their active safety zone.
    Emits SSE events with emotionally-designed copy when state transitions.
    Applies a 60s cooldown on BREACH notifications to prevent spam.
    """
    from app.services.redis_service import get_json, set_json, delete_key
    from app.services.event_broadcaster import broadcaster

    zone = await _load_active_zone(session, user_id)

    # No zone configured → nothing to evaluate. Return neutral.
    if zone is None:
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

    distance_m = haversine_m(lat, lng, zone.lat, zone.lng)
    prev = get_json(_NS_STATE, user_id) or {}
    prev_state: GeoState | None = prev.get("state")  # type: ignore[assignment]
    new_state = _compute_state(distance_m, zone.radius_m, prev_state)

    transition = prev_state != new_state
    name = await _get_user_name(session, user_id)
    message = EMOTIONAL_COPY[new_state].format(name=name)

    # Persist current state (always — for live dashboard reads)
    set_json(
        _NS_STATE,
        user_id,
        {
            "state": new_state,
            "distance_m": round(distance_m, 1),
            "radius_m": zone.radius_m,
            "zone_id": str(zone.id),
            "zone_name": zone.name,
            "lat": lat,
            "lng": lng,
            "center_lat": zone.lat,
            "center_lng": zone.lng,
            "message": message,
            "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        },
        ttl=3600,  # 1h — refreshed on every update
    )

    breach_alert_fired = False
    payload_common = {
        "user_id": user_id,
        "user_name": name,
        "state": new_state,
        "message": message,
        "distance_m": round(distance_m, 1),
        "radius_m": zone.radius_m,
        "zone_id": str(zone.id),
        "zone_name": zone.name,
        "center_lat": zone.lat,
        "center_lng": zone.lng,
        "lat": lat,
        "lng": lng,
    }

    # Emit SSE events only on transitions OR on breach (with cooldown)
    if transition:
        # Always notify the protected user themselves so the mobile app reflects current state
        try:
            await broadcaster.broadcast_to_user(user_id, "geofence_status", payload_common)
        except Exception:
            pass

        # On BREACH: apply 60s cooldown, notify guardians only once per window.
        if new_state == "breach":
            cooldown = get_json(_NS_COOL, user_id)
            if not cooldown:
                set_json(_NS_COOL, user_id, {"fired_at": payload_common.get("updated_at")}, ttl=BREACH_COOLDOWN_SEC)
                guardian_ids = await _resolve_guardian_ids(session, user_id)
                guardians_message = EMOTIONAL_COPY["family_alerted"]
                for gid in guardian_ids:
                    try:
                        await broadcaster.broadcast_to_user(gid, "geofence_breach", {
                            **payload_common,
                            "guardian_message": guardians_message,
                            "alert_sent_message": EMOTIONAL_COPY["alert_sent"].format(name=name),
                        })
                    except Exception:
                        continue
                breach_alert_fired = True
        elif new_state == "recovery":
            # Clear breach cooldown so a future exit triggers a fresh alert.
            delete_key(_NS_COOL, user_id)
            guardian_ids = await _resolve_guardian_ids(session, user_id)
            for gid in guardian_ids:
                try:
                    await broadcaster.broadcast_to_user(gid, "geofence_recovery", payload_common)
                except Exception:
                    continue

    return GeofenceEvaluation(
        state=new_state,
        message=message,
        distance_m=distance_m,
        radius_m=zone.radius_m,
        zone_id=str(zone.id),
        zone_name=zone.name,
        center_lat=zone.lat,
        center_lng=zone.lng,
        transition=transition,
        breach_alert_fired=breach_alert_fired,
    )
