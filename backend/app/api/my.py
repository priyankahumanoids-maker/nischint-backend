# Self-service Seniors & Devices Router (guardian-scoped)
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db_session, get_current_user
from app.models.device import Device
from app.models.senior import Senior
from app.models.user import User
from app.services import device_service

router = APIRouter(prefix="/my", tags=["my-seniors"])


class CreateSeniorRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    age: Optional[int] = Field(None, ge=0, le=150)
    medical_notes: Optional[str] = None


class NotificationPreferences(BaseModel):
    push: Optional[bool] = None
    email: Optional[bool] = None
    sms: Optional[bool] = None
    sos_critical: Optional[bool] = None
    daily_digest: Optional[bool] = None
    weekly_report: Optional[bool] = None


class LinkDeviceRequest(BaseModel):
    device_identifier: str = Field(min_length=1, max_length=255)
    device_type: Optional[str] = None


def _senior_dict(s: Senior) -> dict:
    return {
        "id": str(s.id),
        "full_name": s.full_name,
        "age": s.age,
        "medical_notes": s.medical_notes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _device_dict(d: Device) -> dict:
    return {
        "id": str(d.id),
        "device_identifier": d.device_identifier,
        "device_type": d.device_type,
        "status": d.status,
        "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        "senior_id": str(d.senior_id),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


async def _get_owned_senior(session: AsyncSession, senior_id: UUID, user: User) -> Senior:
    """Fetch senior and verify ownership."""
    senior = (await session.execute(
        select(Senior).where(Senior.id == senior_id, Senior.guardian_id == user.id)
    )).scalar_one_or_none()
    if not senior:
        raise HTTPException(status_code=404, detail="Senior not found")
    return senior


# ── Seniors ──

@router.get("/seniors")
async def list_my_seniors(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List all seniors for the authenticated guardian (test/seed rows filtered out)."""
    from app.services.dashboard_service import is_test_senior_name

    result = await session.execute(
        select(Senior)
        .where(Senior.guardian_id == user.id)
        .order_by(Senior.created_at.asc())
    )
    return [
        _senior_dict(s)
        for s in result.scalars().all()
        if not is_test_senior_name(s.full_name)
    ]


@router.post("/seniors", status_code=201)
async def create_my_senior(
    req: CreateSeniorRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a senior profile under the authenticated guardian."""
    senior = Senior(
        guardian_id=user.id,
        full_name=req.full_name,
        age=req.age,
        medical_notes=req.medical_notes,
    )
    session.add(senior)
    await session.commit()
    await session.refresh(senior)
    return _senior_dict(senior)


@router.get("/seniors/{senior_id}")
async def get_my_senior(
    senior_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get a specific senior (ownership verified)."""
    senior = await _get_owned_senior(session, senior_id, user)
    return _senior_dict(senior)


# ── Devices ──

@router.get("/seniors/{senior_id}/devices")
async def list_senior_devices(
    senior_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List devices for a senior (ownership verified)."""
    await _get_owned_senior(session, senior_id, user)
    result = await session.execute(
        select(Device).where(Device.senior_id == senior_id).order_by(Device.created_at.asc())
    )
    return [_device_dict(d) for d in result.scalars().all()]


@router.post("/seniors/{senior_id}/devices", status_code=201)
async def link_device_to_senior(
    senior_id: UUID,
    req: LinkDeviceRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Link a device to a senior (ownership verified). Device identifier must be unique."""
    await _get_owned_senior(session, senior_id, user)

    # Check duplicate device_identifier
    existing = (await session.execute(
        select(Device).where(Device.device_identifier == req.device_identifier)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A device with this identifier already exists")

    device = Device(
        senior_id=senior_id,
        device_identifier=req.device_identifier,
        device_type=req.device_type,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return _device_dict(device)



# ── Test Alert ──

class TestAlertRequest(BaseModel):
    device_identifier: str
    type: str = Field(default="sos", description="Alert type: sos, fall_detected")


@router.post("/seniors/{senior_id}/test-alert", status_code=201)
async def send_test_alert(
    senior_id: UUID,
    req: TestAlertRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Send a test alert through the FULL pipeline.
    Creates real telemetry → incident (is_test=true) → escalation → notifications.
    Test incidents use reduced thresholds (30s L1, 60s L2, 90s L3).
    """
    from app.models.telemetry import Telemetry
    from app.models.incident import Incident
    from app.services.event_broadcaster import broadcaster, serialize_for_sse
    from app.services.incident_events import log_event

    # Verify senior ownership
    senior = await _get_owned_senior(session, senior_id, user)

    # Verify device belongs to this senior
    device = (await session.execute(
        select(Device).where(
            Device.device_identifier == req.device_identifier,
            Device.senior_id == senior_id,
        )
    )).scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found or does not belong to this senior")

    # Map alert type to incident config
    alert_map = {
        "sos": {"incident_type": "sos_alert", "severity": "critical"},
        "fall_detected": {"incident_type": "fall_alert", "severity": "high"},
    }
    config = alert_map.get(req.type)
    if not config:
        raise HTTPException(status_code=400, detail=f"Unknown alert type: {req.type}")

    # 1. Insert telemetry
    telemetry = Telemetry(
        device_id=device.id,
        metric_type=req.type,
        metric_value={"is_test": True, "triggered_by": str(user.id)},
    )
    session.add(telemetry)

    # 2. Create incident with is_test=True and reduced escalation time
    incident = Incident(
        senior_id=senior_id,
        device_id=device.id,
        incident_type=config["incident_type"],
        severity=config["severity"],
        escalation_minutes=1,  # 1 min for test (scheduler uses L1/L2/L3 thresholds)
        is_test=True,
    )
    session.add(incident)
    await session.commit()
    await session.refresh(incident)

    # 3. Log audit event
    await log_event(session, incident.id, "incident_created", metadata={
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "device_identifier": req.device_identifier,
        "is_test": True,
    })
    await session.commit()

    # 4. Broadcast via SSE
    guardian_id = str(senior.guardian_id)
    incident_data = serialize_for_sse({
        "id": incident.id,
        "senior_id": incident.senior_id,
        "device_id": incident.device_id,
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "status": incident.status,
        "escalated": incident.escalated,
        "is_test": True,
        "created_at": incident.created_at,
    })
    await broadcaster.broadcast_incident_created(guardian_id, incident_data)

    return {
        "message": f"Test {req.type} alert sent for {senior.full_name}",
        "incident_id": str(incident.id),
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "is_test": True,
    }


# ── Device Health ──

@router.get("/seniors/{senior_id}/device-health")
async def get_senior_device_health(
    senior_id: UUID,
    window_hours: int = 24,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get device health metrics for all devices under a senior."""
    await _get_owned_senior(session, senior_id, user)

    from app.services.device_health_service import get_devices_health_batch
    return await get_devices_health_batch(session, senior_id, window_hours)



# ── Notification Preferences (stored in Mongo; per-user) ──

_DEFAULT_PREFS = {
    "push": True,
    "email": True,
    "sms": False,
    "sos_critical": True,  # always on
    "daily_digest": False,
    "weekly_report": False,
}


async def _get_mongo_collection():
    """Lazy-import sync mongo collection (pymongo via journey_store)."""
    try:
        from app.api import journey_store as _store
        _store._init()
        if _store._enabled and _store._db is not None:
            return _store._db["notification_preferences"]
    except Exception:
        pass
    return None


@router.get("/notification-preferences")
async def get_notification_preferences(
    user: User = Depends(get_current_user),
):
    """Get current user's notification preferences."""
    coll = await _get_mongo_collection()
    if coll is None:
        return _DEFAULT_PREFS
    doc = coll.find_one({"user_id": str(user.id)}, {"_id": 0, "user_id": 0})
    if not doc:
        return _DEFAULT_PREFS
    merged = {**_DEFAULT_PREFS, **doc}
    merged["sos_critical"] = True  # never allow off
    return merged


@router.patch("/notification-preferences")
async def update_notification_preferences(
    prefs: NotificationPreferences,
    user: User = Depends(get_current_user),
):
    """Update current user's notification preferences (partial update)."""
    coll = await _get_mongo_collection()
    if coll is None:
        # Mongo unavailable — accept but don't persist. Frontend already stores in localStorage.
        return {"ok": True, "persisted": False}
    patch = {k: v for k, v in prefs.dict(exclude_none=True).items()}
    patch["sos_critical"] = True
    coll.update_one(
        {"user_id": str(user.id)},
        {"$set": {**patch, "user_id": str(user.id)}},
        upsert=True,
    )
    return {"ok": True, "persisted": True}
