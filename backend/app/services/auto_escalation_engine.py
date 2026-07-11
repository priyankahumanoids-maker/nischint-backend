# Auto Escalation Engine
# Tier 1: Child no-response (30s) → escalate to all guardians
# Tier 2: Guardian no-acknowledge (60s) → escalate to secondary guardians + emergency contacts + SMS
import asyncio
import logging
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

ESCALATION_DELAY_S = 30  # seconds before child no-response escalation
GUARDIAN_FAILSAFE_DELAY_S = 60  # seconds before guardian no-ack escalation
SMS_RATE_LIMIT_PER_HOUR = 5  # max SMS per phone per hour

# In-memory tracker of pending escalation timers
_pending: dict[str, asyncio.Task] = {}
# In-memory tracker of guardian failsafe timers
_guardian_failsafe: dict[str, asyncio.Task] = {}
# SMS dedup + delivery tracking: {event_id: [{phone, contact_name, status, sent_at}]}
_sms_log: dict[str, list[dict]] = {}
# Rate limiting: {phone: [sent_at_timestamps]}
_sms_rate: dict[str, list[datetime]] = defaultdict(list)


# ── DLQ for failsafe-audit rows that failed to persist ─────────────
# Compensating action for `_trigger_guardian_failsafe`'s inner
# GuardianAlert insert. The SSE / push / SMS escalation has ALREADY
# fired by the time we reach this; the only thing this DLQ recovers
# is the *audit trail* of how it unfolded. Bounded to protect Redis
# memory during a sustained DB outage.
_FAILSAFE_DLQ_NAMESPACE = "dlq"
_FAILSAFE_DLQ_KEY = "failsafe_audit"
_FAILSAFE_DLQ_MAX = 500


def _push_failsafe_audit_dlq(payload: dict) -> bool:
    """LPUSH the failsafe-audit payload to a bounded Redis list so
    an out-of-band reconciler can replay it once the DB is healthy.
    Returns True on enqueue, False on Redis-unavailable (caller has
    already emitted a CRITICAL structured log)."""
    try:
        import json
        from app.services.redis_service import _get_client
        c = _get_client()
        if not c:
            return False
        full_key = f"{_FAILSAFE_DLQ_NAMESPACE}:{_FAILSAFE_DLQ_KEY}"
        c.lpush(full_key, json.dumps(payload, default=str))
        c.ltrim(full_key, 0, _FAILSAFE_DLQ_MAX - 1)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort DLQ
        logger.debug("failsafe DLQ push skipped: %r", e)
        return False


def schedule_escalation(event_id: str, user_id: str, child_name: str, alert_type: str, delay: int = ESCALATION_DELAY_S):
    """Start a 30s timer. If not cancelled, trigger_escalation fires."""
    if event_id in _pending:
        logger.info(f"[ESCALATION] Timer already exists for event={event_id}")
        return

    task = asyncio.create_task(_escalation_timer(event_id, user_id, child_name, alert_type, delay))
    _pending[event_id] = task
    logger.warning(f"[ESCALATION_SCHEDULED] event={event_id} child={user_id} type={alert_type} delay={delay}s")


def cancel_escalation(event_id: str):
    """Child responded — cancel the escalation timer."""
    task = _pending.pop(event_id, None)
    if task and not task.done():
        task.cancel()
        logger.info(f"[ESCALATION_CANCELLED] event={event_id} (child responded)")
    else:
        logger.debug(f"[ESCALATION_CANCEL] No pending timer for event={event_id}")


# ── TIER 2: GUARDIAN FAILSAFE ──
# If NO guardian acknowledges within 60s, escalate to secondary guardians + emergency contacts

def schedule_guardian_failsafe(event_id: str, child_user_id: str, child_name: str, alert_type: str, delay: int = GUARDIAN_FAILSAFE_DELAY_S):
    """Start a 60s failsafe timer. If no guardian ACKs, escalate to secondary contacts."""
    key = f"gf-{event_id}"
    if key in _guardian_failsafe:
        logger.info(f"[GUARDIAN_FAILSAFE] Timer already exists for event={event_id}")
        return
    task = asyncio.create_task(_guardian_failsafe_timer(event_id, child_user_id, child_name, alert_type, delay))
    _guardian_failsafe[key] = task
    logger.warning(f"[GUARDIAN_FAILSAFE_SCHEDULED] event={event_id} child={child_name} delay={delay}s")


