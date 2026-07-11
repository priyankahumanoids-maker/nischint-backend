# Voice Distress Detection Service
#
# Hybrid architecture: on-device acoustic + Whisper transcription + keyword engine
# Hybrid score: acoustic(0.6) + keyword(0.5) + whisper_boost(0.7)
# Trigger: score >= 0.50 → voice_alert, score >= 0.9 → auto-SOS
# Cooldown: 30s between events (unless score > 0.9)

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.voice_distress_event import VoiceDistressEvent
from app.services.event_broadcaster import broadcaster
from app.services.redis_service import set_json as _redis_set, get_json as _redis_get

logger = logging.getLogger(__name__)

_mem: dict = {}

COOLDOWN_S = 30
AUTO_SOS_THRESHOLD = 0.9
ALERT_THRESHOLD = 0.50
W_SCREAM = 0.55  # Weight when client detects scream — crosses threshold alone

DISTRESS_KEYWORDS = {"help", "stop", "leave me", "call police", "emergency", "don't touch", "save me", "please help"}


# ── DLQ for voice-distress audit rows that failed to persist ──────
# Compensating action for the inner GuardianAlert insert below. SSE
# + FCM push has ALREADY fired by the time the insert is attempted;
# the only thing this DLQ recovers is the *audit trail*. Bounded to
# protect Redis memory during a sustained DB outage.
_VOICE_DISTRESS_DLQ_NAMESPACE = "dlq"
_VOICE_DISTRESS_DLQ_KEY = "voice_distress_audit"
_VOICE_DISTRESS_DLQ_MAX = 500


def _push_voice_distress_audit_dlq(payload: dict) -> bool:
    """LPUSH the voice-distress audit payload to a bounded Redis
    list so an out-of-band reconciler can replay it once the DB is
    healthy. Returns True on enqueue, False on Redis-unavailable
    (caller has already emitted a CRITICAL structured log)."""
    try:
        import json
        from app.services.redis_service import _get_client
        c = _get_client()
        if not c:
            return False
        full_key = f"{_VOICE_DISTRESS_DLQ_NAMESPACE}:{_VOICE_DISTRESS_DLQ_KEY}"
        c.lpush(full_key, json.dumps(payload, default=str))
        c.ltrim(full_key, 0, _VOICE_DISTRESS_DLQ_MAX - 1)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort DLQ
        logger.debug("voice distress DLQ push skipped: %r", e)
        return False


async def trigger_sos_internal(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    event_id: str,
    score: float,
    keywords: list[str] | None,
) -> str | None:
    """
    Internal SOS trigger — bypasses RBAC, called directly by the backend
    when voice distress risk is CRITICAL (score >= threshold).
    Creates SOS record, notifies guardians, triggers escalation pipeline.
    """
    try:
        from app.services.emergency_engine import trigger_silent_sos
        sos_result = await trigger_silent_sos(
            session=session,
            user_id=user_id,
            lat=lat,
            lng=lng,
            trigger_source="voice_distress",
            device_metadata={
                "voice_event_id": event_id,
                "distress_score": score,
                "keywords": keywords,
            },
        )
        emergency_id = sos_result.get("event_id")
        logger.warning(
            f"[VOICE_SOS_INTERNAL_TRIGGER] user={user_id} score={score:.2f} "
            f"emergency_id={emergency_id} keywords={keywords}"
        )
        return emergency_id
    except Exception as e:
        logger.error(f"[VOICE_SOS_INTERNAL_TRIGGER] FAILED user={user_id}: {e}")
        return None


def _set(key, data):
    ok = _redis_set("voice_distress", key, data)
    if not ok:
        _mem[f"voice_distress:{key}"] = data


def _get(key):
    v = _redis_get("voice_distress", key)
    return v if v is not None else _mem.get(f"voice_distress:{key}")


def compute_distress_score(keywords: list[str] | None, scream_detected: bool,
                           repeated: bool, audio_features: dict | None) -> float:
    """Legacy acoustic-only score (used when no audio_base64 provided)."""
    return compute_hybrid_score(
        scream_detected=scream_detected,
        audio_features=audio_features,
        on_device_keywords=keywords,
        whisper_keywords=None,
        repeated=repeated,
    )[0]


