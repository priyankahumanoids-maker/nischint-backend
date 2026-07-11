# Guardian Family Dashboard API
# Consumer-facing endpoints for guardians to monitor loved ones.

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User

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
    if user.role in ("child", "kid"):
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
    """End a journey session (callable by guardian or child)."""
    from app.services.guardian_mode_engine import stop_session
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
