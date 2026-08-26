# Guardian Family Dashboard API
# Consumer-facing endpoints for guardians to monitor loved ones.

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.guardian import GuardianAlert
from app.core.product_roles import is_primary_guardian, is_protected_member, normalize_role

router = APIRouter(prefix="/guardian/dashboard", tags=["guardian-dashboard"])


class SafetyCheckRequest(BaseModel):
    user_id: str  # child's user ID — works with or without active session
    session_id: str | None = None  # optional: legacy callers may pass session_id


@router.get("/loved-ones")
async def get_loved_ones(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get all people this guardian monitors with their live status."""
    from app.services.guardian_dashboard_engine import get_loved_ones as _get
    return await _get(session, user.email, str(user.id), user_role=getattr(user, "role", None))


@router.get("/sessions")
async def get_sessions(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get all active sessions for guardian's loved ones."""
    from app.services.guardian_dashboard_engine import get_active_sessions
    return {"sessions": await get_active_sessions(session, user.email, str(user.id), user_role=getattr(user, "role", None))}


@router.get("/alerts")
async def get_alerts(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get recent alerts. Guardian sees alerts for loved ones. Child sees check-ins addressed to them."""
    if is_protected_member(user.role):
        from app.services.guardian_dashboard_engine import get_child_alerts
        return {"alerts": await get_child_alerts(session, str(user.id), limit)}
    from app.services.guardian_dashboard_engine import get_alerts as _get
    return {"alerts": await _get(session, user.email, limit, str(user.id), user_role=getattr(user, "role", None))}


@router.get("/history")
async def get_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Get completed journey history for guardian's loved ones."""
    from app.services.guardian_dashboard_engine import get_session_history
    return {"history": await get_session_history(session, user.email, limit, str(user.id), user_role=getattr(user, "role", None))}


@router.post("/end-session/{session_id}")
async def end_session(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """End a journey owned by the caller or one managed by the primary guardian."""
    from app.models.guardian import GuardianSession
    from app.services.guardian_dashboard_engine import _get_linked_user_ids
    from app.services.guardian_mode_engine import stop_session

    try:
        session_uuid = uuid.UUID(str(session_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Session not found")

    journey = (await session.execute(
        select(GuardianSession).where(GuardianSession.id == session_uuid)
    )).scalar_one_or_none()
    if journey is None:
        raise HTTPException(status_code=404, detail="Session not found")

    caller_role = normalize_role(getattr(user, "role", None))
    authorized = str(journey.user_id) == str(user.id)

    if not authorized and caller_role in {"admin", "operator"}:
        authorized = True

    if not authorized and is_primary_guardian(caller_role):
        linked_user_ids = await _get_linked_user_ids(
            session,
            user.email,
            str(user.id),
            getattr(user, "role", None),
            include_checkin_recovery=False,
        )
        authorized = any(
            str(linked_id) == str(journey.user_id)
            for linked_id in linked_user_ids
        )

    if not authorized:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to end this journey session.",
        )

    result = await stop_session(session, session_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/request-check")
async def request_check(
    req: SafetyCheckRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian requests a safety check from a monitored user. Creates a CheckIn record (DB source of truth) and sends push notification."""
    from app.services.checkin_service import create_checkin
    result = await create_checkin(session, str(user.id), req.user_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class AlertAckRequest(BaseModel):
    event_id: str


@router.post("/alert/acknowledge")
async def acknowledge_alert(
    req: AlertAckRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian acknowledges an alert — cancels the guardian failsafe escalation timer."""
    import logging
    logger = logging.getLogger(__name__)

    from app.services.guardian_dashboard_engine import _get_linked_user_ids

    linked_user_ids = await _get_linked_user_ids(
        session,
        user.email,
        str(user.id),
        getattr(user, "role", None),
    )
    try:
        event_uuid = uuid.UUID(req.event_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid alert ID")

    alert = (await session.execute(
        select(GuardianAlert).where(
            GuardianAlert.id == event_uuid,
            GuardianAlert.user_id.in_(linked_user_ids),
        )
    )).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found for this guardian")

    alert.ack_status = "acknowledged"
    alert.ack_type = "resolved"
    alert.acked_by = user.id
    alert.acked_at = datetime.now(timezone.utc)
    await session.flush()

    from app.services.auto_escalation_engine import cancel_guardian_failsafe
    cancelled = cancel_guardian_failsafe(req.event_id)

    logger.info(
        f"[ALERT_ACK] guardian={user.id} event={req.event_id} "
        f"failsafe_cancelled={cancelled}"
    )

    return {
        "status": "acknowledged",
        "event_id": req.event_id,
        "failsafe_cancelled": cancelled,
    }
