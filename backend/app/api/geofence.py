"""
Geofence API — Guardian-controlled safety zones with emotionally designed real-time alerts.

Endpoints:
    POST   /api/geofence/zone-for-user     — guardian creates/updates a zone for a linked protected user
    GET    /api/geofence/zones-for/{uid}   — list zones for a user (caller must be owner/guardian/admin)
    DELETE /api/geofence/zone/{zone_id}    — deactivate a zone (caller must be owner/guardian/admin)
    POST   /api/geofence/location-update   — protected user pings location → evaluate + emit SSE
    GET    /api/geofence/status/{uid}      — guardian reads current geofence state for a user
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.models.safe_zone import SafeZone
from app.models.monitored_route import MonitoredRoute

router = APIRouter(prefix="/geofence", tags=["geofence"])

DEFAULT_RADIUS_M = 3000
MIN_RADIUS_M = 100
MAX_RADIUS_M = 10000


# ── Request models ──
class ZoneForUserRequest(BaseModel):
    user_id: str = Field(..., description="Protected user (child/woman/elderly) to create zone for")
    center_lat: float = Field(..., ge=-90, le=90)
    center_lng: float = Field(..., ge=-180, le=180)
    radius_m: float = Field(DEFAULT_RADIUS_M, ge=MIN_RADIUS_M, le=MAX_RADIUS_M)
    name: str = Field("Safety Zone", min_length=1, max_length=100)
    address: str | None = Field(None, max_length=300)
    category: Literal["safe", "restricted"] = "safe"


class RouteForUserRequest(BaseModel):
    user_id: str = Field(..., description="Protected user (child/woman/elderly) to create route for")
    name: str = Field("Safety Route", min_length=1, max_length=100)
    origin_name: str | None = None
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lng: float = Field(..., ge=-180, le=180)
    dest_name: str | None = None
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lng: float = Field(..., ge=-180, le=180)
    corridor_width_m: float = Field(100.0, ge=20.0, le=2000.0)


class ZoneUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    address: str | None = Field(None, max_length=300)
    center_lat: float = Field(..., ge=-90, le=90)
    center_lng: float = Field(..., ge=-180, le=180)
    radius_m: float = Field(..., ge=MIN_RADIUS_M, le=MAX_RADIUS_M)
    category: Literal["safe", "restricted"]


class RouteUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    origin_name: str | None = None
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lng: float = Field(..., ge=-180, le=180)
    dest_name: str | None = None
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lng: float = Field(..., ge=-180, le=180)
    corridor_width_m: float = Field(..., ge=20.0, le=2000.0)


class LocationUpdateRequest(BaseModel):
    user_id: str | None = Field(None, description="Defaults to the authenticated user")
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    battery_pct: int | None = Field(None, ge=0, le=100)
    accuracy_m: float | None = Field(None, ge=0)
    speed_mps: float | None = Field(None, ge=0)
    captured_at: datetime | None = Field(
        None,
        description="Native device fix time; server receipt time is used when omitted",
    )


class LocationAvailabilityRequest(BaseModel):
    available: bool
    reason: str = Field(..., min_length=1, max_length=80)
    services_enabled: bool | None = None
    foreground_permission: str | None = None
    background_permission: str | None = None


# ── Authorization helpers ──
async def _is_guardian_of(session: AsyncSession, guardian_id: str, child_id: str) -> bool:
    """True if `guardian_id` is linked as a guardian of `child_id`."""
    if not child_id or not guardian_id:
        return False

    # 1. Direct check on users table (child.guardian_id == guardian_id)
    try:
        r = await session.execute(
            select(User).where(
                User.id == uuid.UUID(child_id),
                User.guardian_id == uuid.UUID(guardian_id),
            )
        )
        if r.scalar_one_or_none():
            return True
    except Exception:
        pass

    # 2. Check guardian_relationships table (user_id = child_id, guardian_user_id = guardian_id)
    try:
        from sqlalchemy import text
        r = await session.execute(text("""
            SELECT id FROM guardian_relationships 
            WHERE user_id = :cid AND guardian_user_id = :gid AND is_active = true
            LIMIT 1
        """), {"cid": child_id, "gid": guardian_id})
        if r.first():
            return True
    except Exception:
        pass

    # 3. Legacy Guardian table check
    try:
        from app.models.guardian import Guardian
        guardian_user = await session.execute(select(User).where(User.id == uuid.UUID(guardian_id)))
        gu = guardian_user.scalar_one_or_none()
        if gu:
            g_row = await session.execute(
                select(Guardian).where(
                    Guardian.user_id == uuid.UUID(child_id),
                    Guardian.email == gu.email,
                    Guardian.is_active.is_(True),
                )
            )
            if g_row.scalar_one_or_none():
                return True
    except Exception:
        pass

    return False


def _is_admin(user) -> bool:
    return (getattr(user, "role", None) or "").lower() in ("admin", "operator")


async def _can_manage_safety(session: AsyncSession, user: User, target_user_id: str) -> bool:
    """Only admins and linked primary guardians may mutate safety assignments.

    Protected members can view assignments made for them, but cannot create,
    edit, or delete those records. Co-guardians/co-parents remain read-only.
    """
    if _is_admin(user):
        return True
    caller_id = str(user.id)
    if caller_id == target_user_id:
        return False
    role = (getattr(user, "role", None) or "").lower().replace("-", "_")
    if role in ("co_guardian", "co_parent", "coparent"):
        return False
    if role not in ("guardian", "parent", "primary_guardian"):
        return False
    return await _is_guardian_of(session, caller_id, target_user_id)


# ── Endpoints ──
@router.post("/zone-for-user")
async def create_zone_for_user(
    req: ZoneForUserRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian creates/updates a safety zone for a linked protected user."""
    caller_id = str(user.id)

    if not await _can_manage_safety(session, user, req.user_id):
        raise HTTPException(status_code=403, detail="Only a Primary Guardian can manage safety zones.")

    zone = SafeZone(
        user_id=uuid.UUID(req.user_id),
        name=req.name,
        address=req.address,
        lat=req.center_lat,
        lng=req.center_lng,
        radius_m=req.radius_m,
        zone_type=req.category,
        active=True,
    )
    session.add(zone)
    await session.flush()
    await session.commit()

    # Invalidate cached zone so the next location-update sees the new values immediately.
    try:
        from app.services.geofence_alerts import invalidate_zone_cache
        invalidate_zone_cache(req.user_id)
    except Exception:
        pass

    return {
        "id": str(zone.id),
        "user_id": req.user_id,
        "name": zone.name,
        "address": zone.address,
        "center_lat": zone.lat,
        "center_lng": zone.lng,
        "radius_m": zone.radius_m,
        "category": req.category,
        "active": True,
        "message": "Safety zone set. Your loved one will be notified on any exit.",
    }