def cancel_guardian_failsafe(event_id: str):
    """Guardian acknowledged — cancel the failsafe timer."""
    key = f"gf-{event_id}"
    task = _guardian_failsafe.pop(key, None)
    if task and not task.done():
        task.cancel()
        logger.info(f"[GUARDIAN_FAILSAFE_CANCELLED] event={event_id} (guardian acknowledged)")
        return True
    logger.debug(f"[GUARDIAN_FAILSAFE_CANCEL] No pending failsafe for event={event_id}")
    return False


async def _guardian_failsafe_timer(event_id: str, child_user_id: str, child_name: str, alert_type: str, delay: int):
    """Wait {delay}s, then trigger secondary escalation if no guardian ACK."""
    key = f"gf-{event_id}"
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    finally:
        _guardian_failsafe.pop(key, None)

    await _trigger_guardian_failsafe(event_id, child_user_id, child_name, alert_type)


async def _trigger_guardian_failsafe(event_id: str, child_user_id: str, child_name: str, alert_type: str):
    """No guardian ACK in 60s — escalate to secondary guardians + emergency contacts."""
    from app.db.session import async_session
    from app.models.guardian_network import GuardianRelationship, EmergencyContact
    from app.models.guardian import Guardian, GuardianAlert, GuardianSession
    from app.models.user import User
    from app.services.event_broadcaster import broadcaster
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    import uuid

    logger.warning(
        f"[GUARDIAN_FAILSAFE_TRIGGERED] event={event_id} child={child_name} type={alert_type} "
        f"— NO GUARDIAN ACK IN {GUARDIAN_FAILSAFE_DELAY_S}s"
    )

    now = datetime.now(timezone.utc)

    async with async_session() as session:
        try:
            escalation_payload = {
                "type": "ESCALATION",
                "severity": "CRITICAL",
                "child_id": child_user_id,
                "child_name": child_name,
                "safety_event_id": event_id,
                "alert_type": f"guardian_failsafe_{alert_type}",
                "message": f"FAILSAFE: No guardian responded for {child_name} in {GUARDIAN_FAILSAFE_DELAY_S}s. Escalating to secondary contacts.",
                "timestamp": now.isoformat(),
                "escalation_tier": "secondary",
            }

            notified_count = 0
            notified_guardian_ids: list[str] = []  # Collect for SSE escalation events

            # 1. Notify secondary/non-primary guardians from GuardianRelationship
            try:
                gr_result = await session.execute(
                    select(GuardianRelationship).where(
                        GuardianRelationship.user_id == uuid.UUID(child_user_id),
                        GuardianRelationship.is_active.is_(True),
                    ).order_by(GuardianRelationship.priority)
                )
                relationships = gr_result.scalars().all()

                for rel in relationships:
                    # Notify ALL guardians in the network (primary already notified, but re-ping)
                    if rel.guardian_user_id:
                        gid = str(rel.guardian_user_id)
                        await broadcaster.broadcast_to_user(gid, "safety_alert", escalation_payload)
                        notified_count += 1
                        if gid not in notified_guardian_ids:
                            notified_guardian_ids.append(gid)
                        logger.warning(f"[FAILSAFE_NOTIFY] guardian={rel.guardian_name} ({gid}) type={rel.relationship_type}")

                        # Push notification
                        try:
                            from app.services.push_service import send_push_to_user
                            await send_push_to_user(
                                session, uuid.UUID(gid),
                                f"URGENT: {child_name} — no guardian response!",
                                f"No one has responded for {GUARDIAN_FAILSAFE_DELAY_S}s. Please act immediately!",
                                data={"type": "GUARDIAN_FAILSAFE", "child_id": child_user_id, "event_id": event_id},
                            )
                        except Exception as e:
                            logger.warning(f"[FAILSAFE_PUSH] Failed for {gid}: {e}")
            except Exception as e:
                logger.warning(f"[FAILSAFE] GuardianRelationship query failed: {e}")

            # 2. Also notify via original Guardian model (legacy contacts)
            try:
                g_result = await session.execute(
                    select(Guardian).where(
                        Guardian.user_id == uuid.UUID(child_user_id),
                        Guardian.is_active.is_(True),
                    )
                )
                for gc in g_result.scalars().all():
                    if gc.email:
                        gu_result = await session.execute(select(User).where(User.email == gc.email))
                        guardian_user = gu_result.scalar_one_or_none()
                        if guardian_user:
                            gid = str(guardian_user.id)
                            await broadcaster.broadcast_to_user(gid, "safety_alert", escalation_payload)
                            notified_count += 1
                            if gid not in notified_guardian_ids:
                                notified_guardian_ids.append(gid)

                            try:
                                from app.services.push_service import send_push_to_user
                                await send_push_to_user(
                                    session, uuid.UUID(gid),
                                    f"URGENT: {child_name} — no guardian response!",
                                    f"No one responded for {GUARDIAN_FAILSAFE_DELAY_S}s. Act immediately!",
                                    data={"type": "GUARDIAN_FAILSAFE", "child_id": child_user_id, "event_id": event_id},
                                )
                            except Exception as e:
                                logger.warning(f"[FAILSAFE_PUSH_LEGACY] Failed: {e}")
            except Exception as e:
                logger.warning(f"[FAILSAFE] Legacy Guardian query failed: {e}")

            # 3. Get last seen time (shared by SMS + Voice flows)
            last_seen_str = "unknown"
            try:
                ses_result = await session.execute(
                    select(GuardianSession).where(
                        GuardianSession.user_id == uuid.UUID(child_user_id),
                        GuardianSession.status == "active",
                    ).order_by(GuardianSession.started_at.desc()).limit(1)
                )
                active_ses_for_loc = ses_result.scalar_one_or_none()
                if active_ses_for_loc and active_ses_for_loc.previous_update_at:
                    delta = (now - active_ses_for_loc.previous_update_at).total_seconds()
                    if delta < 60:
                        last_seen_str = f"{int(delta)}s ago"
                    else:
                        last_seen_str = f"{int(delta // 60)}m ago"
            except Exception as e:
                logger.debug(f"[FAILSAFE] Last seen lookup failed: {e}")

            # 4. INTELLIGENT SEQUENTIAL ESCALATION
            # Collect ALL contacts → sort by priority → call one by one → stop when answered
            from app.services.sequential_escalation import (
                intelligent_escalation,
                EscalationContact,
            )
            from app.models.relationship import Relationship

            all_contacts: list[EscalationContact] = []
            seen_phones: set[str] = set()

            # 4a. Guardians from GuardianRelationship
            try:
                for rel in relationships:
                    phone = rel.guardian_phone
                    if not phone and rel.guardian_user_id:
                        gu = await session.execute(
                            select(User).where(User.id == rel.guardian_user_id)
                        )
                        guardian_user = gu.scalar_one_or_none()
                        if guardian_user:
                            phone = guardian_user.phone
                    if phone and phone not in seen_phones:
                        seen_phones.add(phone)
                        all_contacts.append(EscalationContact(
                            phone=phone,
                            name=rel.guardian_name or "",
                            source="guardian_relationship",
                            is_primary=rel.is_primary,
                            priority=rel.priority,
                            guardian_user_id=str(rel.guardian_user_id) if rel.guardian_user_id else None,
                        ))
            except Exception as e:
                logger.warning(f"[SEQ_COLLECT] GuardianRelationship failed: {e}")

            # 4b. Guardians from Relationship table (primary link)
            try:
                rel_result = await session.execute(
                    select(Relationship).where(
                        Relationship.child_id == uuid.UUID(child_user_id),
                        Relationship.status == "accepted",
                    )
                )
                for rel in rel_result.scalars().all():
                    gu = await session.execute(
                        select(User).where(User.id == rel.guardian_id)
                    )
                    guardian_user = gu.scalar_one_or_none()
                    if guardian_user and guardian_user.phone and guardian_user.phone not in seen_phones:
                        seen_phones.add(guardian_user.phone)
                        all_contacts.append(EscalationContact(
                            phone=guardian_user.phone,
                            name=guardian_user.name or "",
                            source="relationship",
                            is_primary=True,  # Relationship table = primary link
                            priority=1,
                            guardian_user_id=str(guardian_user.id),
                        ))
            except Exception as e:
                logger.warning(f"[SEQ_COLLECT] Relationship failed: {e}")

            # 4c. Legacy Guardian model contacts
            try:
                g_result2 = await session.execute(
                    select(Guardian).where(
                        Guardian.user_id == uuid.UUID(child_user_id),
                        Guardian.is_active.is_(True),
                    )
                )
                for gc in g_result2.scalars().all():
                    phone = gc.phone
                    if not phone and gc.email:
                        gu = await session.execute(select(User).where(User.email == gc.email))
                        gu_user = gu.scalar_one_or_none()
                        if gu_user:
                            phone = gu_user.phone
                    if phone and phone not in seen_phones:
                        seen_phones.add(phone)
                        all_contacts.append(EscalationContact(
                            phone=phone,
                            name=gc.name or "",
                            source="guardian",
                            is_primary=False,
                            priority=5,
                        ))
            except Exception as e:
                logger.warning(f"[SEQ_COLLECT] Legacy Guardian failed: {e}")

            # 4d. Emergency contacts
            try:
                ec_result = await session.execute(
                    select(EmergencyContact).where(
                        EmergencyContact.user_id == uuid.UUID(child_user_id),
                        EmergencyContact.is_active.is_(True),
                    ).order_by(EmergencyContact.priority)
                )
                for ec in ec_result.scalars().all():
                    if ec.phone and ec.phone not in seen_phones:
                        seen_phones.add(ec.phone)
                        all_contacts.append(EscalationContact(
                            phone=ec.phone,
                            name=ec.name or "",
                            source="emergency_contact",
                            is_primary=False,
                            priority=ec.priority,
                        ))
            except Exception as e:
                logger.warning(f"[SEQ_COLLECT] EmergencyContact failed: {e}")

            # Determine callback URL for Twilio webhooks
            import os
            callback_base_url = os.environ.get("APP_BASE_URL", "https://nischint.care")

            logger.warning(
                f"[SEQ_ESCALATION_CONTACTS] event={event_id} collected={len(all_contacts)} "
                f"sources=GR+Rel+Guardian+EC callback={callback_base_url}"
            )

            # Run sequential escalation: call 1 → wait → no answer → call 2 → ... → SMS blast
            seq_summary = await intelligent_escalation(
                event_id=event_id,
                contacts=all_contacts,
                child_name=child_name,
                alert_type=alert_type,
                last_seen=last_seen_str,
                callback_base_url=callback_base_url,
                guardian_ids=notified_guardian_ids,
            )

            # 5. Broadcast to operators / command center
            await broadcaster.broadcast_to_operators("safety_alert", escalation_payload)

            # 6. Create GuardianAlert record with sequential escalation audit
            try:
                active_ses_result = await session.execute(
                    select(GuardianSession).where(
                        GuardianSession.user_id == uuid.UUID(child_user_id),
                        GuardianSession.status == "active",
                    ).order_by(GuardianSession.started_at.desc()).limit(1)
                )
                active_ses = active_ses_result.scalar_one_or_none()
                if active_ses:
                    alert = GuardianAlert(
                        session_id=active_ses.id,
                        user_id=uuid.UUID(child_user_id),
                        alert_type="guardian_failsafe",
                        severity="critical",
                        message=f"FAILSAFE: No guardian responded for {child_name} in {GUARDIAN_FAILSAFE_DELAY_S}s",
                        details=(
                            f"Original: {alert_type}. Event: {event_id}. "
                            f"Guardians SSE-pinged: {notified_count}. "
                            f"Sequential escalation: {len(all_contacts)} contacts, "
                            f"calls={seq_summary.total_calls}, sms={seq_summary.total_sms}, "
                            f"resolved_by={seq_summary.resolved_by or 'NONE'}, "
                            f"sms_blast={seq_summary.sms_blast_sent}."
                        ),
                        recommendation="Call child immediately. If unreachable, contact emergency services.",
                    )
                    session.add(alert)
            except SQLAlchemyError as e:
                # Compensating action for safety-critical event
                # dispatch: SSE + push + SMS already fired upstream
                # (the escalation IS in motion). The failsafe audit
                # row is the only persistent record of HOW the
                # sequential escalation unfolded — push the planned
                # payload to a bounded Redis DLQ so an operator
                # reconciler can replay it, AND emit a CRITICAL
                # structured log so the on-call sees the gap
                # immediately. Narrow `SQLAlchemyError` lets unknown
                # exceptions surface to the outer safety net at the
                # bottom of this function (line ~374, already
                # compensated by `event_broadcaster`).
                _push_failsafe_audit_dlq({
                    "event_id":      event_id,
                    "child_user_id": child_user_id,
                    "child_name":    child_name,
                    "alert_type":    alert_type,
                    "notified_count": notified_count,
                    "seq_contacts":  len(all_contacts),
                    "seq_summary":   {
                        "total_calls": seq_summary.total_calls,
                        "total_sms":   seq_summary.total_sms,
                        "resolved_by": seq_summary.resolved_by,
                        "sms_blast_sent": seq_summary.sms_blast_sent,
                    },
                    "failed_at":     datetime.now(timezone.utc).isoformat(),
                    "error_type":    type(e).__name__,
                    "error":         str(e)[:200],
                })
                logger.critical(
                    "failsafe_audit_row_dlq",
                    extra={
                        "event":      "failsafe_audit_row_dlq",
                        "event_id":   event_id,
                        "child_user_id": child_user_id,
                        "error_type": type(e).__name__,
                    },
                )

            await session.commit()
            logger.warning(
                f"[GUARDIAN_FAILSAFE_COMPLETE] event={event_id} guardians_sse={notified_count} "
                f"seq_contacts={len(all_contacts)} calls={seq_summary.total_calls} "
                f"sms={seq_summary.total_sms} resolved_by={seq_summary.resolved_by or 'NONE'} "
                f"sms_blast={seq_summary.sms_blast_sent} operators=all"
            )

        except Exception as e:
            logger.error(f"[GUARDIAN_FAILSAFE_ERROR] event={event_id}: {e}")
            await session.rollback()


