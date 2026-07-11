# Incidents Router
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.schemas.incident import IncidentCreate, IncidentResponse
from app.services import incident_service
from app.services.incident_events import get_events

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new incident for a senior. Used by device sensors and safety events."""
    from app.models.incident import Incident, DEFAULT_ESCALATION_MINUTES
    from app.services import senior_service

    senior = await senior_service.get_senior_by_id(session, payload.senior_id)
    if not senior:
        raise HTTPException(status_code=404, detail="Senior not found")

    incident = Incident(
        senior_id=payload.senior_id,
        device_id=payload.device_id,
        incident_type=payload.incident_type,
        severity=payload.severity,
        escalation_minutes=DEFAULT_ESCALATION_MINUTES.get(payload.severity, 15),
    )
    session.add(incident)
    await session.commit()
    await session.refresh(incident)
    return incident


@router.get("/metrics/response")
async def get_response_metrics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Guardian response metrics for Command Center dashboard."""
    from sqlalchemy import text

    result = await session.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'open') AS active_unresolved,
            COUNT(*) FILTER (WHERE acknowledged_at IS NOT NULL) AS acknowledged_count,
            COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved_count,
            COUNT(*) FILTER (WHERE escalated = TRUE) AS escalation_count,
            AVG(EXTRACT(EPOCH FROM (acknowledged_at - created_at))) FILTER (WHERE acknowledged_at IS NOT NULL) AS avg_response_seconds,
            AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) FILTER (WHERE resolved_at IS NOT NULL) AS avg_resolution_seconds
        FROM incidents
        WHERE created_at > NOW() - INTERVAL '30 days'
    """))
    row = result.fetchone()

    total = row[0] or 0
    ack_count = row[2] or 0
    ack_rate = round((ack_count / total * 100), 1) if total > 0 else 0
    avg_response = round(row[5] or 0, 1)
    avg_resolution = round(row[6] or 0, 1)

    guardian_result = await session.execute(text("""
        SELECT
            u.full_name,
            COUNT(i.id) AS incident_count,
            COUNT(i.id) FILTER (WHERE i.acknowledged_at IS NOT NULL) AS ack_count,
            AVG(EXTRACT(EPOCH FROM (i.acknowledged_at - i.created_at))) FILTER (WHERE i.acknowledged_at IS NOT NULL) AS avg_resp
        FROM incidents i
        JOIN seniors s ON i.senior_id = s.id
        JOIN users u ON s.guardian_id = u.id
        WHERE i.created_at > NOW() - INTERVAL '30 days'
        GROUP BY u.id, u.full_name
        ORDER BY incident_count DESC
        LIMIT 20
    """))

    guardians = [
        {
            "name": r[0] or "Unknown",
            "incidents": r[1],
            "acknowledged": r[2],
            "avg_response_seconds": round(r[3] or 0, 1),
        }
        for r in guardian_result.fetchall()
    ]

    return {
        "period": "30d",
        "total_incidents": total,
        "active_unresolved": row[1] or 0,
        "acknowledged_count": ack_count,
        "resolved_count": row[3] or 0,
        "escalation_count": row[4] or 0,
        "acknowledgment_rate_pct": ack_rate,
        "avg_response_seconds": avg_response,
        "avg_resolution_seconds": avg_resolution,
        "guardians": guardians,
    }


@router.get("", response_model=List[IncidentResponse])
async def get_incidents(
    guardian_id: UUID = Query(..., description="Guardian user ID"),
    status: Optional[str] = Query(None, description="Filter by status (open, acknowledged, resolved, false_alarm)"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get all incidents for seniors under a guardian.
    Requires authentication.
    """
    incidents = await incident_service.get_incidents_by_guardian(
        session, guardian_id, status
    )
    return incidents


@router.patch("/{incident_id}/acknowledge", response_model=IncidentResponse)
async def acknowledge_incident(
    incident_id: UUID,
    channel: str = Query("dashboard", description="Acknowledge via: dashboard, sms, push, email"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Acknowledge an incident.
    Can only acknowledge if status == "open".
    """
    try:
        incident = await incident_service.acknowledge_incident(
            session, incident_id, current_user.id,
            current_user.full_name or current_user.email,
            channel,
        )
        return incident
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{incident_id}/resolve", response_model=IncidentResponse)
async def resolve_incident(
    incident_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Resolve an incident.
    Can resolve if status in ["open", "acknowledged"].
    Sets resolved_at timestamp.
    """
    try:
        incident = await incident_service.resolve_incident(session, incident_id)
        return incident
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{incident_id}/false-alarm", response_model=IncidentResponse)
async def mark_false_alarm(
    incident_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Mark an incident as false alarm.
    Can mark if status in ["open", "acknowledged"].
    Sets resolved_at timestamp.
    """
    try:
        incident = await incident_service.mark_false_alarm(session, incident_id)
        return incident
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))



@router.get("/{incident_id}/events")
async def get_incident_events(
    incident_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get the full audit trail of events for an incident."""
    return await get_events(session, incident_id)


@router.get("/{incident_id}/notification-jobs")
async def get_incident_notification_jobs(
    incident_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all notification jobs for an incident. Guardian sees only their own incidents."""
    from sqlalchemy import select, text
    from app.models.notification_job import NotificationJob

    # Verify the incident belongs to this guardian's seniors
    ownership = await session.execute(
        text(
            "SELECT i.id FROM incidents i "
            "JOIN seniors s ON i.senior_id = s.id "
            "WHERE i.id = :iid AND s.guardian_id = :gid"
        ),
        {"iid": incident_id, "gid": current_user.id},
    )
    if not ownership.fetchone():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    result = await session.execute(
        select(NotificationJob)
        .where(NotificationJob.incident_id == incident_id)
        .order_by(NotificationJob.created_at.asc())
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "channel": j.channel,
            "recipient": j.recipient,
            "status": j.status,
            "attempts": j.attempts,
            "last_attempt_at": j.last_attempt_at.isoformat() if j.last_attempt_at else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "escalation_level": j.payload.get("escalation_level") if j.payload else None,
        }
        for j in jobs
    ]
