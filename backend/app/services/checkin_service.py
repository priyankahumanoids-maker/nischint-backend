# Check-In Service — 2-way safety check between guardian and child
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checkin import CheckIn
from app.models.user import User
from app.models.guardian import Guardian

logger = logging.getLogger(__name__)

CHECKIN_EXPIRY_SECONDS = 60


# ── DLQ for check-in audit rows that failed to persist ─────────────
# Compensating action for the two safety-critical event-dispatch
# swallows below (help_requested GuardianAlert + SafetyEvent). The
# SSE + push broadcast has ALREADY fired by the time the INSERT is
# attempted; the only thing this DLQ recovers is the audit trail.
# Bounded to protect Redis memory during a sustained DB outage.
_CHECKIN_DLQ_NAMESPACE = "dlq"
_CHECKIN_DLQ_KEY = "checkin_audit"
_CHECKIN_DLQ_MAX = 500


def _push_checkin_audit_dlq(payload: dict) -> bool:
    """LPUSH the check-in audit payload to a bounded Redis list. The
    payload carries a `row_type` discriminator (`help_requested` or
    `safety_event`) so the reconciler can dispatch to the right
    replay function."""
    try:
        import json
        from app.services.redis_service import _get_client
        c = _get_client()
        if not c:
            return False
        full_key = f"{_CHECKIN_DLQ_NAMESPACE}:{_CHECKIN_DLQ_KEY}"
        c.lpush(full_key, json.dumps(payload, default=str))
        c.ltrim(full_key, 0, _CHECKIN_DLQ_MAX - 1)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort DLQ
        logger.debug("checkin DLQ push skipped: %r", e)
        return False


async def create_checkin(session: AsyncSession, guardian_id: str, child_id: str) -> dict:
    """Guardian initiates a safety check-in for a child."""
    logger.info(f"CHECKIN_CREATE guardian={guardian_id} child={child_id}")
    # Verify guardian is linked to this child
    guardian_uuid = uuid.UUID(guardian_id)
    child_uuid = uuid.UUID(child_id)

    # Get guardian's email to verify link
    guardian_user = await session.execute(select(User).where(User.id == guardian_uuid))
    guardian = guardian_user.scalar_one_or_none()
    if not guardian:
        return {"error": "Guardian not found"}

    # Use the same canonical family resolver as the Guardian dashboard.  The
    # older implementation checked only the legacy Guardian table and the
    # Relationship table, so valid direct User.guardian_id and co-guardian
    # links could be rejected with "not linked as a guardian".
    #
    # Do NOT use legacy CheckIn rows as authorization for a new action.
    from app.services.guardian_dashboard_engine import _get_linked_user_ids

    linked_user_ids = await _get_linked_user_ids(
        session,
        guardian.email or "",
        str(guardian_uuid),
        guardian.role,
        include_checkin_recovery=False,
    )
    if child_uuid not in set(linked_user_ids):
        logger.warning(
            "CHECKIN_LINK_REJECTED guardian=%s child=%s role=%s",
            guardian_id,
            child_id,
            guardian.role,
        )
        return {"error": "You are not linked as a guardian to this user"}

    # Cancel any existing pending check-ins from this guardian to this child
    await session.execute(
        update(CheckIn).where(
            CheckIn.guardian_id == guardian_uuid,
            CheckIn.child_id == child_uuid,
            CheckIn.status == "pending",
        ).values(status="expired", escalated_at=datetime.now(timezone.utc))
    )

    checkin = CheckIn(
        guardian_id=guardian_uuid,
        child_id=child_uuid,
        status="pending",
    )
    session.add(checkin)
    await session.flush()

    # Capture values before commit (avoids detached-instance errors in async SQLAlchemy)
    check_in_id = str(checkin.id)
    created_at = checkin.created_at.isoformat()

    # Get child info for response
    child_user = await session.execute(select(User).where(User.id == child_uuid))
    child = child_user.scalar_one_or_none()
    child_name = child.full_name if child else "Unknown"

    # Commit the real check-in before any external FCM call. A slow/unavailable
    # push provider must never leave the guardian button spinning or hide the
    # pending request from the protected member's authenticated polling path.
    await session.commit()

    # Send push notification to child. Bound delivery latency; the committed
    # row plus SSE/polling remain authoritative if FCM is temporarily slow.
    try:
        from app.services.push_service import send_push_to_user
        await asyncio.wait_for(
            send_push_to_user(
                session,
                child_uuid,
                "Safety Check",
                "Your guardian is checking on you. Are you safe?",
                data={
                    "type": "CHECKIN_REQUEST",
                    "eventType": "checkin_pending",
                    "event_type": "checkin_pending",
                    "check_in_id": check_in_id,
                    "child_id": child_id,
                    "child_name": child_name,
                    "guardian_id": guardian_id,
                    "guardian_name": guardian.full_name or "Your guardian",
                    "created_at": created_at,
                    "expires_in_seconds": CHECKIN_EXPIRY_SECONDS,
                    "screen": "home",
                },
                channel_id="safety-alerts",
            ),
            timeout=3.0,
        )
        logger.info(f"CHECKIN_PUSH_SENT child={child_id}")
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"CHECKIN_PUSH_FAILED {e}")
    logger.info(f"CHECKIN_CREATE_SUCCESS id={check_in_id} guardian={guardian_id} child={child_id}")

    # Broadcast checkin_pending to BOTH guardian AND child via SSE
    try:
        from app.services.event_broadcaster import broadcaster
        pending_payload = {
            "check_in_id": check_in_id,
            "child_id": child_id,
            "child_name": child_name,
            "guardian_id": guardian_id,
            "guardian_name": guardian.full_name or "Your parent",
            "status": "pending",
            "created_at": created_at,
            "expires_in_seconds": CHECKIN_EXPIRY_SECONDS,
        }
        await broadcaster.broadcast_to_user(guardian_id, "checkin_pending", pending_payload)
        logger.info(f"[SSE_CHECKIN_EMIT] type=checkin_pending user={guardian_id} checkin={check_in_id}")
        await broadcaster.broadcast_to_user(child_id, "checkin_pending", pending_payload)
        logger.info(f"[SSE_CHECKIN_EMIT] type=checkin_pending user={child_id} checkin={check_in_id}")
    except Exception as e:
        logger.warning(f"[SSE_CHECKIN_EMIT] checkin_pending broadcast failed: {e}")

    return {
        "check_in_id": check_in_id,
        "guardian_id": guardian_id,
        "child_id": child_id,
        "child_name": child_name,
        "status": "pending",
        "created_at": created_at,
    }


