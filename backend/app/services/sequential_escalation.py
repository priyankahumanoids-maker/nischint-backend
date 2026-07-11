"""
Intelligent Sequential Escalation Engine

Instead of calling all guardians simultaneously, this engine:
1. Sorts guardians by priority (primary first, fastest responders first)
2. Calls Guardian 1 → waits for answer → if no answer → calls Guardian 2 → ...
3. If nobody answers → SMS blast to all
4. Tracks results for audit trail
5. **Emits SSE events** at every step for live visibility

Flow:
  AI detects risk → Call Guardian 1 → No answer → Call Guardian 2 →
  No answer → Call Guardian 3 → SMS blast → Command center escalation
"""
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CALL_WAIT_TIMEOUT_S = 35  # max seconds to wait for a single call result
POLL_INTERVAL_S = 2  # how often to check Redis for call status

# Kill switch: disable all escalation calls globally
ESCALATION_ENABLED = os.environ.get("ESCALATION_ENABLED", "true").lower() == "true"


@dataclass
class EscalationContact:
    """A contact to escalate to, with priority metadata."""
    phone: str
    name: str
    source: str  # 'guardian_relationship', 'relationship', 'guardian', 'emergency_contact'
    is_primary: bool = False
    priority: int = 99
    guardian_user_id: str | None = None


@dataclass
class EscalationResult:
    """Result of escalating to a single contact."""
    phone: str
    name: str
    source: str
    method: str  # 'voice_answered', 'voice_voicemail', 'voice_no_answer', 'sms_fallback', 'failed'
    call_sid: str | None = None
    call_status: str | None = None
    answered_by: str | None = None
    success: bool = False


@dataclass
class EscalationSummary:
    """Full escalation audit trail."""
    event_id: str
    child_name: str
    results: list[EscalationResult] = field(default_factory=list)
    resolved_by: str | None = None  # phone of person who answered
    total_calls: int = 0
    total_sms: int = 0
    sms_blast_sent: bool = False


def sort_contacts_by_priority(contacts: list[EscalationContact]) -> list[EscalationContact]:
    """Sort contacts: primary guardians first, then by priority field (lower = higher priority)."""
    return sorted(contacts, key=lambda c: (
        not c.is_primary,  # primary first (False < True, so negate)
        c.priority,        # lower priority number = higher priority
    ))


