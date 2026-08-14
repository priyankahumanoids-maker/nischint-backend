"""
NISCHINT BLE Wearable Backend — Device identity, event ingestion, and escalation layer.
Mobile-bridged architecture: BLE stays on mobile, backend handles truth/mapping/escalation.

Endpoints:
  POST /api/wearable/register     — Register a BLE peripheral
  POST /api/wearable/bind         — Bind device to user
  POST /api/wearable/event        — Ingest BLE events (button press, fall, etc.)
  POST /api/wearable/heartbeat    — Device health telemetry
  GET  /api/wearable/devices      — List user's devices
  GET  /api/wearable/audit        — Event audit trail
"""
import json as json_lib
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.services.event_broadcaster import broadcaster
from app.core.rate_limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wearable", tags=["BLE Wearable"])


# ──────────────────────────────────────────────
# DB SCHEMA
# ──────────────────────────────────────────────

SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS wearable_devices (
        id UUID PRIMARY KEY,
        device_uid TEXT NOT NULL UNIQUE,
        user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        device_type TEXT DEFAULT 'wearable',
        status TEXT DEFAULT 'inactive',
        device_name TEXT,
        capabilities JSONB DEFAULT '{}',
        battery_level INT,
        heart_rate_bpm INT,
        heart_rate_at TIMESTAMPTZ,
        last_seen_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS device_audit_log (
        id UUID PRIMARY KEY,
        device_id UUID REFERENCES wearable_devices(id) ON DELETE CASCADE,
        user_id UUID,
        event_type TEXT NOT NULL,
        event_id TEXT,
        payload JSONB DEFAULT '{}',
        source TEXT DEFAULT 'wearable',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS device_health_log (
        id UUID PRIMARY KEY,
        device_id UUID REFERENCES wearable_devices(id) ON DELETE CASCADE,
        battery INT,
        rssi INT,
        heart_rate_bpm INT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    "ALTER TABLE wearable_devices ADD COLUMN IF NOT EXISTS device_name TEXT;",
    "ALTER TABLE wearable_devices ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '{}';",
    "ALTER TABLE wearable_devices ADD COLUMN IF NOT EXISTS heart_rate_bpm INT;",
    "ALTER TABLE wearable_devices ADD COLUMN IF NOT EXISTS heart_rate_at TIMESTAMPTZ;",
    "ALTER TABLE device_health_log ADD COLUMN IF NOT EXISTS heart_rate_bpm INT;",
    "CREATE INDEX IF NOT EXISTS idx_wd_device_uid ON wearable_devices(device_uid);",
    "CREATE INDEX IF NOT EXISTS idx_wd_user_id ON wearable_devices(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_dal_device_id ON device_audit_log(device_id);",
    "CREATE INDEX IF NOT EXISTS idx_dal_event_id ON device_audit_log(event_id);",
    "CREATE INDEX IF NOT EXISTS idx_dal_event_type ON device_audit_log(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_dhl_device_id ON device_health_log(device_id);",
]


_schema_ready = False


async def _ensure_schema(db: AsyncSession):
    global _schema_ready
    if _schema_ready:
        return
    for sql in SCHEMA_SQL:
        await db.execute(text(sql))
    await db.commit()
    _schema_ready = True


# ──────────────────────────────────────────────
# EVENT NORMALIZER
# ──────────────────────────────────────────────

EVENT_MAP = {
    "BUTTON_PRESS": "EMERGENCY",
    "BUTTON_LONG_PRESS": "EMERGENCY",
    "FALL_DETECTED": "SAFETY_ALERT",
    "IMPACT_DETECTED": "SAFETY_ALERT",
    "TAMPER_DETECTED": "TAMPER_ALERT",
    "GEOFENCE_BREACH": "GEOFENCE_ALERT",
    "HEARTRATE_ANOMALY": "HEALTH_ALERT",
}


def normalize_event(event_type: str) -> str:
    """Map raw BLE event types to system alert categories."""
    return EVENT_MAP.get(event_type, "DEVICE_EVENT")


# ──────────────────────────────────────────────
# REQUEST MODELS
# ──────────────────────────────────────────────

class DeviceRegisterRequest(BaseModel):
    device_uid: str
    device_type: str = "wearable"
    device_name: Optional[str] = None
    capabilities: Optional[dict] = None


class DeviceBindRequest(BaseModel):
    device_id: str
    user_id: str


class DeviceEventRequest(BaseModel):
    device_id: str
    event_type: str
    event_id: Optional[str] = None
    payload: Optional[dict] = None
    client_timestamp: Optional[str] = None


class HeartbeatRequest(BaseModel):
    device_id: str
    battery: Optional[int] = None
    rssi: Optional[int] = None
    heart_rate_bpm: Optional[int] = None


# ──────────────────────────────────────────────
# DEVICE RESOLVER
# ──────────────────────────────────────────────

async def _resolve_device(db: AsyncSession, device_id: str) -> dict | None:
    """Resolve device_id → user_id + guardian_ids + last known location."""
    r = await db.execute(text("""
        SELECT wd.id, wd.device_uid, wd.user_id, wd.device_type, wd.status,
               u.full_name, u.email, u.role
        FROM wearable_devices wd
        LEFT JOIN users u ON wd.user_id = u.id
        WHERE wd.id = :did
    """), {"did": device_id})
    row = r.fetchone()
    if not row or not row.user_id:
        return None

    user_id = str(row.user_id)

    # Resolve every real linked primary/co-guardian using the canonical
    # relationship resolver (direct link + code invite + guardian network).
    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(db, user_id)

    # Last known location from guardian_sessions
    loc = await db.execute(text("""
        SELECT current_location FROM guardian_sessions
        WHERE user_id = :uid AND status = 'active'
        ORDER BY started_at DESC LIMIT 1
    """), {"uid": user_id})
    loc_row = loc.fetchone()
    location = None
    if loc_row and loc_row.current_location:
        try:
            import json
            loc_data = loc_row.current_location if isinstance(loc_row.current_location, dict) else json.loads(loc_row.current_location)
            location = {"lat": loc_data.get("lat"), "lng": loc_data.get("lng")}
        except Exception:
            pass

    return {
        "device_id": str(row.id),
        "device_uid": row.device_uid,
        "user_id": user_id,
        "user_name": row.full_name or row.email,
        "user_role": row.role,
        "guardian_ids": guardian_ids,
        "location": location,
    }


# ──────────────────────────────────────────────
# AUDIT LOGGER
# ──────────────────────────────────────────────

async def _audit_log(db: AsyncSession, device_id: str, user_id: str | None,
                     event_type: str, event_id: str | None, payload: dict | None,
                     source: str = "wearable"):
    await db.execute(text("""
        INSERT INTO device_audit_log (id, device_id, user_id, event_type, event_id, payload, source, created_at)
        VALUES (:id, :did, :uid, :etype, :eid, CAST(:payload AS jsonb), :source, :now)
    """), {
        "id": str(uuid.uuid4()),
        "did": device_id,
        "uid": user_id,
        "etype": event_type,
        "eid": event_id,
        "payload": json_lib.dumps(payload or {}),
        "source": source,
        "now": datetime.now(timezone.utc),
    })


# ══════════════════════════════════════════════
# P0 ENDPOINTS
# ══════════════════════════════════════════════

@router.post("/register")
@limiter.limit("30/minute")
async def register_device(
    request: Request,
    req: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Register a BLE peripheral device. Returns device_id for subsequent calls."""
    await _ensure_schema(db)

    if not req.device_uid.strip():
        raise HTTPException(status_code=422, detail="A Bluetooth device identifier is required")

    # Check if already registered
    existing = await db.execute(
        text("SELECT id, user_id FROM wearable_devices WHERE device_uid = :uid"),
        {"uid": req.device_uid},
    )
    row = existing.fetchone()
    if row:
        if row.user_id and str(row.user_id) != str(user.id):
            raise HTTPException(status_code=409, detail="This wearable is already linked to another account")
        return {
            "status": "exists",
            "device_id": str(row.id),
            "linked_user": row.user_id is not None,
        }

    device_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO wearable_devices
          (id, device_uid, user_id, device_type, device_name, capabilities, status, last_seen_at, created_at)
        VALUES (:id, :uid, :owner, :dtype, :name, CAST(:capabilities AS jsonb), 'active', :now, :now)
    """), {
        "id": device_id,
        "uid": req.device_uid,
        "owner": str(user.id),
        "dtype": req.device_type,
        "name": (req.device_name or '').strip()[:120] or None,
        "capabilities": json_lib.dumps(req.capabilities or {}),
        "now": datetime.now(timezone.utc),
    })
    await db.commit()

    logger.info(f"[WEARABLE_REGISTER] device_uid={req.device_uid} device_id={device_id}")
    return {
        "status": "registered",
        "device_id": device_id,
        "linked_user": True,
    }


@router.post("/bind")
@limiter.limit("30/minute")
async def bind_device(
    request: Request,
    req: DeviceBindRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Bind a registered device to a user. Activates the device."""
    # Verify device exists
    d = await db.execute(
        text("SELECT id FROM wearable_devices WHERE id = :did"),
        {"did": req.device_id},
    )
    if not d.fetchone():
        raise HTTPException(status_code=404, detail="Device not found")

    # Verify user exists
    u = await db.execute(
        text("SELECT id FROM users WHERE id = :uid"),
        {"uid": req.user_id},
    )
    if not u.fetchone():
        raise HTTPException(status_code=404, detail="User not found")

    await db.execute(text("""
        UPDATE wearable_devices
        SET user_id = :uid, status = 'active', last_seen_at = :now
        WHERE id = :did
    """), {
        "uid": req.user_id,
        "did": req.device_id,
        "now": datetime.now(timezone.utc),
    })
    await db.commit()

    logger.info(f"[WEARABLE_BIND] device={req.device_id} -> user={req.user_id}")
    return {"status": "bound", "device_id": req.device_id, "user_id": req.user_id}


@router.post("/event")
@limiter.limit("120/minute")
async def ingest_event(
    request: Request,
    req: DeviceEventRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Ingest a BLE event. Resolves device→user, normalizes event type,
    logs audit trail, broadcasts SSE, and triggers escalation for emergencies.
    """
    await _ensure_schema(db)

    # Idempotency: skip if event_id already processed
    if req.event_id:
        dup = await db.execute(
            text("SELECT id FROM device_audit_log WHERE event_id = :eid LIMIT 1"),
            {"eid": req.event_id},
        )
        if dup.fetchone():
            return {"status": "duplicate", "event_id": req.event_id}

    # Resolve device → user + guardians + location
    context = await _resolve_device(db, req.device_id)
    if not context:
        raise HTTPException(status_code=404, detail="Device not found or not bound to a user")

    # Normalize event
    alert_category = normalize_event(req.event_type)
    now = datetime.now(timezone.utc)

    # Enrich payload
    enriched = {
        **(req.payload or {}),
        "raw_event_type": req.event_type,
        "alert_category": alert_category,
        "trigger_source": "wearable",
        "user_id": context["user_id"],
        "user_name": context["user_name"],
        "user_role": context["user_role"],
        "guardian_ids": context["guardian_ids"],
        "location": context["location"],
        "client_timestamp": req.client_timestamp,
        "server_timestamp": now.isoformat(),
    }

    # Audit log
    await _audit_log(db, req.device_id, context["user_id"],
                     req.event_type, req.event_id, enriched, "wearable")

    # Update device last_seen
    await db.execute(text("""
        UPDATE wearable_devices SET last_seen_at = :now WHERE id = :did
    """), {"now": now, "did": req.device_id})

    await db.commit()

    # Route real hardware events through the same persisted alert +
    # FCM/SMS pipeline as phone SOS/fall events. DEVICE_TEST remains an
    # audit-only diagnostic and never becomes a family safety alert.
    wearable_kind = {
        "BUTTON_PRESS": "sos",
        "BUTTON_LONG_PRESS": "sos",
        "BUTTON_DOUBLE_PRESS": "help_requested",
        "FALL_DETECTED": "fall_detected",
        "IMPACT_DETECTED": "wearable_impact",
        "TAMPER_DETECTED": "wearable_tamper",
        "GEOFENCE_BREACH": "geofence_breach",
        "HEARTRATE_ANOMALY": "health_anomaly",
    }.get(req.event_type)
    severity = {
        "BUTTON_PRESS": "critical",
        "BUTTON_LONG_PRESS": "critical",
        "BUTTON_DOUBLE_PRESS": "critical",
        "FALL_DETECTED": "critical",
        "IMPACT_DETECTED": "high",
        "TAMPER_DETECTED": "high",
        "GEOFENCE_BREACH": "high",
        "HEARTRATE_ANOMALY": "high",
    }.get(req.event_type, "medium")
    event_label = req.event_type.replace("_", " ").title()
    alert_dispatch = None
    if wearable_kind:
        try:
            from app.services.alert_trigger import trigger_alert
            alert_dispatch = await trigger_alert(
                db,
                kind=wearable_kind,
                user_id=context["user_id"],
                severity=severity,
                message=(
                    f"{event_label} reported by paired "
                    f"{context.get('device_uid') or 'wearable'}."
                ),
                details=(
                    "Source: paired BLE wearable/keychain/band. "
                    f"Hardware event ID: {req.event_id or 'not supplied'}."
                ),
                location=context["location"],
                sse_event_type=f"wearable_{req.event_type.lower()}",
                sse_payload_extras=enriched,
                louder=severity == "critical",
                idempotency_key=req.event_id or f"{req.device_id}:{req.event_type}",
                cooldown_s=60,
            )
            await db.commit()
        except Exception as exc:
            logger.error("[WEARABLE_ALERT_DISPATCH_FAIL] %s", exc)

    logger.info(f"[WEARABLE_EVENT] type={req.event_type} -> {alert_category} "
                f"user={context['user_id']} guardians={len(context['guardian_ids'])}")

    return {
        "status": "processed",
        "event_id": req.event_id,
        "alert_category": alert_category,
        "user_id": context["user_id"],
        "guardians_notified": (
            alert_dispatch.guardians_notified
            if alert_dispatch is not None
            else 0
        ),
        "alert_id": (
            alert_dispatch.alert_id
            if alert_dispatch is not None
            else None
        ),
        "escalation_triggered": bool(
            alert_dispatch is not None and severity == "critical"
        ),
    }


# ══════════════════════════════════════════════
# P1 ENDPOINTS
# ══════════════════════════════════════════════

@router.post("/heartbeat")
@limiter.limit("300/minute")
async def device_heartbeat(
    request: Request,
    req: HeartbeatRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Device health telemetry — battery, signal strength, connectivity check."""
    await _ensure_schema(db)

    now = datetime.now(timezone.utc)

    # Verify device
    d = await db.execute(
        text("SELECT id, user_id, battery_level FROM wearable_devices WHERE id = :did"),
        {"did": req.device_id},
    )
    device = d.fetchone()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.user_id or str(device.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail="This wearable is not linked to the signed-in account")
    if req.battery is not None and not 0 <= req.battery <= 100:
        raise HTTPException(status_code=422, detail="Battery must be between 0 and 100")
    if req.heart_rate_bpm is not None and not 20 <= req.heart_rate_bpm <= 260:
        raise HTTPException(status_code=422, detail="Heart rate is outside the supported wearable range")

    # Update device status
    await db.execute(text("""
        UPDATE wearable_devices
        SET last_seen_at = :now, status = 'active',
            battery_level = COALESCE(:battery, battery_level)
            ,heart_rate_bpm = COALESCE(:heart_rate_bpm, heart_rate_bpm)
            ,heart_rate_at = CASE WHEN :heart_rate_bpm IS NULL THEN heart_rate_at ELSE :now END
        WHERE id = :did
    """), {"now": now, "did": req.device_id, "battery": req.battery, "heart_rate_bpm": req.heart_rate_bpm})

    # Log health data
    await db.execute(text("""
        INSERT INTO device_health_log (id, device_id, battery, rssi, heart_rate_bpm, created_at)
        VALUES (:id, :did, :battery, :rssi, :heart_rate_bpm, :now)
    """), {
        "id": str(uuid.uuid4()),
        "did": req.device_id,
        "battery": req.battery,
        "rssi": req.rssi,
        "heart_rate_bpm": req.heart_rate_bpm,
        "now": now,
    })

    await db.commit()

    # Low battery alert from an actual BLE Battery Service reading.
    if req.battery is not None and req.battery < 20 and device.user_id:
        try:
            from app.services.alert_trigger import trigger_alert
            dispatch = await trigger_alert(
                db,
                kind="low_battery",
                user_id=str(device.user_id),
                severity="high" if req.battery <= 10 else "medium",
                message=f"Paired wearable battery is {req.battery}%.",
                details=(
                    "Battery value was read from the paired device's "
                    "standard BLE Battery Service."
                ),
                location=None,
                sse_event_type="device_low_battery",
                sse_payload_extras={
                    "device_id": req.device_id,
                    "battery": req.battery,
                    "user_id": str(device.user_id),
                    "source": "ble_battery_service",
                },
                idempotency_key=f"{req.device_id}:below20",
                cooldown_s=1800,
            )
            await db.commit()
        except Exception as exc:
            logger.error("[WEARABLE_LOW_BATTERY_DISPATCH_FAIL] %s", exc)

    return {"status": "ok", "device_id": req.device_id}


@router.get("/devices")
async def list_devices(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """List all wearable devices linked to the current user."""
    await _ensure_schema(db)

    r = await db.execute(text("""
        SELECT id, device_uid, device_type, device_name, capabilities, status, battery_level,
               heart_rate_bpm, heart_rate_at, last_seen_at, created_at
        FROM wearable_devices WHERE user_id = :uid ORDER BY created_at DESC
    """), {"uid": str(user.id)})

    return {
        "devices": [
            {
                "device_id": str(row.id),
                "device_uid": row.device_uid,
                "device_type": row.device_type,
                "device_name": row.device_name,
                "capabilities": row.capabilities or {},
                "status": row.status,
                "battery_level": row.battery_level,
                "heart_rate_bpm": row.heart_rate_bpm,
                "heart_rate_at": row.heart_rate_at.isoformat() if row.heart_rate_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in r.fetchall()
        ]
    }


def _device_payload(row) -> dict:
    return {
        "device_id": str(row.id),
        "device_type": row.device_type,
        "device_name": row.device_name,
        "capabilities": row.capabilities or {},
        "status": row.status,
        "battery_level": row.battery_level,
        "heart_rate_bpm": row.heart_rate_bpm,
        "heart_rate_at": row.heart_rate_at.isoformat() if row.heart_rate_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/dependent/{dependent_id}/devices")
async def list_dependent_devices(
    dependent_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Read-only device status for a protected member or their linked guardians."""
    await _ensure_schema(db)

    user_exists = await db.execute(
        text("SELECT id FROM users WHERE id = :uid"),
        {"uid": dependent_id},
    )
    if not user_exists.fetchone():
        raise HTTPException(status_code=404, detail="Protected member not found")

    if str(user.id) != str(dependent_id):
        from app.services.alert_trigger import _resolve_guardian_ids
        guardian_ids, _ = await _resolve_guardian_ids(db, dependent_id)
        if str(user.id) not in {str(guardian_id) for guardian_id in guardian_ids}:
            raise HTTPException(status_code=403, detail="You are not linked to this protected member")

    result = await db.execute(text("""
        SELECT id, device_type, device_name, capabilities, status,
               battery_level, heart_rate_bpm, heart_rate_at, last_seen_at, created_at
        FROM wearable_devices
        WHERE user_id = :uid
        ORDER BY created_at DESC
    """), {"uid": dependent_id})

    return {
        "dependent_id": str(dependent_id),
        "devices": [_device_payload(row) for row in result.fetchall()],
    }


@router.get("/audit")
async def audit_trail(
    device_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Event audit trail — for legal proof, insurance, debugging."""
    await _ensure_schema(db)

    conditions = ["wd.user_id = :uid"]
    params: dict = {"uid": str(user.id), "lim": limit}

    if device_id:
        conditions.append("dal.device_id = :did")
        params["did"] = device_id
    if event_type:
        conditions.append("dal.event_type = :etype")
        params["etype"] = event_type

    where = " AND ".join(conditions)
    r = await db.execute(text(f"""
        SELECT dal.id, dal.device_id, dal.event_type, dal.event_id,
               dal.payload, dal.source, dal.created_at
        FROM device_audit_log dal
        JOIN wearable_devices wd ON dal.device_id = wd.id
        WHERE {where}
        ORDER BY dal.created_at DESC
        LIMIT :lim
    """), params)

    return {
        "events": [
            {
                "id": str(row.id),
                "device_id": str(row.device_id),
                "event_type": row.event_type,
                "event_id": row.event_id,
                "payload": row.payload,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in r.fetchall()
        ]
    }