async def _escalation_timer(event_id: str, user_id: str, child_name: str, alert_type: str, delay: int):
    """Wait {delay}s, then check if event is still active. If so, escalate."""
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    finally:
        _pending.pop(event_id, None)

    # Timer fired — check if event is still unresolved
    await _trigger_escalation(event_id, user_id, child_name, alert_type)


async def _trigger_escalation(event_id: str, user_id: str, child_name: str, alert_type: str):
    """No response in 30s — escalate priority, notify operator, broadcast SSE."""
    from app.db.session import async_session
    from app.models.safety_event import SafetyEvent
    from app.models.guardian import Guardian, GuardianAlert, GuardianSession
    from app.models.user import User
    from app.services.event_broadcaster import broadcaster
    from sqlalchemy import select
    import uuid

    logger.warning(f"[ESCALATION_TRIGGERED] event={event_id} child={user_id} type={alert_type} — NO RESPONSE IN {ESCALATION_DELAY_S}s")

    async with async_session() as session:
        try:
            # 1. Check if event is still active (not resolved)
            #    Support both VoiceDistressEvent and SafetyEvent models
            from app.models.voice_distress_event import VoiceDistressEvent

            event = None
            event_model = None

            # Try VoiceDistressEvent first (most common for voice alerts)
            vde = await session.get(VoiceDistressEvent, uuid.UUID(event_id))
            if vde:
                event = vde
                event_model = "VoiceDistressEvent"
            else:
                # Fallback to SafetyEvent (help requests, etc.)
                se = await session.get(SafetyEvent, uuid.UUID(event_id))
                if se:
                    event = se
                    event_model = "SafetyEvent"

            if not event:
                logger.warning(f"[ESCALATION] Event {event_id} not found in any model — skipping")
                return
            if event.status != "active":
                logger.info(f"[ESCALATION] Event {event_id} ({event_model}) already {event.status} — skipping")
                return

            # 2. Escalate: update event status
            if event_model == "SafetyEvent":
                event.risk_level = "critical"
                event.risk_score = max(event.risk_score, 0.95)
                event.updated_at = datetime.now(timezone.utc)
                event.signals = {**(event.signals or {}), "auto_escalated": True, "escalation_reason": "no_response_30s"}
            else:
                event.distress_score = max(event.distress_score, 0.95)
                event.status = "auto_sos"

            now = datetime.now(timezone.utc)

            # 3. Find all guardians and broadcast escalation (check BOTH tables)
            g_result = await session.execute(
                select(Guardian).where(
                    Guardian.user_id == uuid.UUID(user_id),
                    Guardian.is_active.is_(True),
                )
            )
            guardian_contacts = g_result.scalars().all()
            guardian_ids = []

            escalation_payload = {
                "type": "ESCALATION",
                "severity": "CRITICAL",
                "child_id": user_id,
                "child_name": child_name,
                "safety_event_id": event_id,
                "alert_type": alert_type,
                "message": f"NO RESPONSE from {child_name} for {ESCALATION_DELAY_S}s — auto-escalated to CRITICAL",
                "timestamp": now.isoformat(),
            }

            for gc in guardian_contacts:
                if gc.email:
                    gu_result = await session.execute(select(User).where(User.email == gc.email))
                    guardian_user = gu_result.scalar_one_or_none()
                    if guardian_user:
                        gid = str(guardian_user.id)
                        guardian_ids.append(gid)
                        await broadcaster.broadcast_to_user(gid, "safety_alert", escalation_payload)

            # Also check Relationship table (primary link source)
            from app.models.relationship import Relationship
            rel_result = await session.execute(
                select(Relationship).where(
                    Relationship.child_id == uuid.UUID(user_id),
                    Relationship.status == "accepted",
                )
            )
            for rel in rel_result.scalars().all():
                gid = str(rel.guardian_id)
                if gid not in guardian_ids:
                    guardian_ids.append(gid)
                    await broadcaster.broadcast_to_user(gid, "safety_alert", escalation_payload)

            # 4. Notify operators
            await broadcaster.broadcast_to_operators("safety_alert", escalation_payload)
            logger.warning(
                f"[ESCALATION_BROADCAST] event={event_id} guardians={len(guardian_ids)} operators=all"
            )

            # 5. Create GuardianAlert record
            active_ses_result = await session.execute(
                select(GuardianSession).where(
                    GuardianSession.user_id == uuid.UUID(user_id),
                    GuardianSession.status == "active",
                ).order_by(GuardianSession.started_at.desc()).limit(1)
            )
            active_ses = active_ses_result.scalar_one_or_none()
            if active_ses:
                alert = GuardianAlert(
                    session_id=active_ses.id,
                    user_id=uuid.UUID(user_id),
                    alert_type="auto_escalated",
                    severity="critical",
                    message=f"AUTO-ESCALATION: No response from {child_name} in {ESCALATION_DELAY_S}s",
                    details=f"Original alert: {alert_type}. SafetyEvent: {event_id}",
                    recommendation="Call your child immediately. If unreachable, contact local authorities.",
                )
                session.add(alert)

            # 6. Push notification to guardians (HIGH priority — works when app is killed)
            try:
                from app.services.push_service import send_push_to_user
                for gid in guardian_ids:
                    await send_push_to_user(
                        session, uuid.UUID(gid),
                        f"ESCALATION: {child_name} not responding!",
                        f"No response for {ESCALATION_DELAY_S}s. Call immediately!",
                        data={
                            "type": "ESCALATION",
                            "child_id": user_id,
                            "child_name": child_name,
                            "event_id": event_id,
                            "alert_type": alert_type,
                        },
                    )
            except Exception as e:
                logger.warning(f"[ESCALATION_PUSH] Failed: {e}")

            await session.commit()
            logger.warning(f"[ESCALATION_COMPLETE] event={event_id} status=critical guardians_notified={len(guardian_ids)}")

            # TIER 2: Start guardian failsafe — if NO guardian ACKs within 60s, escalate further
            if guardian_ids:
                schedule_guardian_failsafe(event_id, user_id, child_name, alert_type)

        except Exception as e:
            logger.error(f"[ESCALATION_ERROR] event={event_id}: {e}")
            await session.rollback()