async def get_pending_checkins(session: AsyncSession, child_id: str) -> list[dict]:
    """Get all pending check-ins for a child."""
    child_uuid = uuid.UUID(child_id)
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(CheckIn).where(
            CheckIn.child_id == child_uuid,
            CheckIn.status == "pending",
        ).order_by(CheckIn.created_at.desc())
    )

    checkins = []
    for ci in result.scalars().all():
        # The guardian escalation check is deliberately short-lived. The
        # backend owns this deadline so it still applies when either app is
        # backgrounded or closed.
        age_seconds = (now - ci.created_at).total_seconds()
        if age_seconds > CHECKIN_EXPIRY_SECONDS:
            # Leave the row pending for the background escalator. Marking it
            # expired here would let a protected-device refresh consume the
            # row before guardians receive the mandatory high alert.
            continue

        # Get guardian name
        g_result = await session.execute(select(User).where(User.id == ci.guardian_id))
        guardian = g_result.scalar_one_or_none()

        checkins.append({
            "check_in_id": str(ci.id),
            "guardian_id": str(ci.guardian_id),
            "guardian_name": guardian.full_name if guardian else "Guardian",
            "status": ci.status,
            "created_at": ci.created_at.isoformat(),
            "expires_in_seconds": max(0, int(CHECKIN_EXPIRY_SECONDS - age_seconds)),
        })

    await session.commit()
    return checkins


