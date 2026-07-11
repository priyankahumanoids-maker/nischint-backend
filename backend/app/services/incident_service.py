# Incident Service
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.incident import Incident
from app.models.senior import Senior
from app.services.event_broadcaster import broadcaster, serialize_for_sse


# Valid status transitions
VALID_TRANSITIONS = {
    "acknowledge": {"from": ["open"], "to": "acknowledged"},
    "resolve": {"from": ["open", "acknowledged"], "to": "resolved"},
    "false_alarm": {"from": ["open", "acknowledged"], "to": "false_alarm"},
}


async def get_incidents_by_guardian(
    session: AsyncSession,
    guardian_id: UUID,
    status: Optional[str] = None,
) -> Sequence[Incident]:
    """
    Get all incidents for seniors in this guardian's FAMILY scope.
    Optionally filter by status.
    """
    from app.services.dashboard_service import _get_family_senior_ids
    senior_ids = await _get_family_senior_ids(session, guardian_id)

    if not senior_ids:
        return []

    # Get incidents for those seniors
    stmt = select(Incident).where(Incident.senior_id.in_(senior_ids))

    if status:
        stmt = stmt.where(Incident.status == status)

    stmt = stmt.order_by(Incident.created_at.desc())

    result = await session.execute(stmt)
    return result.scalars().all()


async def get_incident_by_id(
    session: AsyncSession,
    incident_id: UUID,
) -> Optional[Incident]:
    """Get an incident by ID."""
    stmt = select(Incident).where(Incident.id == incident_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_guardian_id_for_incident(session: AsyncSession, incident: Incident) -> str:
    """Get guardian_id for an incident by looking up the senior."""
    stmt = select(Senior.guardian_id).where(Senior.id == incident.senior_id)
    result = await session.execute(stmt)
    guardian_id = result.scalar_one_or_none()
    return str(guardian_id) if guardian_id else None


async def _broadcast_incident_update(session: AsyncSession, incident: Incident):
    """Broadcast incident update to guardian."""
    guardian_id = await _get_guardian_id_for_incident(session, incident)
    if guardian_id:
        incident_data = serialize_for_sse({
            "id": incident.id,
            "senior_id": incident.senior_id,
            "device_id": incident.device_id,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "status": incident.status,
            "escalated": incident.escalated,
            "escalation_minutes": incident.escalation_minutes,
            "escalated_at": incident.escalated_at,
            "created_at": incident.created_at,
            "resolved_at": incident.resolved_at,
        })
        await broadcaster.broadcast_incident_updated(guardian_id, incident_data)


async def _transition_incident(
    session: AsyncSession,
    incident_id: UUID,
    action: str,
) -> Incident:
    """
    Internal helper to transition incident status.
    
    Raises:
        ValueError: If incident not found or invalid transition
    """
    incident = await get_incident_by_id(session, incident_id)
    
    if not incident:
        raise ValueError(f"Incident with id {incident_id} not found")
    
    transition = VALID_TRANSITIONS[action]
    
    if incident.status not in transition["from"]:
        raise ValueError(
            f"Cannot {action} incident in '{incident.status}' status. "
            f"Valid states: {transition['from']}"
        )
    
    incident.status = transition["to"]
    
    # Set resolved_at for terminal states
    if transition["to"] in ["resolved", "false_alarm"]:
        incident.resolved_at = datetime.now(timezone.utc)
    
    await session.commit()
    await session.refresh(incident)
    
    # Broadcast update
    await _broadcast_incident_update(session, incident)
    
    # Log audit event
    from app.services.incident_events import log_event
    await log_event(session, incident.id, action, metadata={"new_status": transition["to"]})
    await session.commit()
    
    return incident


async def acknowledge_incident(
    session: AsyncSession,
    incident_id: UUID,
    current_user_id: UUID,
    current_user_name: str,
    channel: str = "dashboard",
) -> Incident:
    """
    Acknowledge an incident.
    Can only acknowledge if status == "open".
    """
    incident = await get_incident_by_id(session, incident_id)
    
    if not incident:
        raise ValueError(f"Incident with id {incident_id} not found")
    
    if incident.status not in ["open"]:
        raise ValueError(
            f"Cannot acknowledge incident in '{incident.status}' status. "
            f"Valid states: ['open']"
        )
    
    incident.status = "acknowledged"
    incident.acknowledged_by_user_id = current_user_id
    incident.acknowledged_at = datetime.now(timezone.utc)
    incident.acknowledged_via = channel
    
    await session.commit()
    await session.refresh(incident)
    await _broadcast_incident_update(session, incident)
    
    from app.services.incident_events import log_event
    await log_event(session, incident.id, "acknowledged", channel, {
        "acknowledged_by": str(current_user_id),
        "acknowledged_by_name": current_user_name,
        "acknowledged_via": channel,
    })
    await session.commit()
    
    return incident


async def resolve_incident(
    session: AsyncSession,
    incident_id: UUID,
) -> Incident:
    """
    Resolve an incident.
    Can resolve if status in ["open", "acknowledged"].
    Sets resolved_at timestamp.
    """
    return await _transition_incident(session, incident_id, "resolve")


async def mark_false_alarm(
    session: AsyncSession,
    incident_id: UUID,
) -> Incident:
    """
    Mark an incident as false alarm.
    Can mark if status in ["open", "acknowledged"].
    Sets resolved_at timestamp.
    """
    return await _transition_incident(session, incident_id, "false_alarm")