@router.get("/zones-for/{target_user_id}")
async def list_zones_for_user(
    target_user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List active safety zones for a user. Caller must own the user or be a linked guardian/admin."""
    caller_id = str(user.id)
    if target_user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, target_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to view these zones.")
    rows = await session.execute(
        select(SafeZone)
        .where(SafeZone.user_id == uuid.UUID(target_user_id), SafeZone.active.is_(True))
        .order_by(SafeZone.created_at.desc())
    )
    zones = rows.scalars().all()
    return {
        "zones": [
            {
                "id": str(z.id),
                "name": z.name,
                "address": z.address,
                "center_lat": z.lat,
                "center_lng": z.lng,
                "radius_m": z.radius_m,
                "zone_type": z.zone_type,
                "category": "restricted" if z.zone_type == "restricted" else "safe",
            }
            for z in zones
        ],
        "count": len(zones),
    }


@router.put("/zone/{zone_id}")
async def update_zone(
    zone_id: str,
    req: ZoneUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    zrow = await session.execute(select(SafeZone).where(SafeZone.id == uuid.UUID(zone_id)))
    zone = zrow.scalar_one_or_none()
    if not zone or not zone.active:
        raise HTTPException(status_code=404, detail="Zone not found")
    caller_id = str(user.id)
    if not await _can_manage_safety(session, user, str(zone.user_id)):
        raise HTTPException(status_code=403, detail="Only a Primary Guardian can edit this zone.")
    zone.name = req.name
    zone.address = req.address
    zone.lat = req.center_lat
    zone.lng = req.center_lng
    zone.radius_m = req.radius_m
    zone.zone_type = req.category
    zone.updated_at = datetime.utcnow()
    await session.commit()
    from app.services.geofence_alerts import clear_zone_runtime_state, invalidate_zone_cache
    invalidate_zone_cache(str(zone.user_id))
    clear_zone_runtime_state(str(zone.user_id), str(zone.id))
    return {
        "id": str(zone.id), "user_id": str(zone.user_id), "name": zone.name,
        "address": zone.address, "center_lat": zone.lat, "center_lng": zone.lng,
        "radius_m": zone.radius_m, "category": req.category, "active": True,
    }


@router.delete("/zone/{zone_id}")
async def deactivate_zone(
    zone_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    zrow = await session.execute(select(SafeZone).where(SafeZone.id == uuid.UUID(zone_id)))
    z = zrow.scalar_one_or_none()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found")
    caller_id = str(user.id)
    if not await _can_manage_safety(session, user, str(z.user_id)):
        raise HTTPException(status_code=403, detail="Only a Primary Guardian can remove this zone.")
    z.active = False
    await session.commit()
    try:
        from app.services.geofence_alerts import clear_zone_runtime_state, invalidate_zone_cache
        invalidate_zone_cache(str(z.user_id))
        clear_zone_runtime_state(str(z.user_id), str(z.id))
    except Exception:
        pass
    return {"id": zone_id, "active": False, "message": "Zone removed."}


@router.post("/location-update")
async def location_update(
    req: LocationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Protected user pings their current lat/lng. Backend evaluates against their
    active safety zone and emits SSE events with emotional copy on transitions.
    """
    from app.services.geofence_alerts import (
        evaluate_environmental_hazard,
        evaluate_user_location,
        record_protected_telemetry,
    )

    target_id = req.user_id or str(user.id)
    # Users may only update their OWN location via this endpoint (ownership guard).
    # Admins can update on behalf of others (useful for testing).
    if target_id != str(user.id) and not _is_admin(user):
        raise HTTPException(status_code=403, detail="You can only update your own location.")

    telemetry = await record_protected_telemetry(
        session,
        target_id,
        req.lat,
        req.lng,
        battery_pct=req.battery_pct,
        accuracy_m=req.accuracy_m,
        speed_mps=req.speed_mps,
        captured_at=req.captured_at,
    )
    # A delayed offline fix is useful as truthful last-known state, but must not
    # replay historical safe-zone/environmental alerts when the phone reconnects.
    if not telemetry["is_current"]:
        await session.commit()
        return {
            "state": "stale",
            "message": "Last known location recorded; waiting for a current device fix.",
            "distance_m": None,
            "radius_m": None,
            "zone_id": None,
            "telemetry": telemetry,
            "environmental": [],
        }

    from app.services.location_availability import record_location_availability
    await record_location_availability(
        session,
        target_id,
        available=True,
        reason="current_location_fix",
        source="protected_device",
    )

    result = await evaluate_user_location(session, target_id, req.lat, req.lng)
    environmental = await evaluate_environmental_hazard(
        session,
        target_id,
        req.lat,
        req.lng,
    )
    await session.commit()
    return {
        "state": result.state,
        "message": result.message,
        "distance_m": round(result.distance_m, 1),
        "radius_m": result.radius_m,
        "zone_id": result.zone_id,
        "zone_name": result.zone_name,
        "transition": result.transition,
        "breach_alert_fired": result.breach_alert_fired,
        "telemetry": {
            "battery_pct": telemetry.get("battery_pct"),
            "updated_at": telemetry.get("updated_at"),
            "source": telemetry.get("source"),
        },
        "environmental_hazard": {
            "matched": bool(environmental.get("matched")),
            "source": (
                (environmental.get("strongest") or {}).get("source")
                if environmental.get("matched")
                else None
            ),
            "title": (
                (environmental.get("strongest") or {}).get("title")
                if environmental.get("matched")
                else None
            ),
            "alert_dispatched": bool(
                environmental.get("guardian_alert_dispatched")
            ),
        },
    }


@router.post("/location-availability")
async def location_availability(
    req: LocationAvailabilityRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Receive the protected phone's real permission/services state."""
    from app.services.location_availability import record_location_availability

    state = await record_location_availability(
        session,
        str(user.id),
        available=req.available,
        reason=req.reason,
        source="protected_device_status",
    )
    await session.commit()
    return state


@router.get("/status/{target_user_id}")
async def get_status(
    target_user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Read the last known geofence state for a user (guardian dashboard)."""
    from app.services.redis_service import get_json

    caller_id = str(user.id)
    if target_user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, target_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to read this status.")
    state = get_json("geofence:state", target_user_id)
    if not state:
        # No pings yet. Return the configured zone (if any) so UI can render the circle.
        zrow = await session.execute(
            select(SafeZone)
            .where(SafeZone.user_id == uuid.UUID(target_user_id), SafeZone.active.is_(True))
            .order_by(SafeZone.created_at.desc())
            .limit(1)
        )
        z = zrow.scalar_one_or_none()
        if z:
            return {
                "state": "unknown",
                "message": "Waiting for first location update…",
                "zone": {
                    "id": str(z.id),
                    "name": z.name,
                    "center_lat": z.lat,
                    "center_lng": z.lng,
                    "radius_m": z.radius_m,
                },
            }
        return {"state": "no_zone", "message": "No safety zone set yet.", "zone": None}
    return state


# ═════════════════════════════════════════════════════════════════════
# Care Locations (saved pins) — Redis-only, no schema changes.
# One-tap geofence setup for frequent places: Home / Office / Hospital / …
# Stored at `geofence:pins:{user_id}` → JSON list of {type, name, lat, lng, saved_at}
# ═════════════════════════════════════════════════════════════════════

MAX_PINS_PER_USER = 5
ALLOWED_PIN_TYPES = {"home", "office", "school", "hospital", "custom"}


class PinModel(BaseModel):
    type: str = Field("custom")
    name: str = Field(..., min_length=1, max_length=60)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class SavePinsRequest(BaseModel):
    user_id: str
    pins: list[PinModel]


class SaveOnePinRequest(BaseModel):
    user_id: str
    pin: PinModel


def _normalize_pins(pins) -> list[dict]:
    import datetime as _dt
    now = _dt.datetime.utcnow().isoformat() + "Z"
    out: list[dict] = []
    for p in pins[:MAX_PINS_PER_USER]:
        data = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        ptype = (data.get("type") or "custom").lower()
        if ptype not in ALLOWED_PIN_TYPES:
            ptype = "custom"
        out.append({
            "type": ptype,
            "name": data["name"].strip()[:60],
            "lat": float(data["lat"]),
            "lng": float(data["lng"]),
            "saved_at": data.get("saved_at", now),
        })
    return out


@router.get("/pins/{target_user_id}")
async def get_pins(
    target_user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Fetch saved Care Locations for a user. Empty list if none saved yet."""
    from app.services.redis_service import get_json
    caller_id = str(user.id)
    if target_user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, target_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to view these care locations.")
    pins = get_json("geofence:pins", target_user_id) or []
    return {"user_id": target_user_id, "pins": pins, "count": len(pins), "max": MAX_PINS_PER_USER}


@router.post("/pins/save")
async def save_pins(
    req: SavePinsRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Replace the full pin list for a user (idempotent). Enforces MAX_PINS_PER_USER."""
    from app.services.redis_service import set_json
    caller_id = str(user.id)
    if req.user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, req.user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to save care locations.")
    pins = _normalize_pins(req.pins)
    # Redis TTL: none (persistent); pins are tiny and long-lived per user.
    # Using set_json with ttl=0 means no expiry on our helper.
    set_json("geofence:pins", req.user_id, pins, ttl=None)  # persistent
    return {"user_id": req.user_id, "pins": pins, "count": len(pins), "message": "Care locations saved."}


@router.post("/pins/add")
async def add_pin(
    req: SaveOnePinRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Append a single pin (dedupes by name, enforces MAX_PINS_PER_USER — oldest drops out)."""
    from app.services.redis_service import get_json, set_json
    caller_id = str(user.id)
    if req.user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, req.user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to save care locations.")
    existing = get_json("geofence:pins", req.user_id) or []
    # Remove duplicate by name (case-insensitive) — updating the location in place.
    new_name = req.pin.name.strip().lower()
    existing = [p for p in existing if (p.get("name") or "").strip().lower() != new_name]
    new_pin = _normalize_pins([req.pin])[0]
    existing.append(new_pin)
    # Cap at MAX — drop the oldest (front of list).
    if len(existing) > MAX_PINS_PER_USER:
        existing = existing[-MAX_PINS_PER_USER:]
    set_json("geofence:pins", req.user_id, existing, ttl=None)
    return {"user_id": req.user_id, "pins": existing, "count": len(existing), "message": f"{new_pin['name']} location saved for quicker care setup."}


@router.delete("/pins/{target_user_id}/{pin_name}")
async def delete_pin(
    target_user_id: str,
    pin_name: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    from app.services.redis_service import get_json, set_json
    caller_id = str(user.id)
    if target_user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, target_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to delete care locations.")
    existing = get_json("geofence:pins", target_user_id) or []
    target = pin_name.strip().lower()
    remaining = [p for p in existing if (p.get("name") or "").strip().lower() != target]
    set_json("geofence:pins", target_user_id, remaining, ttl=None)
    return {"user_id": target_user_id, "pins": remaining, "count": len(remaining)}


# ── Monitored Route Endpoints ──

@router.post("/route-for-user")
async def create_route_for_user(
    req: RouteForUserRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian creates a monitored route corridor for a linked protected user."""
    caller_id = str(user.id)

    if not await _can_manage_safety(session, user, req.user_id):
        raise HTTPException(status_code=403, detail="Only a Primary Guardian can manage monitored routes.")

    route_obj = MonitoredRoute(
        user_id=uuid.UUID(req.user_id),
        created_by_guardian_id=uuid.UUID(caller_id) if caller_id != req.user_id else None,
        name=req.name,
        origin_name=req.origin_name,
        origin_lat=req.origin_lat,
        origin_lng=req.origin_lng,
        dest_name=req.dest_name,
        dest_lat=req.dest_lat,
        dest_lng=req.dest_lng,
        corridor_width_m=req.corridor_width_m,
        active=True,
    )
    session.add(route_obj)
    await session.flush()
    await session.commit()

    return {
        "id": str(route_obj.id),
        "user_id": req.user_id,
        "name": route_obj.name,
        "origin_name": route_obj.origin_name,
        "origin_lat": route_obj.origin_lat,
        "origin_lng": route_obj.origin_lng,
        "dest_name": route_obj.dest_name,
        "dest_lat": route_obj.dest_lat,
        "dest_lng": route_obj.dest_lng,
        "corridor_width_m": route_obj.corridor_width_m,
        "active": True,
        "message": "Monitored route saved successfully.",
    }


@router.get("/routes-for/{target_user_id}")
async def list_routes_for_user(
    target_user_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List active monitored routes for a user."""
    caller_id = str(user.id)
    if target_user_id != caller_id and not _is_admin(user):
        ok = await _is_guardian_of(session, caller_id, target_user_id)
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorized to view these routes.")

    rows = await session.execute(
        select(MonitoredRoute)
        .where(MonitoredRoute.user_id == uuid.UUID(target_user_id), MonitoredRoute.active.is_(True))
        .order_by(MonitoredRoute.created_at.desc())
    )
    routes = rows.scalars().all()
    return {
        "routes": [
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                "name": r.name,
                "origin_name": r.origin_name,
                "origin_lat": r.origin_lat,
                "origin_lng": r.origin_lng,
                "dest_name": r.dest_name,
                "dest_lat": r.dest_lat,
                "dest_lng": r.dest_lng,
                "corridor_width_m": r.corridor_width_m,
                "active": r.active,
            }
            for r in routes
        ],
        "count": len(routes),
    }


@router.delete("/route/{route_id}")
async def deactivate_route(
    route_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Deactivate a monitored route."""
    rrow = await session.execute(select(MonitoredRoute).where(MonitoredRoute.id == uuid.UUID(route_id)))
    r = rrow.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Route not found")

    caller_id = str(user.id)
    if not await _can_manage_safety(session, user, str(r.user_id)):
        raise HTTPException(status_code=403, detail="Only a Primary Guardian can remove this route.")

    r.active = False
    await session.commit()
    from app.services.geofence_alerts import clear_route_runtime_state
    clear_route_runtime_state(str(r.user_id), str(r.id))
    return {"id": route_id, "active": False, "message": "Monitored route removed."}


@router.put("/route/{route_id}")
async def update_route(
    route_id: str,
    req: RouteUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    rrow = await session.execute(select(MonitoredRoute).where(MonitoredRoute.id == uuid.UUID(route_id)))
    route = rrow.scalar_one_or_none()
    if not route or not route.active:
        raise HTTPException(status_code=404, detail="Route not found")
    caller_id = str(user.id)
    if not await _can_manage_safety(session, user, str(route.user_id)):
        raise HTTPException(status_code=403, detail="Only a Primary Guardian can edit this route.")
    route.name = req.name
    route.origin_name = req.origin_name
    route.origin_lat = req.origin_lat
    route.origin_lng = req.origin_lng
    route.dest_name = req.dest_name
    route.dest_lat = req.dest_lat
    route.dest_lng = req.dest_lng
    route.corridor_width_m = req.corridor_width_m
    route.updated_at = datetime.utcnow()
    await session.commit()
    from app.services.geofence_alerts import clear_route_runtime_state
    clear_route_runtime_state(str(route.user_id), str(route.id))
    return {
        "id": str(route.id), "user_id": str(route.user_id), "name": route.name,
        "origin_name": route.origin_name, "origin_lat": route.origin_lat,
        "origin_lng": route.origin_lng, "dest_name": route.dest_name,
        "dest_lat": route.dest_lat, "dest_lng": route.dest_lng,
        "corridor_width_m": route.corridor_width_m, "active": True,
    }