def compute_hybrid_score(
    scream_detected: bool,
    audio_features: dict | None,
    on_device_keywords: list[str] | None,
    whisper_keywords: list[str] | None,
    repeated: bool = False,
) -> tuple[float, str, list[str]]:
    """
    Hybrid distress score: scream(0.55) + keyword(0.5) + whisper_boost(0.7).
    Threshold: score >= 0.50 → alert, score >= 0.9 → auto-SOS.

    Returns: (score, risk_level, all_matched_keywords)
    """
    score = 0.0
    amp = 0.0
    if audio_features:
        amp = audio_features.get("amplitude", 0)

    # 1. Scream detected by client — W_SCREAM (crosses threshold alone)
    if scream_detected:
        score += W_SCREAM

    # 2. Keyword score — from Whisper transcript or on-device detection
    all_keywords = list(set((whisper_keywords or []) + (on_device_keywords or [])))
    if all_keywords:
        score += 0.5

    # 3. Whisper boost — quiet distress (keyword detected at low amplitude)
    if amp < 0.4 and all_keywords:
        score += 0.7

    # 4. Whisper-specific safety: require repeat for quiet distress
    #    If amp < 0.4 and keywords found but NOT repeated, cap at HIGH (not CRITICAL)
    if amp < 0.4 and all_keywords and not repeated:
        score = min(score, 0.85)

    score = round(min(1.0, score), 3)

    # Determine risk level
    if score >= AUTO_SOS_THRESHOLD:
        risk = "CRITICAL"
    elif score >= ALERT_THRESHOLD:
        risk = "HIGH"
    else:
        risk = "LOW"

    logger.info(
        f"[VOICE_SCORE_COMPUTED] score={score} risk={risk} W_SCREAM={'YES' if scream_detected else 'NO'} "
        f"amp={amp:.2f} keywords={all_keywords} repeated={repeated}"
    )

    return score, risk, all_keywords


def _check_cooldown(user_id: str, score: float) -> bool:
    """Returns True if in cooldown. Bypass if score > 0.9."""
    if score >= AUTO_SOS_THRESHOLD:
        return False  # Never block critical alerts
    last = _get(f"cooldown:{user_id}")
    if last:
        last_time = datetime.fromisoformat(last)
        if (datetime.now(timezone.utc) - last_time).total_seconds() < COOLDOWN_S:
            return True
    return False


