# Telemetry Service
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.device import Device
from app.models.senior import Senior
from app.models.telemetry import Telemetry
from app.models.incident import Incident, DEFAULT_ESCALATION_MINUTES
from app.schemas.telemetry import TelemetryCreate
from app.services.event_broadcaster import broadcaster, serialize_for_sse
from app.services.incident_events import log_event


# Rule engine: metric types that trigger incidents
INCIDENT_RULES = {
    "sos": {"incident_type": "sos_alert", "severity": "critical"},
    "fall_detected": {"incident_type": "fall_alert", "severity": "high"},
}

# Metric types that ONLY update device state — no incident, no escalation
DEVICE_STATE_ONLY_METRICS = {"heartbeat"}


async def ingest_telemetry(
    session: AsyncSession,
    telemetry_create: TelemetryCreate,
) -> Telemetry:
    """
    Ingest telemetry data and trigger incidents based on rules.
    
    - Inserts telemetry row
    - For heartbeat: updates device last_seen/status only — no incident
    - If metric_type matches incident rule, creates an Incident
    - Broadcasts SSE event to guardian
    - Returns the created telemetry
    
    Raises:
        ValueError: If device not found
    """
    # Look up device by device_identifier
    stmt = (
        select(Device)
        .options(selectinload(Device.senior))
        .where(Device.device_identifier == telemetry_create.device_identifier)
    )
    result = await session.execute(stmt)
    device = result.scalar_one_or_none()
    
    if not device:
        raise ValueError(f"Device with identifier '{telemetry_create.device_identifier}' not found")
    
    # Build metric_value for heartbeat from top-level fields
    metric_value = telemetry_create.metric_value
    if telemetry_create.metric_type == "heartbeat":
        hb_data = {}
        if telemetry_create.battery_level is not None:
            hb_data["battery_level"] = telemetry_create.battery_level
        if telemetry_create.signal_strength is not None:
            hb_data["signal_strength"] = telemetry_create.signal_strength
        metric_value = hb_data if hb_data else metric_value

    # Create telemetry record
    telemetry = Telemetry(
        device_id=device.id,
        metric_type=telemetry_create.metric_type,
        metric_value=metric_value,
    )
    session.add(telemetry)
    
    # Heartbeat: update device state + auto-recover if was offline
    if telemetry_create.metric_type in DEVICE_STATE_ONLY_METRICS:
        was_offline = device.status == "offline"
        device.last_seen = datetime.now(timezone.utc)
        device.status = "online"

        if was_offline:
            # Auto-resolve any open device_offline incidents for this device
            open_offline_incidents = (await session.execute(
                select(Incident)
                .where(and_(
                    Incident.device_id == device.id,
                    Incident.incident_type == "device_offline",
                    Incident.status == "open",
                ))
            )).scalars().all()

            for inc in open_offline_incidents:
                inc.status = "resolved"
                inc.resolved_at = datetime.now(timezone.utc)
                await session.flush()
                await log_event(session, inc.id, "device_back_online", metadata={
                    "device_identifier": telemetry_create.device_identifier,
                    "resolved_by": "heartbeat_auto_recovery",
                })

            # Broadcast SSE update if incidents were resolved
            if open_offline_incidents and device.senior:
                guardian_id = str(device.senior.guardian_id)
                for inc in open_offline_incidents:
                    incident_data = serialize_for_sse({
                        "id": inc.id,
                        "senior_id": inc.senior_id,
                        "device_id": inc.device_id,
                        "incident_type": inc.incident_type,
                        "severity": inc.severity,
                        "status": inc.status,
                        "resolved_at": inc.resolved_at,
                        "created_at": inc.created_at,
                    })
                    await broadcaster.broadcast_incident_updated(guardian_id, incident_data)

        await session.commit()
        await session.refresh(telemetry)
        return telemetry
    
    incident = None
    # Check if this metric type triggers an incident
    if telemetry_create.metric_type in INCIDENT_RULES:
        rule = INCIDENT_RULES[telemetry_create.metric_type]
        severity = rule["severity"]
        
        # Get escalation time based on severity
        escalation_minutes = DEFAULT_ESCALATION_MINUTES.get(severity, 15)
        
        incident = Incident(
            senior_id=device.senior_id,
            device_id=device.id,
            incident_type=rule["incident_type"],
            severity=severity,
            escalation_minutes=escalation_minutes,
        )
        session.add(incident)
    
    # Commit transaction atomically
    await session.commit()
    await session.refresh(telemetry)
    
    # Broadcast incident created event if applicable
    if incident:
        await session.refresh(incident)
        guardian_id = str(device.senior.guardian_id)
        
        incident_data = serialize_for_sse({
            "id": incident.id,
            "senior_id": incident.senior_id,
            "device_id": incident.device_id,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "status": incident.status,
            "escalated": incident.escalated,
            "escalation_minutes": incident.escalation_minutes,
            "created_at": incident.created_at,
        })
        
        await broadcaster.broadcast_incident_created(guardian_id, incident_data)
        
        # Log audit event
        await log_event(session, incident.id, "incident_created", metadata={
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "device_identifier": telemetry_create.device_identifier,
        })
        await session.commit()
    
    return telemetry


async def get_telemetry_by_device(
    session: AsyncSession,
    device_id,
    limit: int = 100,
):
    """Get recent telemetry for a device."""
    stmt = (
        select(Telemetry)
        .where(Telemetry.device_id == device_id)
        .order_by(Telemetry.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()
