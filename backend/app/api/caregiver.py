# Caregiver API — Field response interface for caregivers, nurses, facility staff
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.roles import require_role
from app.models.user import User
from app.models.senior import Senior
from app.models.incident import Incident
from app.models.caregiver import CaregiverStatus, VisitLog, HealthNote

router = APIRouter(prefix="/caregiver", tags=["Caregiver"])
logger = logging.getLogger(__name__)

_cg_role = require_role("caregiver", "admin")


# ── Schemas ──

class StatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(available|busy|offline)$")


class VisitCreate(BaseModel):
    senior_id: str
    purpose: str = Field(..., max_length=200)
    status: str = "completed"
    remarks: Optional[str] = None
    visited_at: Optional[str] = None


class NoteCreate(BaseModel):
    senior_id: str
    observation_type: str = Field(..., max_length=100)
    severity: str = Field("low", pattern="^(low|medium|high|critical)$")
    notes: str
    follow_up: Optional[str] = None


class AlertStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(acknowledged|in_progress|resolved|escalated)$")


# ── Profile & Status ──

@router.get("/profile")
async def get_caregiver_profile(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Get caregiver profile with status."""
    cg_status = (await session.execute(
        select(CaregiverStatus).where(CaregiverStatus.user_id == user.id)
    )).scalar_one_or_none()

    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "facility_id": user.facility_id,
        "status": cg_status.status if cg_status else "available",
        "current_assignment_id": str(cg_status.current_assignment_id) if cg_status and cg_status.current_assignment_id else None,
    }


@router.patch("/status")
async def update_caregiver_status(
    body: StatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Update caregiver availability status."""
    now = datetime.now(timezone.utc)
    cg = (await session.execute(
        select(CaregiverStatus).where(CaregiverStatus.user_id == user.id)
    )).scalar_one_or_none()

    if cg:
        cg.status = body.status
        cg.updated_at = now
    else:
        cg = CaregiverStatus(user_id=user.id, status=body.status, facility_id=user.facility_id, updated_at=now)
        session.add(cg)

    return {"status": body.status, "updated_at": now.isoformat()}


# ── Assigned Users ──

@router.get("/assigned-users")
async def get_assigned_users(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Get seniors assigned to caregiver's facility or directly assigned incidents."""
    seniors_q = select(Senior)
    if user.facility_id:
        # Get seniors whose guardian belongs to the same facility
        guardian_ids = (await session.execute(
            select(User.id).where(User.facility_id == user.facility_id)
        )).scalars().all()
        if guardian_ids:
            seniors_q = seniors_q.where(Senior.guardian_id.in_(guardian_ids))

    result = await session.execute(seniors_q.order_by(Senior.full_name))
    seniors = result.scalars().all()

    # Get incident counts per senior
    seniors_data = []
    for s in seniors:
        active_incidents = (await session.execute(
            select(func.count()).select_from(Incident).where(
                Incident.senior_id == s.id,
                Incident.status.in_(["open", "in_progress"])
            )
        )).scalar() or 0

        last_visit = (await session.execute(
            select(VisitLog.visited_at).where(
                VisitLog.senior_id == s.id,
                VisitLog.caregiver_id == user.id,
            ).order_by(VisitLog.visited_at.desc()).limit(1)
        )).scalar_one_or_none()

        seniors_data.append({
            "id": str(s.id),
            "full_name": s.full_name,
            "age": s.age,
            "medical_notes": s.medical_notes,
            "active_incidents": active_incidents,
            "last_visit": last_visit.isoformat() if last_visit else None,
            "risk_status": "high" if active_incidents > 0 else "normal",
        })

    return {"users": seniors_data, "total": len(seniors_data)}


# ── Alerts (incidents assigned to this caregiver) ──

@router.get("/alerts")
async def get_caregiver_alerts(
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Get incidents assigned to this caregiver."""
    q = select(Incident).where(Incident.assigned_to_user_id == user.id)
    if status:
        q = q.where(Incident.status == status)
    q = q.order_by(Incident.created_at.desc())

    result = await session.execute(q)
    incidents = result.scalars().all()

    alerts = []
    for inc in incidents:
        senior = (await session.execute(
            select(Senior).where(Senior.id == inc.senior_id)
        )).scalar_one_or_none()

        alerts.append({
            "id": str(inc.id),
            "incident_type": inc.incident_type,
            "severity": inc.severity,
            "status": inc.status,
            "senior_name": senior.full_name if senior else "Unknown",
            "senior_id": str(inc.senior_id),
            "created_at": inc.created_at.isoformat(),
            "assigned_at": inc.assigned_at.isoformat() if inc.assigned_at else None,
            "acknowledged_at": inc.acknowledged_at.isoformat() if inc.acknowledged_at else None,
        })

    return {"alerts": alerts, "total": len(alerts)}


@router.patch("/alerts/{incident_id}/acknowledge")
async def acknowledge_alert(
    incident_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Acknowledge an assigned incident."""
    inc = (await session.execute(
        select(Incident).where(Incident.id == uuid.UUID(incident_id))
    )).scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")
    if inc.assigned_to_user_id != user.id:
        raise HTTPException(403, "Not assigned to you")

    now = datetime.now(timezone.utc)
    inc.acknowledged_at = now
    inc.acknowledged_by_user_id = user.id
    inc.acknowledged_via = "caregiver_dashboard"

    return {"acknowledged": True, "incident_id": incident_id, "acknowledged_at": now.isoformat()}


@router.patch("/alerts/{incident_id}/status")
async def update_alert_status(
    incident_id: str,
    body: AlertStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Update alert/incident status (in_progress, resolved, escalated)."""
    inc = (await session.execute(
        select(Incident).where(Incident.id == uuid.UUID(incident_id))
    )).scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")

    now = datetime.now(timezone.utc)

    if body.status == "resolved":
        inc.status = "resolved"
        inc.resolved_at = now
        # Free up caregiver
        cg = (await session.execute(
            select(CaregiverStatus).where(CaregiverStatus.user_id == user.id)
        )).scalar_one_or_none()
        if cg:
            cg.current_assignment_id = None
            cg.status = "available"
    elif body.status == "in_progress":
        inc.status = "in_progress"
    elif body.status == "escalated":
        inc.escalated = True
        inc.escalated_at = now
    elif body.status == "acknowledged":
        inc.acknowledged_at = now
        inc.acknowledged_by_user_id = user.id

    return {"status": body.status, "incident_id": incident_id}


# ── Visit Logs ──

@router.get("/visits")
async def get_visits(
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Get caregiver visit logs."""
    result = await session.execute(
        select(VisitLog).where(VisitLog.caregiver_id == user.id)
        .order_by(VisitLog.visited_at.desc()).limit(limit)
    )
    visits = result.scalars().all()

    data = []
    for v in visits:
        senior = (await session.execute(
            select(Senior.full_name).where(Senior.id == v.senior_id)
        )).scalar_one_or_none()
        data.append({
            "id": str(v.id),
            "senior_name": senior or "Unknown",
            "senior_id": str(v.senior_id),
            "purpose": v.purpose,
            "status": v.status,
            "remarks": v.remarks,
            "visited_at": v.visited_at.isoformat(),
        })

    return {"visits": data, "total": len(data)}


@router.post("/visits", status_code=201)
async def create_visit(
    body: VisitCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Log a visit."""
    now = datetime.now(timezone.utc)
    visited_at = now
    if body.visited_at:
        try:
            visited_at = datetime.fromisoformat(body.visited_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    visit = VisitLog(
        caregiver_id=user.id,
        senior_id=uuid.UUID(body.senior_id),
        purpose=body.purpose,
        status=body.status,
        remarks=body.remarks,
        visited_at=visited_at,
        created_at=now,
    )
    session.add(visit)
    await session.flush()

    return {"id": str(visit.id), "purpose": visit.purpose, "visited_at": visit.visited_at.isoformat()}


# ── Health Notes ──

@router.get("/notes")
async def get_notes(
    senior_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Get health notes."""
    q = select(HealthNote).where(HealthNote.caregiver_id == user.id)
    if senior_id:
        q = q.where(HealthNote.senior_id == uuid.UUID(senior_id))
    q = q.order_by(HealthNote.created_at.desc()).limit(limit)

    result = await session.execute(q)
    notes = result.scalars().all()

    data = []
    for n in notes:
        senior = (await session.execute(
            select(Senior.full_name).where(Senior.id == n.senior_id)
        )).scalar_one_or_none()
        data.append({
            "id": str(n.id),
            "senior_name": senior or "Unknown",
            "senior_id": str(n.senior_id),
            "observation_type": n.observation_type,
            "severity": n.severity,
            "notes": n.notes,
            "follow_up": n.follow_up,
            "created_at": n.created_at.isoformat(),
        })

    return {"notes": data, "total": len(data)}


@router.post("/notes", status_code=201)
async def create_note(
    body: NoteCreate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_cg_role),
):
    """Create a health note."""
    now = datetime.now(timezone.utc)
    note = HealthNote(
        caregiver_id=user.id,
        senior_id=uuid.UUID(body.senior_id),
        observation_type=body.observation_type,
        severity=body.severity,
        notes=body.notes,
        follow_up=body.follow_up,
        created_at=now,
    )
    session.add(note)
    await session.flush()

    return {"id": str(note.id), "observation_type": note.observation_type, "created_at": now.isoformat()}