# ── SMS DEDUP + RATE LIMITING HELPERS ──

def _is_sms_sent(event_id: str, phone: str) -> bool:
    """Check if SMS was already sent for this event + phone combo."""
    entries = _sms_log.get(event_id, [])
    return any(e["phone"] == phone and e["status"] in ("delivered", "failed") for e in entries)


def _record_sms(event_id: str, phone: str, contact_name: str, status: str):
    """Record SMS delivery attempt for dedup + audit."""
    if event_id not in _sms_log:
        _sms_log[event_id] = []
    _sms_log[event_id].append({
        "phone": phone,
        "contact_name": contact_name,
        "status": status,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
    # Cap log entries per event (prevent unbounded growth)
    if len(_sms_log[event_id]) > 50:
        _sms_log[event_id] = _sms_log[event_id][-50:]
    # Cap total events tracked (oldest evicted)
    if len(_sms_log) > 500:
        oldest_key = next(iter(_sms_log))
        del _sms_log[oldest_key]


def _is_rate_limited(phone: str) -> bool:
    """Check if phone has exceeded hourly SMS rate limit."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now.timestamp() - 3600
    # Prune old entries
    _sms_rate[phone] = [
        ts for ts in _sms_rate[phone]
        if ts.timestamp() > one_hour_ago
    ]
    return len(_sms_rate[phone]) >= SMS_RATE_LIMIT_PER_HOUR


def _record_rate(phone: str):
    """Record SMS send timestamp for rate limiting."""
    _sms_rate[phone].append(datetime.now(timezone.utc))


def get_sms_log(event_id: str) -> list[dict]:
    """Get SMS delivery log for a specific event (for debugging/audit)."""
    return _sms_log.get(event_id, [])