async def report_safe_status(
    session: AsyncSession,
    child_id: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    message: str | None = None,
) -> dict:
    """Record a proactive all-clear and notify every linked guardian once."""
    child_uuid = uuid.UUID(child_id)
    child_result = await session.execute(select(User).where(User.id == child_uuid))
    child = child_result.scalar_one_or_none()
    if not child:
        return {"error": "Protected member account not found"}

    from app.services.alert_trigger import _resolve_guardian_ids
    guardian_ids, _ = await _resolve_guardian_ids(session, child_id)
    guardian_ids = list(dict.fromkeys(guardian_ids))
    if not guardian_ids:
        return {"error": "No linked guardian is available to receive your safe status"}

    now = datetime.now(timezone.utc)
    safe_message = message or f"{child.full_name or child.email} is safe — no need to worry."
    check_in_ids: list[str] = []

    for guardian_id in guardian_ids:
        guardian_uuid = uuid.UUID(guardian_id)
        pending_result = await session.execute(
            select(CheckIn)
            .where(
                CheckIn.guardian_id == guardian_uuid,
                CheckIn.child_id == child_uuid,
                CheckIn.status == "pending",
            )
            .order_by(CheckIn.created_at.desc())
            .limit(1)
        )
        checkin = pending_result.scalar_one_or_none()
        if checkin:
            checkin.status = "safe"
            checkin.responded_at = now
            checkin.response_note = safe_message
        else:
            checkin = CheckIn(
                guardian_id=guardian_uuid,
                child_id=child_uuid,
                status="safe",
                response_note=safe_message,
                created_at=now,
                responded_at=now,
            )
            session.add(checkin)
        await session.flush()
        check_in_ids.append(str(checkin.id))

    # An explicit all-clear returns non-emergency risk state to normal. It does
    # not cancel an active SOS/EmergencyEvent; that remains a separate action.
    try:
        from app.models.safety_event import SafetyEvent
        await session.execute(
            update(SafetyEvent)
            .where(SafetyEvent.user_id == child_uuid, SafetyEvent.status == "active")
            .values(status="resolved", resolved_at=now, updated_at=now)
        )
    except Exception as exc:
        logger.warning("SAFE_STATUS risk reset skipped child=%s: %s", child_id, exc)

    await session.commit()

    payload = {
        "type": "CHECKIN_SAFE",
        "eventType": "checkin_safe",
        "event_type": "checkin_safe",
        "child_id": child_id,
        "child_name": child.full_name or child.email,
        "message": safe_message,
        "lat": lat,
        "lng": lng,
        "check_in_ids": check_in_ids,
        "check_in_id": check_in_ids[0],
        "checkin_id": check_in_ids[0],
        "responded_at": now.isoformat(),
    }

    push_count = 0
    from app.services.push_service import send_push_to_user
    from app.services.event_broadcaster import broadcaster
    for guardian_id in guardian_ids:
        try:
            push_count += await send_push_to_user(
                session,
                uuid.UUID(guardian_id),
                f"{child.full_name or 'Protected member'} is safe",
                "They checked in to say they are safe. No need to worry.",
                data={**payload, "screen": "alerts"},
            )
        except Exception as exc:
            logger.warning("SAFE_STATUS push failed guardian=%s: %s", guardian_id, exc)
        try:
            await broadcaster.broadcast_to_user(guardian_id, "checkin_safe", payload)
        except Exception as exc:
            logger.warning("SAFE_STATUS realtime alert failed guardian=%s: %s", guardian_id, exc)

    try:
        await broadcaster.broadcast_to_user(child_id, "checkin_safe", payload)
    except Exception:
        pass

    return {
        "status": "safe",
        "message": "Your guardians have been notified that you are safe.",
        "guardian_count": len(guardian_ids),
        "push_count": push_count,
        "responded_at": now.isoformat(),
    }