async def report_voice_distress(
    session: AsyncSession,
    user_id: str,
    lat: float,
    lng: float,
    keywords: list[str] | None,
    scream_detected: bool,
    repeated: bool,
    audio_features: dict | None,
    audio_base64: str | None = None,
    client_confidence: float | None = None,
    trigger_type: str | None = None,
) -> dict:
    """Report voice distress event. Runs Whisper + keyword engine + hybrid scoring."""

    logger.info(
        f"[VOICE_REPORT] user={user_id} trigger={trigger_type} "
        f"client_confidence={client_confidence} scream={scream_detected}"
    )

    # ── Step 1: Whisper transcription (if audio provided) ──
    whisper_transcript = None
    whisper_keywords = None
    if audio_base64:
        try:
            from app.services.whisper_transcription import transcribe_audio_base64
            result = await transcribe_audio_base64(audio_base64)
            if result.get("success") and result.get("text"):
                whisper_transcript = result["text"]
                # Run keyword engine on transcript
                from app.services.keyword_engine import match_distress_keywords
                whisper_keywords = match_distress_keywords(whisper_transcript)
                logger.info(
                    f"[WHISPER_RESULT] user={user_id} transcript='{whisper_transcript[:80]}' "
                    f"keywords={whisper_keywords}"
                )
            else:
                logger.warning(f"[WHISPER_RESULT] user={user_id} failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"[WHISPER_RESULT] user={user_id} exception: {e}")

    # ── Step 2: Hybrid score ──
    score, risk_level, all_keywords = compute_hybrid_score(
        scream_detected=scream_detected,
        audio_features=audio_features,
        on_device_keywords=keywords,
        whisper_keywords=whisper_keywords,
        repeated=repeated,
    )

    if score < ALERT_THRESHOLD:
        return {"status": "below_threshold", "distress_score": score, "message": "Score below alert threshold"}

    if _check_cooldown(user_id, score):
        return {"status": "cooldown", "message": "Voice event recently reported. Wait 30s."}

    is_auto_sos = score >= AUTO_SOS_THRESHOLD

    event = VoiceDistressEvent(
        user_id=uuid.UUID(user_id),
        lat=lat, lng=lng,
        keywords=all_keywords or keywords,
        scream_detected=scream_detected,
        repeated_detection=repeated,
        audio_features=audio_features,
        distress_score=score,
        status="auto_sos" if is_auto_sos else "active",
        whisper_transcript=whisper_transcript,
        whisper_verified=whisper_transcript is not None,
    )
    session.add(event)
    await session.flush()
    event_id = str(event.id)

    _set(f"cooldown:{user_id}", datetime.now(timezone.utc).isoformat())

    # Auto-SOS for critical distress — handled internally (no client call needed)
    emergency_id = None
    if is_auto_sos:
        emergency_id = await trigger_sos_internal(
            session, user_id, lat, lng, event_id, score, all_keywords,
        )
        if emergency_id:
            event.emergency_event_id = uuid.UUID(emergency_id)

    # Use hybrid keyword list for display
    matched = all_keywords or []

    sse_data = {
        "event_id": event_id,
        "user_id": user_id,
        "lat": lat, "lng": lng,
        "distress_score": score,
        "risk_level": risk_level,
        "keywords": matched,
        "whisper_transcript": whisper_transcript,
        "scream_detected": scream_detected,
        "repeated": repeated,
        "auto_sos": is_auto_sos,
        "emergency_event_id": emergency_id,
        "client_confidence": client_confidence,
        "trigger_type": trigger_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await broadcaster.broadcast_to_user(user_id, "voice_alert", sse_data)
    await broadcaster.broadcast_to_operators("voice_alert", sse_data)

    # ── Migration to unified `trigger_alert` (NISCH-001 Phase 2) ──
    # Behind feature flag `ALERT_TRIGGER_V2_VOICE_DISTRESS`. When True,
    # the unified path replaces the inline guardian fan-out + push +
    # GuardianAlert creation block below. We keep both paths in-tree
    # while we burn in v2; the flag flips off in seconds if v2 misfires.
    import os as _os
    _use_v2 = _os.environ.get("ALERT_TRIGGER_V2_VOICE_DISTRESS", "false").lower() == "true"
    if _use_v2:
        from app.services.alert_trigger import trigger_alert
        from app.models.user import User as _User
        cu = (await session.execute(select(_User).where(_User.id == uuid.UUID(user_id)))).scalar_one_or_none()
        _child_name = cu.full_name if (cu and cu.full_name) else "Child"

        # Resolve active session_id (if any) so the alert can link.
        from app.models.guardian import GuardianSession as _GS
        _active_ses = (await session.execute(
            select(_GS).where(_GS.user_id == uuid.UUID(user_id), _GS.status == "active")
        )).scalar_one_or_none()
        _session_id = str(_active_ses.id) if _active_ses else None

        _severity = "critical" if is_auto_sos else "high"
        _msg = f"Voice distress detected from {_child_name}!"
        if scream_detected:
            _msg = f"Scream detected from {_child_name} — distress score {score:.1f}"
        if matched:
            _msg += f" (keywords: {', '.join(matched)})"

        # Idempotency key dedups repeated triggers from the same event,
        # not unrelated voice-distress signals — so we key on event_id.
        result = await trigger_alert(
            session,
            kind="voice_distress",
            user_id=user_id,
            severity=_severity,
            message=_msg,
            details=f"Score: {score:.2f}, Scream: {scream_detected}, Keywords: {matched}",
            location={"lat": lat, "lng": lng} if lat and lng else None,
            session_id=_session_id,
            sse_event_type="safety_alert",
            sse_payload_extras={
                "type": "VOICE_DISTRESS",
                "safety_event_id": event_id,
                "distress_score": score,
                "scream_detected": scream_detected,
                "keywords": matched,
                "auto_sos": is_auto_sos,
            },
            louder=is_auto_sos,
            idempotency_key=f"voice:{event_id}",
            cooldown_s=20,  # one alert per event_id within 20s
        )
        await session.commit()

        # Auto-escalation timer still runs from the legacy path below
        # for non-auto-SOS, so jump straight to that branch.
        if not is_auto_sos:
            try:
                from app.services.auto_escalation_engine import schedule_escalation
                schedule_escalation(event_id, user_id, _child_name, "voice_distress")
            except Exception as e:
                logger.error(f"Auto-escalation schedule failed: {e}")

        # Safety brain hook (legacy path also calls this) — keep parity.
        try:
            from app.services.safety_brain_service import on_voice_distress
            await on_voice_distress(session, user_id, score, lat, lng)
        except Exception as e:
            logger.error(f"Safety Brain voice hook failed: {e}")

        logger.warning(
            f"[ALERT_TRIGGER_V2] voice_distress dispatched: {result.to_dict()}"
        )
        return  # short-circuit — skip the legacy block below

    # ── Broadcast to ALL linked guardians (critical escalation) ──
    from app.models.user import User
    from app.models.guardian import Guardian, GuardianAlert, GuardianSession

    # Get child's name
    child_result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    child_user = child_result.scalar_one_or_none()
    child_name = child_user.full_name if child_user else "Child"

    guardian_payload = {
        "type": "VOICE_DISTRESS",
        "safety_event_id": event_id,
        "child_id": user_id,
        "child_name": child_name,
        "distress_score": score,
        "scream_detected": scream_detected,
        "keywords": matched,
        "auto_sos": is_auto_sos,
        "lat": lat, "lng": lng,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Find guardians linked to this child (check BOTH Guardian table AND Relationship table)
    g_result = await session.execute(
        select(Guardian).where(
            Guardian.user_id == uuid.UUID(user_id),
            Guardian.is_active.is_(True),
        )
    )
    guardian_contacts = g_result.scalars().all()
    notified_guardians = 0

    guardian_ids = []
    for gc in guardian_contacts:
        if gc.email:
            gu_result = await session.execute(select(User).where(User.email == gc.email))
            guardian_user = gu_result.scalar_one_or_none()
            if guardian_user:
                gid = str(guardian_user.id)
                guardian_ids.append(gid)
                await broadcaster.broadcast_to_user(gid, "safety_alert", guardian_payload)
                notified_guardians += 1
                logger.info(f"[VOICE_SSE_BROADCAST] guardian={gid} child={user_id} score={score:.2f} (via Guardian table)")

    # Also check Relationship table (code-based linking — primary link source)
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
            await broadcaster.broadcast_to_user(gid, "safety_alert", guardian_payload)
            notified_guardians += 1
            logger.info(f"[VOICE_SSE_BROADCAST] guardian={gid} child={user_id} score={score:.2f} (via Relationship table)")

    logger.info(f"[ALERT_GUARDIAN_IDS] guardians={guardian_ids} child={user_id} notified={notified_guardians}")

    if notified_guardians > 0:
        logger.warning(
            f"[SSE_VOICE_ALERT] DELIVERED to {notified_guardians} guardians — "
            f"child={user_id} score={score:.2f} risk={risk_level} scream={scream_detected}"
        )
        # FCM Push fallback — guarantees delivery even when app is killed
        try:
            from app.services.push_service import send_push_to_user
            for gid in guardian_ids:
                await send_push_to_user(
                    session, uuid.UUID(gid),
                    f"Voice Alert: {child_name}",
                    f"Distress detected from {child_name} (score: {score:.0%})",
                    data={
                        "type": "VOICE_DISTRESS",
                        "child_id": user_id,
                        "child_name": child_name,
                        "event_id": event_id,
                        "score": str(score),
                    },
                )
        except Exception as e:
            logger.warning(f"[FCM_PUSH] Voice distress push failed: {e}")
    else:
        logger.warning(
            f"[SSE_VOICE_ALERT] NO GUARDIANS FOUND — child={user_id} score={score:.2f} "
            f"guardian_contacts={len(guardian_contacts)} (check Guardian.user_id linkage)"
        )

    # Create GuardianAlert record if child has an active session
    try:
        active_session = await session.execute(
            select(GuardianSession).where(
                GuardianSession.user_id == uuid.UUID(user_id),
                GuardianSession.status == "active",
            )
        )
        active_ses = active_session.scalar_one_or_none()
        if active_ses:
            severity = "critical" if is_auto_sos else "high"
            alert_msg = f"Voice distress detected from {child_name}!"
            if scream_detected:
                alert_msg = f"Scream detected from {child_name} — distress score {score:.1f}"
            if matched:
                alert_msg += f" (keywords: {', '.join(matched)})"

            ga = GuardianAlert(
                session_id=active_ses.id,
                user_id=uuid.UUID(user_id),
                alert_type="voice_distress",
                severity=severity,
                message=alert_msg,
                details=f"Score: {score:.2f}, Scream: {scream_detected}, Keywords: {matched}",
                recommendation="Contact your child immediately or call emergency services.",
                location={"lat": lat, "lng": lng} if lat and lng else None,
            )
            session.add(ga)
            logger.info(f"[ALERT_CREATED] type=voice_distress child={user_id} severity={severity}")
    except SQLAlchemyError as e:
        # Compensating action for safety-critical event dispatch:
        # SSE + FCM push already fanned out upstream (lines ~415-
        # 425), so guardians are already being notified. The audit
        # row is the only persistent record — push the planned
        # GuardianAlert payload to a bounded Redis DLQ
        # (`nischint:dlq:voice_distress_audit`) so an out-of-band
        # reconciler can replay it, AND emit a CRITICAL structured
        # log so on-call sees the gap immediately.
        _push_voice_distress_audit_dlq({
            "event_id":         event_id,
            "child_user_id":    user_id,
            "child_name":       child_name,
            "score":            score,
            "scream_detected":  scream_detected,
            "matched_keywords": matched,
            "is_auto_sos":      is_auto_sos,
            "lat":              lat,
            "lng":              lng,
            "failed_at":        datetime.now(timezone.utc).isoformat(),
            "error_type":       type(e).__name__,
            "error":            str(e)[:200],
        })
        logger.critical(
            "voice_distress_audit_row_dlq",
            extra={
                "event":         "voice_distress_audit_row_dlq",
                "event_id":      event_id,
                "child_user_id": user_id,
                "score":         score,
                "error_type":    type(e).__name__,
            },
        )

    logger.warning(f"Voice distress: user={user_id}, score={score:.2f}, risk={risk_level}, "
                   f"trigger={trigger_type}, confidence={client_confidence}, "
                   f"keywords={matched}, whisper='{whisper_transcript}', "
                   f"scream={scream_detected}, auto_sos={is_auto_sos}")

    await session.commit()

    # Schedule auto-escalation timer (30s) — if child doesn't respond, escalate to CRITICAL
    if not is_auto_sos:  # auto-SOS already escalated; no need to double-escalate
        try:
            from app.services.auto_escalation_engine import schedule_escalation
            schedule_escalation(event_id, user_id, child_name, "voice_distress")
        except Exception as e:
            logger.error(f"Auto-escalation schedule failed: {e}")

    # Feed signal to Safety Brain (augment, don't replace existing SSE)
    try:
        from app.services.safety_brain_service import on_voice_distress
        await on_voice_distress(session, user_id, score, lat, lng)
    except Exception as e:
        logger.error(f"Safety Brain voice hook failed: {e}")

    return {
        "status": "auto_sos" if is_auto_sos else "alert",
        "event_id": event_id,
        "distress_score": score,
        "risk_level": risk_level,
        "keywords_matched": matched,
        "whisper_transcript": whisper_transcript,
        "scream_detected": scream_detected,
        "auto_sos": is_auto_sos,
        "emergency_event_id": emergency_id,
        "client_confidence": client_confidence,
        "trigger_type": trigger_type,
    }


async def resolve_voice_distress(session: AsyncSession, event_id: str, user_id: str, resolved_by: str) -> dict:
    result = await session.execute(
        select(VoiceDistressEvent).where(VoiceDistressEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "Voice distress event not found"}
    if str(event.user_id) != user_id:
        return {"error": "Not authorized"}
    if event.status in ("resolved", "false_positive"):
        return {"status": "already_resolved"}

    now = datetime.now(timezone.utc)
    event.status = "false_positive" if resolved_by == "false_positive" else "resolved"
    event.resolved_by = resolved_by
    event.resolved_at = now
    await session.commit()

    # Cancel auto-escalation timer — child responded
    try:
        from app.services.auto_escalation_engine import cancel_escalation
        cancel_escalation(event_id)
    except Exception as e:
        logger.warning(f"Cancel escalation failed: {e}")

    sse_data = {"event_id": event_id, "user_id": user_id, "resolved_by": resolved_by, "timestamp": now.isoformat()}
    await broadcaster.broadcast_to_user(user_id, "voice_distress_resolved", sse_data)
    await broadcaster.broadcast_to_operators("voice_distress_resolved", sse_data)

    return {"status": event.status, "event_id": event_id, "resolved_by": resolved_by}


async def get_voice_distress_events(session: AsyncSession, user_id: str | None = None, limit: int = 20) -> list[dict]:
    query = select(VoiceDistressEvent).order_by(desc(VoiceDistressEvent.created_at)).limit(limit)
    if user_id:
        query = query.where(VoiceDistressEvent.user_id == uuid.UUID(user_id))
    result = await session.execute(query)
    return [
        {
            "event_id": str(e.id), "user_id": str(e.user_id),
            "lat": e.lat, "lng": e.lng,
            "keywords": e.keywords, "scream_detected": e.scream_detected,
            "repeated_detection": e.repeated_detection,
            "audio_features": e.audio_features,
            "distress_score": e.distress_score,
            "status": e.status, "resolved_by": e.resolved_by,
            "emergency_event_id": str(e.emergency_event_id) if e.emergency_event_id else None,
            "whisper_verified": e.whisper_verified,
            "whisper_transcript": e.whisper_transcript,
            "whisper_confidence": e.whisper_confidence,
            "verification_status": e.verification_status,
            "distress_phrases_found": e.distress_phrases_found,
            "trigger_type": e.trigger_type,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in result.scalars().all()
    ]
