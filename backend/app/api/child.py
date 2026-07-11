# Child API — link code generation + standalone help request
import random
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.services import redis_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/child", tags=["child"])

LINK_CODE_TTL = 300  # 5 minutes


class HelpRequest(BaseModel):
    lat: float = Field(0.0, ge=-90, le=90)
    lng: float = Field(0.0, ge=-180, le=180)
    message: Optional[str] = Field(None, max_length=500)


@router.post("/help-request")
async def request_help(
    req: HelpRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    Standalone 'Need Help' — child can press anytime to alert all linked guardians.
    Lighter than SOS: creates GuardianAlert + broadcasts safety_alert via SSE.
    """
    user_id = str(user.id)
    child_name = user.full_name or user.email or "Child"
    now = datetime.now(timezone.utc)

    logger.info(f"[HELP_REQUEST_RECEIVED] child={user_id} name={child_name} lat={req.lat} lng={req.lng}")

    # Create a SafetyEvent record
    from app.models.safety_event import SafetyEvent
    safety_event = SafetyEvent(
        user_id=user.id,
        risk_score=0.8,
        risk_level="high",
        signals={"help_request": 1.0, "manual": True},
        primary_event="help_request",
        location_lat=req.lat,
        location_lng=req.lng,
        status="active",
    )
    session.add(safety_event)
    await session.flush()
    event_id = str(safety_event.id)
    logger.info(f"[HELP_EVENT_CREATED] SafetyEvent id={event_id} child={user_id}")

    # Find all linked guardians and broadcast
    from app.models.guardian import Guardian, GuardianAlert, GuardianSession
    from app.services.event_broadcaster import broadcaster

    # ── Migration to unified `trigger_alert` (NISCH-001 Phase 2) ──
    # Behind feature flag `ALERT_TRIGGER_V2_HELP_REQUEST`. When True,
    # the unified path replaces the inline guardian fan-out + push +
    # GuardianAlert creation block. Operator broadcast and ACK-engine
    # wiring stay in this file.
    import os as _os
    _use_v2 = _os.environ.get("ALERT_TRIGGER_V2_HELP_REQUEST", "false").lower() == "true"

    safety_alert_data = {
        "type": "HELP_REQUEST",
        "severity": "HIGH",
        "child_id": user_id,
        "child_name": child_name,
        "safety_event_id": event_id,
        "message": req.message or f"{child_name} needs help!",
        "lat": req.lat,
        "lng": req.lng,
        "timestamp": now.isoformat(),
    }

    if _use_v2:
        from app.services.alert_trigger import trigger_alert
        active_ses_result = await session.execute(
            select(GuardianSession).where(
                GuardianSession.user_id == user.id,
                GuardianSession.status == "active",
            ).order_by(GuardianSession.started_at.desc()).limit(1)
        )
        active_ses = active_ses_result.scalar_one_or_none()
        result = await trigger_alert(
            session,
            kind="help_requested",
            user_id=user_id,
            severity="critical",
            message=req.message or f"{child_name} pressed Need Help!",
            details=f"Manual help request. SafetyEvent: {event_id}",
            location={"lat": req.lat, "lng": req.lng} if req.lat and req.lng else None,
            session_id=str(active_ses.id) if active_ses else None,
            sse_event_type="safety_alert",
            sse_payload_extras=safety_alert_data,
            louder=True,
            idempotency_key=f"help:{event_id}",
            cooldown_s=30,
        )
        notified = result.guardians_notified
        guardian_ids = []  # already SSE-fanned by trigger_alert; legacy push loop below skipped

        # Operator broadcast (separate audience from guardians).
        await broadcaster.broadcast_to_operators("safety_alert", safety_alert_data)

        # Wire ACK engine on the GuardianAlert row that trigger_alert created.
        try:
            if result.alert_id:
                alert_row = (await session.execute(
                    select(GuardianAlert).where(GuardianAlert.id == uuid.UUID(result.alert_id))
                )).scalar_one_or_none()
                if alert_row is not None:
                    from app.services.alert_ack_engine import (
                        severity_requires_ack, mark_for_ack,
                    )
                    if severity_requires_ack(alert_row.severity):
                        await mark_for_ack(session, alert_row)
        except Exception:
            logger.exception("[help_request V2] mark_for_ack wiring failed (non-fatal)")

        logger.warning(
            f"[ALERT_TRIGGER_V2] help_request dispatched: {result.to_dict()}"
        )
        await session.commit()

        # Auto-escalation (still scheduled — not part of trigger_alert's scope).
        try:
            from app.services.auto_escalation_engine import schedule_escalation
            schedule_escalation(event_id, user_id, child_name, "help_request")
        except Exception as e:
            logger.error(f"Auto-escalation schedule failed: {e}")

        return {
            "status": "help_sent",
            "event_id": event_id,
            "guardians_notified": notified,
            "message": f"Help request sent to {notified} guardian(s).",
        }

    # ── Legacy path (V2 flag off) ────────────────────────────────────
    g_result = await session.execute(
        select(Guardian).where(
            Guardian.user_id == user.id,
            Guardian.is_active.is_(True),
        )
    )
    guardian_contacts = g_result.scalars().all()
    notified = 0
    guardian_ids = []

    for gc in guardian_contacts:
        if gc.email:
            gu_result = await session.execute(select(User).where(User.email == gc.email))
            guardian_user = gu_result.scalar_one_or_none()
            if guardian_user:
                gid = str(guardian_user.id)
                guardian_ids.append(gid)
                await broadcaster.broadcast_to_user(gid, "safety_alert", safety_alert_data)
                notified += 1
                logger.info(f"[SSE_HELP_ALERT] guardian={gid} child={user_id}")

    await broadcaster.broadcast_to_operators("safety_alert", safety_alert_data)

    # Create GuardianAlert (session-less alerts are first-class —
    # see migration ae1a2b3c4dt01). The ACK engine MUST be armed
    # so escalation can fire even when the child has no active
    # journey session.
    try:
        active_ses_result = await session.execute(
            select(GuardianSession).where(
                GuardianSession.user_id == user.id,
                GuardianSession.status == "active",
            ).order_by(GuardianSession.started_at.desc()).limit(1)
        )
        active_ses = active_ses_result.scalar_one_or_none()
        alert = GuardianAlert(
            session_id=active_ses.id if active_ses else None,
            user_id=user.id,
            alert_type="help_requested",
            severity="critical",
            message=req.message or f"{child_name} pressed Need Help!",
            details=f"Manual help request. SafetyEvent: {event_id}",
            recommendation="Contact your child immediately.",
            location={"lat": req.lat, "lng": req.lng} if req.lat and req.lng else None,
        )
        session.add(alert)
        await session.flush()
        logger.info(
            f"[ALERT_CREATED] type=help_requested id={alert.id} "
            f"child={user_id} session={active_ses.id if active_ses else 'none'}"
        )
        # Wire ACK engine so escalation runs.
        try:
            from app.services.alert_ack_engine import (
                severity_requires_ack, mark_for_ack,
            )
            if severity_requires_ack(alert.severity):
                await mark_for_ack(session, alert)
        except Exception:
            logger.exception("[help_request] mark_for_ack wiring failed (non-fatal)")
    except Exception as e:
        logger.warning(f"[ALERT_CREATED] GuardianAlert failed: {e}", exc_info=True)

    # Push notification to guardians (HIGH priority — works when app is killed)
    try:
        from app.services.push_service import send_push_to_user
        for gid in guardian_ids:
            await send_push_to_user(
                session, uuid.UUID(gid),
                f"URGENT: {child_name} needs help!",
                req.message or f"{child_name} pressed Need Help!",
                data={
                    "type": "HELP_REQUEST",
                    "child_id": user_id,
                    "child_name": child_name,
                    "event_id": event_id,
                    "lat": str(req.lat),
                    "lng": str(req.lng),
                },
            )
    except Exception as e:
        logger.warning(f"[HELP_PUSH] Failed: {e}")

    await session.commit()

    logger.warning(
        f"[HELP_REQUEST_COMPLETE] child={user_id} event={event_id} "
        f"guardians_notified={notified} guardian_ids={guardian_ids}"
    )

    # Schedule auto-escalation (30s) — if child doesn't cancel, escalate to CRITICAL
    try:
        from app.services.auto_escalation_engine import schedule_escalation
        schedule_escalation(event_id, user_id, child_name, "help_request")
    except Exception as e:
        logger.error(f"Auto-escalation schedule failed: {e}")

    return {
        "status": "help_sent",
        "event_id": event_id,
        "guardians_notified": notified,
        "message": f"Help request sent to {notified} guardian(s).",
    }


@router.post("/generate-link-code")
async def generate_link_code(
    user: User = Depends(get_current_user),
):
    """Generate a 6-digit link code for a child to share with their guardian."""
    if user.role != "child":
        raise HTTPException(status_code=403, detail="Only child accounts can generate link codes")

    code = str(random.randint(100000, 999999))
    stored = redis_service.set_json("link_code", code, str(user.id), ttl=LINK_CODE_TTL)
    if not stored:
        raise HTTPException(status_code=503, detail="Code generation temporarily unavailable")

    logger.info(f"[LINK] Child {user.email} generated link code {code}")
    return {"code": code}
