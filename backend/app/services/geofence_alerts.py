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
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import GuardianSession
from app.models.safe_zone import SafeZone
from app.models.user import User

__all__ = [
    "haversine_m",
    "evaluate_user_location",
    "record_protected_telemetry",
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
    is_current = observation_age_s <= 120
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
        "source": "protected_device",
    }
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

        # On BREACH: apply 60s cooldown and enter the canonical persisted
        # alert pipeline. That pipeline resolves every linked guardian,
        # writes GuardianAlert/SafetyIncident rows, sends closed-app FCM,
        # and evaluates SACHET/NDMA context for this real coordinate.
        if new_state == "breach":
            cooldown = get_json(_NS_COOL, user_id)
            if not cooldown:
                now_iso = __import__("datetime").datetime.utcnow().isoformat() + "Z"
                set_json(_NS_COOL, user_id, {"fired_at": now_iso}, ttl=BREACH_COOLDOWN_SEC)
                try:
                    from app.services.alert_trigger import trigger_alert
                    result = await trigger_alert(
                        session,
                        kind="geofence_breach",
                        user_id=user_id,
                        severity="high",
                        message=message,
                        details=(
                            f"Outside {zone.name} by {round(distance_m, 1)} metres. "
                            "Location is from the protected member's latest GPS fix."
                        ),
                        location={"lat": lat, "lng": lng},
                        sse_event_type="geofence_breach",
                        sse_payload_extras={
                            **payload_common,
                            "guardian_message": EMOTIONAL_COPY["family_alerted"],
                            "alert_sent_message": EMOTIONAL_COPY["alert_sent"].format(name=name),
                        },
                        idempotency_key=f"{zone.id}:breach",
                        cooldown_s=BREACH_COOLDOWN_SEC,
                    )
                    breach_alert_fired = result.dispatched
                except Exception:
                    # Keep the protected-user status update intact even if the
                    # guardian dispatch path is temporarily unavailable.
                    pass
        elif new_state == "recovery":
            # Clear breach cooldown so a future exit triggers a fresh alert.
            delete_key(_NS_COOL, user_id)
            try:
                from app.services.alert_trigger import trigger_alert
                await trigger_alert(
                    session,
                    kind="geofence_recovery",
                    user_id=user_id,
                    severity="low",
                    message=message,
                    details=f"Returned inside {zone.name}.",
                    location={"lat": lat, "lng": lng},
                    sse_event_type="geofence_recovery",
                    sse_payload_extras=payload_common,
                    idempotency_key=f"{zone.id}:recovery",
                    cooldown_s=BREACH_COOLDOWN_SEC,
                )
            except Exception:
                pass

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