async def respond_to_checkin(session: AsyncSession, check_in_id: str, child_id: str, response: str) -> dict:
    """Child responds to a check-in. response = 'safe' | 'help'."""
    logger.info(f"CHECKIN_RESPOND child={child_id} check_in={check_in_id} response={response}")

    ci_result = await session.execute(
        select(CheckIn).where(
            CheckIn.id == uuid.UUID(check_in_id),
            CheckIn.child_id == uuid.UUID(child_id),
        )
    )
    ci = ci_result.scalar_one_or_none()
    if not ci:
        logger.warning(f"CHECKIN_RESPOND check-in {check_in_id} not found for child {child_id}")
        return {"error": "Check-in not found"}

    if ci.status != "pending":
        logger.warning(f"CHECKIN_RESPOND check-in {check_in_id} already {ci.status}")
        return {"error": f"Check-in already {ci.status}"}

    now = datetime.now(timezone.utc)
    ci.status = response  # "safe" or "help"
    ci.responded_at = now
    await session.flush()
    logger.info(f"CHECKIN_RESPOND DB updated: check_in={check_in_id} status={response}")

    # Get names for notification
    guardian_result = await session.execute(select(User).where(User.id == ci.guardian_id))
    guardian = guardian_result.scalar_one_or_none()
    child_result = await session.execute(select(User).where(User.id == ci.child_id))
    child = child_result.scalar_one_or_none()
    child_name = child.full_name if child else "Your child"
    guardian_id_str = str(ci.guardian_id)
    from app.services.alert_trigger import _resolve_guardian_ids
    linked_guardian_ids, _ = await _resolve_guardian_ids(session, child_id)
    guardian_recipient_ids = list(dict.fromkeys([
        guardian_id_str,
        *linked_guardian_ids,
    ]))

    # A SAFE response is an explicit all-clear from this authenticated
    # protected member. If they currently have an active SOS, close that
    # same member's emergency through the canonical emergency engine.
    #
    # A normal safety check with no active SOS is unchanged.
    # HELP never enters this branch and can never resolve an SOS.
    resolved_emergency_id = None
    if response == "safe":
        from app.models.emergency import EmergencyEvent

        emergency_result = await session.execute(
            select(EmergencyEvent).where(
                EmergencyEvent.user_id == uuid.UUID(child_id),
                EmergencyEvent.status == "active",
            ).order_by(EmergencyEvent.created_at.desc()).limit(1)
        )
        active_emergency = emergency_result.scalar_one_or_none()

        if active_emergency:
            from app.services.emergency_engine import resolve_emergency

            resolution = await resolve_emergency(
                session=session,
                event_id=str(active_emergency.id),
                # respond_to_checkin already sends the Guardian's All Clear
                # push below. Avoid a second push for the same user action.
                notify_guardians=False,
            )
            if "error" in resolution:
                raise RuntimeError(
                    f"Active SOS could not be resolved: {resolution['error']}"
                )

            resolved_emergency_id = str(active_emergency.id)
            logger.info(
                f"CHECKIN_SAFE resolved active SOS "
                f"child={child_id} event={resolved_emergency_id}"
            )

    # ── Step A: Push notification ──
    push_count = 0
    if response == "safe":
        from app.services.push_service import send_push_to_user
        for recipient_id in guardian_recipient_ids:
            try:
                push_count += await send_push_to_user(
                    session, uuid.UUID(recipient_id),
                    "All Clear",
                    f"{child_name} confirmed they are safe.",
                    data={
                        "type": "CHECKIN_SAFE",
                        "eventType": "checkin_safe",
                        "event_type": "checkin_safe",
                        "child_id": str(ci.child_id),
                        "child_name": child_name,
                        "check_in_id": str(ci.id),
                        "checkin_id": str(ci.id),
                        "screen": "alerts",
                    },
                )
            except Exception as e:
                logger.warning(
                    f"CHECKIN_RESPOND safe push failed guardian={recipient_id}: {e}"
                )

    elif response == "help":
        from app.services.push_service import send_push_to_user
        for recipient_id in guardian_recipient_ids:
            try:
                push_count += await send_push_to_user(
                    session, uuid.UUID(recipient_id),
                    f"URGENT: {child_name} needs help!",
                    f"{child_name} responded to your safety check requesting help!",
                    data={
                        "type": "CHECKIN_HELP",
                        "eventType": "checkin_help",
                        "event_type": "checkin_help",
                        "child_id": str(ci.child_id),
                        "child_name": child_name,
                        "check_in_id": str(ci.id),
                        "checkin_id": str(ci.id),
                        "screen": "alerts",
                    },
                    channel_id="critical_safety",
                    louder=True,
                )
            except Exception as e:
                logger.warning(
                    f"CHECKIN_RESPOND help push failed guardian={recipient_id}: {e}"
                )

    # ── Step B: Broadcast real-time SSE event to guardian + child + operators ──
    response_payload = {
        "check_in_id": check_in_id,
        "child_id": child_id,
        "child_name": child_name,
        "guardian_id": guardian_id_str,
        "response": response,
        "responded_at": now.isoformat(),
    }
    try:
        from app.services.event_broadcaster import broadcaster
        event_type = "checkin_help" if response == "help" else "checkin_safe"
        for recipient_id in guardian_recipient_ids:
            await broadcaster.broadcast_to_user(
                recipient_id,
                event_type,
                response_payload,
            )
            logger.info(
                f"[SSE_CHECKIN_EMIT] type={event_type} "
                f"user={recipient_id} checkin={check_in_id}"
            )
        await broadcaster.broadcast_to_user(child_id, event_type, response_payload)
        logger.info(f"[SSE_CHECKIN_EMIT] type={event_type} user={child_id} checkin={check_in_id}")
        await broadcaster.broadcast_to_operators(event_type, response_payload)
    except Exception as e:
        logger.error(f"[SSE_CHECKIN_EMIT] {event_type} broadcast failed: {e}")

    # ── Step C: Create a GuardianAlert record (so it appears in the Alerts tab) ──
    if response == "help":
        try:
            from app.models.guardian import GuardianAlert, GuardianSession
            sess_result = await session.execute(
                select(GuardianSession).where(
                    GuardianSession.user_id == uuid.UUID(child_id),
                    GuardianSession.status == "active",
                ).order_by(GuardianSession.started_at.desc()).limit(1)
            )
            active_session = sess_result.scalar_one_or_none()

            # Session-less alerts are now first-class. The DB row
            # MUST be created even when no active journey exists,
            # otherwise the ACK engine is blind and the audit trail
            # has a hole at the exact moment it matters most.
            alert = GuardianAlert(
                session_id=active_session.id if active_session else None,
                user_id=uuid.UUID(child_id),
                alert_type="help_requested",
                severity="critical",
                message=f"{child_name} needs help! Responded to safety check requesting assistance.",
                details=f"Check-in ID: {check_in_id}. Child explicitly requested help.",
                recommendation="Contact the child immediately. Call or send help.",
                location=active_session.current_location if active_session else None,
            )
            session.add(alert)
            await session.flush()
            logger.info(
                f"[ALERT_CREATED] type=help_requested id={alert.id} "
                f"child={child_id} guardian={guardian_id_str} "
                f"session={active_session.id if active_session else 'none'}"
            )

            # Wire into the ACK engine so escalation runs even on
            # session-less alerts (critical severity demands it).
            try:
                from app.services.alert_ack_engine import (
                    severity_requires_ack, mark_for_ack,
                )
                if severity_requires_ack(alert.severity):
                    await mark_for_ack(session, alert)
            except Exception:
                logger.exception("[alert_ack] mark_for_ack wiring failed (non-fatal)")
        except SQLAlchemyError as e:
            # Compensating action for safety-critical event dispatch:
            # SSE + push has already fired upstream; the help_requested
            # alert row is the only persistent record. Push the planned
            # payload to a bounded Redis DLQ for out-of-band replay.
            _push_checkin_audit_dlq({
                "row_type":     "help_requested",
                "check_in_id":  check_in_id,
                "child_id":     child_id,
                "child_name":   child_name,
                "guardian_id":  guardian_id_str,
                "failed_at":    datetime.now(timezone.utc).isoformat(),
                "error_type":   type(e).__name__,
                "error":        str(e)[:200],
            })
            logger.critical(
                "checkin_help_audit_row_dlq",
                extra={
                    "event":       "checkin_help_audit_row_dlq",
                    "check_in_id": check_in_id,
                    "child_id":    child_id,
                    "error_type":  type(e).__name__,
                },
                exc_info=True,
            )

        # ── Step D: Create SafetyEvent + broadcast safety_alert ──
        try:
            from app.models.safety_event import SafetyEvent
            safety_event = SafetyEvent(
                user_id=uuid.UUID(child_id),
                risk_score=0.9,
                risk_level="critical",
                signals={"help_request": 1.0, "check_in_id": check_in_id},
                primary_event="help_request",
                location_lat=0.0,
                location_lng=0.0,
                status="active",
            )
            session.add(safety_event)
            await session.flush()
            logger.info(f"[HELP_EVENT_CREATED] SafetyEvent id={safety_event.id} child={child_id}")

            # Broadcast safety_alert to guardian
            safety_alert_data = {
                "type": "HELP_REQUEST",
                "severity": "HIGH",
                "child_id": child_id,
                "child_name": child_name,
                "check_in_id": check_in_id,
                "safety_event_id": str(safety_event.id),
                "timestamp": now.isoformat(),
            }
            logger.info(f"[ALERT_GUARDIAN_IDS] guardian={guardian_id_str} for help_requested child={child_id}")
            await broadcaster.broadcast_to_user(guardian_id_str, "safety_alert", safety_alert_data)
            logger.info(f"[ALERT_BROADCAST] type=safety_alert/HELP_REQUEST guardian={guardian_id_str} child={child_id}")
            await broadcaster.broadcast_to_operators("safety_alert", safety_alert_data)
            logger.info(f"[SSE_EVENT_SENT] safety_alert/HELP_REQUEST to guardian={guardian_id_str}")
        except SQLAlchemyError as e:
            # SSE has already fanned out to guardian + operators.
            # SafetyEvent row is the persistent record — DLQ replay.
            _push_checkin_audit_dlq({
                "row_type":     "safety_event",
                "check_in_id":  check_in_id,
                "child_id":     child_id,
                "child_name":   child_name,
                "guardian_id":  guardian_id_str,
                "now_iso":      now.isoformat(),
                "failed_at":    datetime.now(timezone.utc).isoformat(),
                "error_type":   type(e).__name__,
                "error":        str(e)[:200],
            })
            logger.critical(
                "checkin_safety_event_audit_row_dlq",
                extra={
                    "event":       "checkin_safety_event_audit_row_dlq",
                    "check_in_id": check_in_id,
                    "child_id":    child_id,
                    "error_type":  type(e).__name__,
                },
            )

    await session.commit()
    logger.info(f"CHECKIN_RESPOND Pipeline complete: check_in={check_in_id} response={response} push={push_count} sse=sent")

    return {
        "check_in_id": check_in_id,
        "status": response,
        "responded_at": now.isoformat(),
        "resolved_emergency_id": resolved_emergency_id,
    }


