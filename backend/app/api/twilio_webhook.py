"""
Twilio Status Callback Webhook
Receives call status updates from Twilio and stores in Redis for sequential escalation.

Hardened:
- Idempotent: SETNX guard prevents duplicate processing on Twilio retries
- Status data stored with 5min TTL

Twilio sends POST with form data:
  CallSid, CallStatus, To, From, AnsweredBy, CallDuration, etc.

CallStatus values: queued, ringing, in-progress, completed, busy, no-answer, failed, canceled
AnsweredBy values: human, machine_start, machine_end_beep, machine_end_silence, fax, unknown
"""
import logging
from fastapi import APIRouter, Request, Response

from app.services.redis_service import set_json, get_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twilio", tags=["twilio"])

CALL_STATUS_TTL = 300  # 5 min TTL for call status in Redis
REDIS_NS = "twilio_call"
DEDUP_NS = "twilio_cb_dedup"


def _try_claim_callback(call_sid: str, call_status: str) -> bool:
    """Idempotent guard: returns True only on first processing of this sid+status.
    Uses Redis SETNX to prevent duplicate processing on Twilio retries.
    """
    from app.services.redis_service import _get_client, _key
    c = _get_client()
    if not c:
        return True  # Redis down — process anyway, don't drop events

    dedup_key = _key(DEDUP_NS, f"{call_sid}:{call_status}")
    try:
        was_set = c.setnx(dedup_key, "1")
        if was_set:
            c.expire(dedup_key, CALL_STATUS_TTL)
        return bool(was_set)
    except Exception as e:
        logger.warning(f"[TWILIO_DEDUP_ERR] {e} — processing anyway")
        return True


@router.post("/status")
async def twilio_status_callback(request: Request):
    """Receive Twilio voice call status updates.
    No auth required — Twilio sends webhooks directly.
    Idempotent: duplicate callbacks for the same sid+status are dropped.
    """
    form = await request.form()

    call_sid = form.get("CallSid", "")
    call_status = form.get("CallStatus", "")
    to = form.get("To", "")
    from_num = form.get("From", "")
    answered_by = form.get("AnsweredBy", "")
    duration = form.get("CallDuration", "0")

    # Idempotent guard: drop duplicate Twilio retries
    if not _try_claim_callback(call_sid, call_status):
        logger.info(
            f"[TWILIO_STATUS_DEDUP] Duplicate callback dropped: sid={call_sid} status={call_status}"
        )
        return Response(content="<Response/>", media_type="application/xml", status_code=200)

    logger.warning(
        f"[TWILIO_STATUS] sid={call_sid} status={call_status} to={to} "
        f"answered_by={answered_by} duration={duration}s"
    )

    # Store full status data in Redis
    status_data = {
        "call_sid": call_sid,
        "status": call_status,
        "to": to,
        "from": from_num,
        "answered_by": answered_by,
        "duration": duration,
    }
    set_json(REDIS_NS, call_sid, status_data, ttl=CALL_STATUS_TTL)

    # Determine resolved status
    is_human_answer = (
        call_status == "in-progress" and answered_by in ("human", "")
    )
    is_voicemail = answered_by in (
        "machine_start", "machine_end_beep", "machine_end_silence", "machine_end_other"
    )

    if is_human_answer:
        logger.warning(f"[TWILIO_ANSWERED] sid={call_sid} to={to} — HUMAN PICKED UP")
        set_json(REDIS_NS, f"{call_sid}:resolved", "answered", ttl=CALL_STATUS_TTL)
    elif is_voicemail:
        logger.warning(f"[TWILIO_VOICEMAIL] sid={call_sid} to={to} — machine detected, NOT success")
        set_json(REDIS_NS, f"{call_sid}:resolved", "voicemail", ttl=CALL_STATUS_TTL)
    elif call_status in ("busy", "no-answer", "failed", "canceled"):
        logger.warning(f"[TWILIO_NOT_ANSWERED] sid={call_sid} to={to} status={call_status}")
        set_json(REDIS_NS, f"{call_sid}:resolved", call_status, ttl=CALL_STATUS_TTL)

    return Response(content="<Response/>", media_type="application/xml", status_code=200)


def get_call_status(call_sid: str) -> str | None:
    """Poll Redis for call resolution status.
    Returns: 'answered', 'voicemail', 'busy', 'no-answer', 'failed', 'canceled', or None (pending).
    """
    result = get_json(REDIS_NS, f"{call_sid}:resolved")
    return result if result else None
