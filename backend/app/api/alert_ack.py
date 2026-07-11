"""Alert ACK API — the endpoint a guardian hits to close the loop.

Routes:
  POST /api/alerts/{alert_id}/ack    — guardian / admin acknowledges
  GET  /api/alerts/pending           — operator console: pending ACK list
  GET  /api/alerts/metrics           — Time-To-First-Human north-star metric
"""
from __future__ import annotations
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.guardian import GuardianAlert
from app.models.user import User

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AckBody(BaseModel):
    ack_type: str = Field(default="seen", description="seen | acting | resolved")
    confirmed: bool = Field(default=False,
                            description="Required true for resolved (misclick guard)")


@router.post("/{alert_id}/ack")
async def ack_alert(
    alert_id: uuid.UUID,
    body: Optional[AckBody] = Body(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """A guardian (or admin/operator) acknowledges receipt of a
    safety alert. Tri-state: `seen` (default), `acting`, `resolved`.

    Misclick protection: `resolved` requires `confirmed=true` in the
    request body. The client enforces this with a "hold 1.5s" or
    double-tap UX; the server refuses unconfirmed resolves so a
    single accidental tap can never close out a real emergency.
    """
    from app.services.alert_ack_engine import acknowledge_alert
    ack_type  = (body.ack_type if body else "seen") or "seen"
    confirmed = bool(body.confirmed) if body else False
    result = await acknowledge_alert(session, alert_id, current_user.id,
                                      ack_type=ack_type, confirmed=confirmed)
    if not result.get("acknowledged") and result.get("reason") == "not_found":
        raise HTTPException(404, "alert not found")
    if not result.get("acknowledged") and result.get("reason") == "invalid_ack_type":
        raise HTTPException(400, f"invalid ack_type — must be one of {result['valid']}")
    if not result.get("acknowledged") and result.get("reason") == "confirmation_required":
        # 409 Conflict — the request is well-formed but contradicts
        # the misclick-guard policy. Client should re-submit with
        # confirmed=true after an intentional UI gesture.
        raise HTTPException(409, detail=result)
    return result


@router.post("/{alert_id}/heartbeat")
async def acting_heartbeat(
    alert_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Guardian liveness ping while in `acting` state. Called by the
    client every ~10 s to prove the responder hasn't dropped off
    (phone died, network gone, panic). If the engine doesn't see a
    beat for 30 s while `ack_type='acting'`, it fires
    `alert_acting_lapsed` so operators can pull in another guardian.
    """
    from app.services.alert_ack_engine import heartbeat_acting
    result = await heartbeat_acting(session, alert_id, current_user.id)
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "not_found":
            raise HTTPException(404, "alert not found")
        if reason == "not_acting":
            raise HTTPException(409, detail=result)
        if reason == "not_owner":
            raise HTTPException(403, detail=result)
    return result


@router.get("/pending",
            dependencies=[Depends(require_role(["admin", "operator"]))])
async def list_pending_alerts(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
):
    """Operator console: pending ACK alerts + their escalation status."""
    rows = (await session.execute(
        select(GuardianAlert)
        .where(GuardianAlert.ack_status.in_(("pending", "escalated")))
        .order_by(GuardianAlert.ack_deadline.asc())
        .limit(limit)
    )).scalars().all()
    return {
        "count": len(rows),
        "alerts": [
            {
                "id":              str(a.id),
                "session_id":      str(a.session_id),
                "alert_type":      a.alert_type,
                "severity":        a.severity,
                "message":         a.message,
                "ack_status":      a.ack_status,
                "ack_type":        a.ack_type,
                "ack_deadline":    a.ack_deadline.isoformat() if a.ack_deadline else None,
                "ack_timeout_sec": a.ack_timeout_sec,
                "seen_deadline":   a.seen_deadline.isoformat() if a.seen_deadline else None,
                "escalation_step":    a.escalation_step,
                "escalation_history": a.escalation_history,
                "context":         a.context_json or {},
                "created_at":      a.created_at.isoformat(),
            } for a in rows
        ],
    }


@router.get("/metrics",
            dependencies=[Depends(require_role(["admin", "operator"]))])
async def alert_metrics(
    window_days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_db_session),
):
    """Time-To-First-Human (TTFH) — the Control Layer north-star metric.

    Returns p50 / p95 / avg ACK latency over `window_days`, plus
    counts of acked vs escalated alerts. Push success and SSE uptime
    are inputs; this is the actual outcome.
    """
    from app.services.alert_ack_engine import get_ttfh_metrics
    return await get_ttfh_metrics(session, window_days=window_days)