async def get_checkin_status(session: AsyncSession, check_in_id: str) -> dict | None:
    """Get status of a check-in (for guardian polling)."""
    ci_result = await session.execute(
        select(CheckIn).where(CheckIn.id == uuid.UUID(check_in_id))
    )
    ci = ci_result.scalar_one_or_none()
    if not ci:
        return None

    child_result = await session.execute(select(User).where(User.id == ci.child_id))
    child = child_result.scalar_one_or_none()

    return {
        "check_in_id": str(ci.id),
        "child_id": str(ci.child_id),
        "child_name": child.full_name if child else "Unknown",
        "status": ci.status,
        "created_at": ci.created_at.isoformat(),
        "responded_at": ci.responded_at.isoformat() if ci.responded_at else None,
        "escalated_at": ci.escalated_at.isoformat() if ci.escalated_at else None,
    }


async def get_latest_checkin_for_child(session: AsyncSession, guardian_id: str, child_id: str) -> dict | None:
    """Get the most recent check-in between a guardian and child."""
    result = await session.execute(
        select(CheckIn).where(
            CheckIn.guardian_id == uuid.UUID(guardian_id),
            CheckIn.child_id == uuid.UUID(child_id),
        ).order_by(CheckIn.created_at.desc()).limit(1)
    )
    ci = result.scalar_one_or_none()
    if not ci:
        logger.info(f"[CHECKIN-LATEST] No check-ins found for guardian={guardian_id} child={child_id}")
        return None

    logger.info(f"[CHECKIN-LATEST] guardian={guardian_id} child={child_id} → status={ci.status} id={ci.id}")
    return {
        "check_in_id": str(ci.id),
        "status": ci.status,
        "created_at": ci.created_at.isoformat(),
        "responded_at": ci.responded_at.isoformat() if ci.responded_at else None,
    }