async def emit_escalation_event(
    guardian_ids: list[str],
    event_id: str,
    child_name: str,
    status: str,
    current_guardian: dict | None = None,
    sequence: int = 0,
    total_guardians: int = 0,
    resolved_by: str | None = None,
):
    """Broadcast an escalation_update SSE event to all guardians + operators."""
    from app.services.event_broadcaster import broadcaster

    payload = {
        "event_id": event_id,
        "child_name": child_name,
        "status": status,
        "current_guardian": current_guardian,
        "sequence": sequence,
        "total_guardians": total_guardians,
        "resolved_by": resolved_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await broadcaster.broadcast_escalation_update(guardian_ids, payload)
        logger.info(
            f"[ESCALATION_SSE] status={status} guardian={current_guardian.get('name') if current_guardian else 'N/A'} "
            f"seq={sequence}/{total_guardians} event={event_id}"
        )
    except Exception as e:
        logger.warning(f"[ESCALATION_SSE_ERROR] Failed to emit: {e}")


async def wait_for_call_status(call_sid: str, timeout: int = CALL_WAIT_TIMEOUT_S) -> str:
    """Poll Redis for Twilio call status resolution.
    Returns: 'answered', 'voicemail', 'busy', 'no-answer', 'failed', 'canceled', or 'timeout'.
    """
    from app.api.twilio_webhook import get_call_status

    elapsed = 0
    while elapsed < timeout:
        status = get_call_status(call_sid)
        if status:
            logger.info(f"[CALL_STATUS] sid={call_sid} resolved={status} after {elapsed}s")
            return status
        await asyncio.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S

    logger.warning(f"[CALL_STATUS_TIMEOUT] sid={call_sid} no resolution in {timeout}s")
    return "timeout"


async def intelligent_escalation(
    event_id: str,
    contacts: list[EscalationContact],
    child_name: str,
    alert_type: str,
    last_seen: str = "unknown",
    callback_base_url: str = "",
    guardian_ids: list[str] | None = None,
) -> EscalationSummary:
    """Run the intelligent sequential escalation chain with live SSE events.

    For each contact (in priority order):
      1. Emit SSE: "calling" → Make voice call with status callback
      2. Wait for call result (up to CALL_WAIT_TIMEOUT_S)
      3. If answered → Emit SSE: "answered" → STOP
      4. If not answered → Emit SSE: "no_answer" → move to next
    After all exhausted → Emit SSE: "sms_blast" → SMS blast to all → Emit SSE: "exhausted"
    """
    from app.services.sms_service import (
        make_voice_call_with_callback,
        send_failsafe_sms,
        is_voice_available,
        is_available as sms_available,
    )

    summary = EscalationSummary(event_id=event_id, child_name=child_name)

    # Kill switch: abort if escalation is globally disabled
    if not ESCALATION_ENABLED:
        logger.warning(
            f"[SEQ_ESCALATION_KILLED] event={event_id} child={child_name} — "
            f"ESCALATION_ENABLED=false, aborting all calls and SMS"
        )
        return summary

    sorted_contacts = sort_contacts_by_priority(contacts)
    called_phones: set[str] = set()
    _guardian_ids = guardian_ids or []
    total = len(sorted_contacts)

    logger.warning(
        f"[SEQ_ESCALATION_START] event={event_id} child={child_name} "
        f"contacts={total} type={alert_type}"
    )

    # Emit: escalation started
    await emit_escalation_event(
        _guardian_ids, event_id, child_name,
        status="started",
        total_guardians=total,
    )

    # Phase 1: Sequential voice calls
    if is_voice_available():
        for idx, contact in enumerate(sorted_contacts):
            if contact.phone in called_phones:
                continue
            called_phones.add(contact.phone)
            seq = idx + 1

            guardian_info = {
                "name": contact.name,
                "phone": contact.phone,
                "priority": contact.priority,
                "source": contact.source,
            }

            logger.warning(
                f"[SEQ_ESCALATION_CALL] event={event_id} calling={contact.phone} "
                f"name={contact.name} primary={contact.is_primary} priority={contact.priority}"
            )

            # Emit: calling this guardian
            await emit_escalation_event(
                _guardian_ids, event_id, child_name,
                status="calling",
                current_guardian=guardian_info,
                sequence=seq,
                total_guardians=total,
            )

            # Make call with status callback
            call_sid = make_voice_call_with_callback(
                to=contact.phone,
                child_name=child_name,
                alert_type=alert_type,
                event_id=event_id,
                contact_name=contact.name,
                callback_url=f"{callback_base_url}/api/twilio/status" if callback_base_url else "",
            )

            result = EscalationResult(
                phone=contact.phone,
                name=contact.name,
                source=contact.source,
                call_sid=call_sid,
                method="voice_no_answer",
            )
            summary.total_calls += 1

            if not call_sid:
                result.method = "failed"
                result.call_status = "call_creation_failed"
                summary.results.append(result)

                await emit_escalation_event(
                    _guardian_ids, event_id, child_name,
                    status="failed",
                    current_guardian=guardian_info,
                    sequence=seq,
                    total_guardians=total,
                )

                logger.warning(f"[SEQ_ESCALATION_CALL_FAILED] phone={contact.phone} — moving to next")
                continue

            # Wait for Twilio callback
            call_status = await wait_for_call_status(call_sid)
            result.call_status = call_status

            if call_status == "answered":
                result.method = "voice_answered"
                result.success = True
                result.answered_by = "human"
                summary.resolved_by = contact.phone
                summary.results.append(result)

                await emit_escalation_event(
                    _guardian_ids, event_id, child_name,
                    status="answered",
                    current_guardian=guardian_info,
                    sequence=seq,
                    total_guardians=total,
                    resolved_by=contact.name,
                )

                logger.warning(
                    f"[SEQ_ESCALATION_RESOLVED] event={event_id} answered_by={contact.name} "
                    f"phone={contact.phone} — STOPPING CHAIN"
                )
                break

            elif call_status == "voicemail":
                result.method = "voice_voicemail"
                result.answered_by = "machine"

                await emit_escalation_event(
                    _guardian_ids, event_id, child_name,
                    status="voicemail",
                    current_guardian=guardian_info,
                    sequence=seq,
                    total_guardians=total,
                )

                logger.warning(f"[SEQ_ESCALATION_VOICEMAIL] phone={contact.phone} — moving to next")

            elif call_status in ("busy", "no-answer", "failed", "canceled", "timeout"):
                result.method = f"voice_{call_status}"

                await emit_escalation_event(
                    _guardian_ids, event_id, child_name,
                    status="no_answer",
                    current_guardian=guardian_info,
                    sequence=seq,
                    total_guardians=total,
                )

                logger.warning(f"[SEQ_ESCALATION_{call_status.upper()}] phone={contact.phone} — moving to next")

            summary.results.append(result)
    else:
        logger.warning("[SEQ_ESCALATION] Voice not available — skipping to SMS blast")

    # Phase 2: SMS blast if nobody answered
    if not summary.resolved_by:
        logger.warning(
            f"[SEQ_ESCALATION_EXHAUSTED] event={event_id} — nobody answered. "
            f"Sending SMS blast to all {total} contacts"
        )

        await emit_escalation_event(
            _guardian_ids, event_id, child_name,
            status="sms_blast",
            total_guardians=total,
        )

        if sms_available():
            for contact in sorted_contacts:
                success = send_failsafe_sms(
                    to=contact.phone,
                    child_name=child_name,
                    alert_type=alert_type,
                    last_seen=last_seen,
                    contact_name=contact.name,
                )
                summary.total_sms += 1

                existing = next((r for r in summary.results if r.phone == contact.phone), None)
                if not existing or existing.success:
                    summary.results.append(EscalationResult(
                        phone=contact.phone,
                        name=contact.name,
                        source=contact.source,
                        method="sms_fallback",
                        success=success,
                    ))

                if success:
                    logger.warning(f"[SEQ_ESCALATION_SMS] to={contact.phone} name={contact.name} — sent")
                else:
                    logger.error(f"[SEQ_ESCALATION_SMS_FAILED] to={contact.phone}")

            summary.sms_blast_sent = True
        else:
            logger.warning("[SEQ_ESCALATION_NO_SMS] Twilio not configured — cannot SMS blast")

        await emit_escalation_event(
            _guardian_ids, event_id, child_name,
            status="exhausted",
            total_guardians=total,
        )

    # Summary log
    logger.warning(
        f"[SEQ_ESCALATION_COMPLETE] event={event_id} child={child_name} "
        f"calls={summary.total_calls} sms={summary.total_sms} "
        f"resolved_by={summary.resolved_by or 'NONE'} "
        f"sms_blast={summary.sms_blast_sent}"
    )

    return summary