async def expire_stale_checkins(session: AsyncSession) -> int:
    """Escalate unanswered guardian safety checks after one minute."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CHECKIN_EXPIRY_SECONDS)
    result = await session.execute(
        select(CheckIn).where(
            CheckIn.status == "pending",
            CheckIn.created_at < cutoff,
        )
    )

    expired_count = 0
    now = datetime.now(timezone.utc)
    for ci in result.scalars().all():
        ci.status = "expired"
        ci.escalated_at = now
        expired_count += 1

        # Get child name
        child_result = await session.execute(select(User).where(User.id == ci.child_id))
        child = child_result.scalar_one_or_none()
        child_name = child.full_name if child else "Your child"

        from app.services.alert_trigger import _resolve_guardian_ids
        linked_guardian_ids, _ = await _resolve_guardian_ids(
            session,
            str(ci.child_id),
        )
        guardian_recipient_ids = list(dict.fromkeys([
            str(ci.guardian_id),
            *linked_guardian_ids,
        ]))

        # Persist one critical alert against the protected member. Guardian
        # alert queries resolve it through the family relationship, so every
        # linked guardian sees the same real high-priority event.
        try:
            from app.models.guardian import GuardianAlert, GuardianSession
            session_result = await session.execute(
                select(GuardianSession).where(
                    GuardianSession.user_id == ci.child_id,
                    GuardianSession.status == "active",
                ).order_by(GuardianSession.started_at.desc()).limit(1)
            )
            active_session = session_result.scalar_one_or_none()
            alert = GuardianAlert(
                session_id=active_session.id if active_session else None,
                user_id=ci.child_id,
                alert_type="checkin_no_response",
                severity="critical",
                message=f"{child_name} did not respond to the safety check within 1 minute.",
                details=f"Check-in ID: {ci.id}. No protected-member response was received.",
                recommendation="Call the protected member and check their live location immediately.",
                location=active_session.current_location if active_session else None,
            )
            session.add(alert)
            await session.flush()
            try:
                from app.services.alert_ack_engine import mark_for_ack
                await mark_for_ack(session, alert)
            except Exception:
                logger.exception("[checkin_expiry] alert acknowledgement wiring failed")
        except SQLAlchemyError:
            logger.exception("[checkin_expiry] critical guardian alert persistence failed")

        from app.services.push_service import send_push_to_user
        for recipient_id in guardian_recipient_ids:
            try:
                await send_push_to_user(
                    session,
                    uuid.UUID(recipient_id),
                    f"HIGH ALERT: {child_name} did not respond",
                    f"{child_name} did not respond to the safety check within 1 minute. Check their live location now.",
                    data={
                        "type": "CHECKIN_EXPIRED",
                        "eventType": "checkin_expired",
                        "event_type": "checkin_expired",
                        "check_in_id": str(ci.id),
                        "child_id": str(ci.child_id),
                        "child_name": child_name,
                        "severity": "critical",
                        "screen": "alerts",
                    },
                    channel_id="critical_safety",
                    louder=True,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send expiry push guardian={recipient_id}: {e}"
                )

        # Broadcast checkin_expired to both guardian and child via SSE
        try:
            from app.services.event_broadcaster import broadcaster
            expired_payload = {
                "check_in_id": str(ci.id),
                "child_id": str(ci.child_id),
                "child_name": child_name,
                "guardian_id": str(ci.guardian_id),
                "status": "expired",
                "severity": "critical",
                "message": f"{child_name} did not respond within 1 minute. Treat this as a high-priority safety alert.",
                "expired_at": now.isoformat(),
            }
            for recipient_id in guardian_recipient_ids:
                await broadcaster.broadcast_to_user(
                    recipient_id,
                    "checkin_expired",
                    expired_payload,
                )
                logger.info(
                    f"[SSE_CHECKIN_EMIT] type=checkin_expired "
                    f"user={recipient_id} checkin={ci.id}"
                )
            await broadcaster.broadcast_to_user(str(ci.child_id), "checkin_expired", expired_payload)
            logger.info(f"[SSE_CHECKIN_EMIT] type=checkin_expired user={ci.child_id} checkin={ci.id}")
        except Exception as e:
            logger.warning(f"[SSE_CHECKIN_EMIT] checkin_expired broadcast failed: {e}")

    if expired_count > 0:
        await session.commit()
        logger.info(f"Expired {expired_count} stale check-ins and sent escalation alerts")

    return expired_count
