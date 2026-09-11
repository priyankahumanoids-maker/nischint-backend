"""NISCHINT central AI safety decision, confirmation, and Guardian escalation.

Phase 3 confirmation-gated contract:
- protected member's authenticated device submits ONE fused AI candidate;
- backend independently re-validates Motion/Voice/Location evidence;
- backend enriches risk with EXISTING external-signal providers:
  SACHET/NDMA, Weather, and TomTom Traffic (fail-quiet, no fake provider data);
- EVERY AI-origin actionable candidate asks the protected member first;
- ``safe`` resolves with NO Guardian alert;
- ``help`` or confirmation timeout creates ONE Guardian-facing alert through
  the existing ``alert_trigger`` pipeline (SSE/FCM/preferences/dedupe);
- models and mobile code NEVER call Firebase/SOS/Guardian delivery directly;
- ``NISCHINT_AI_GUARDIAN_ALERTS_ENABLED`` defaults ON, as requested.

External context may strengthen confidence, but cannot invent evidence. Location-only
escalation additionally requires Android feature-parity approval AND corroborating
SACHET/Weather/Traffic risk before a protected-member confirmation is created.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.product_roles import is_protected_member
from app.models.user import User

logger = logging.getLogger(__name__)

_ENV_GATE = "NISCHINT_AI_GUARDIAN_ALERTS_ENABLED"
_DEFAULT_CONFIRMATION_TIMEOUT_S = 60
_RELEVANT_EXTERNAL_PROVIDERS = {"sachet", "weather", "tomtom"}

_DDL = """
CREATE TABLE IF NOT EXISTS ai_safety_events (
    id UUID PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_event_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    adjusted_score DOUBLE PRECISION NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    location JSONB NULL,
    authoritative_anchor TEXT NULL,
    external_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'stored_not_actionable',
    confirmation_expires_at TIMESTAMPTZ NULL,
    response TEXT NULL,
    responded_at TIMESTAMPTZ NULL,
    notification_gate_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    guardian_alert_dispatched BOOLEAN NOT NULL DEFAULT FALSE,
    guardian_alert_id TEXT NULL,
    dispatch_result JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(member_id, client_event_id)
)
"""

# These make the service safe if a preview environment happened to create an older
# Phase-3 table before the final confirmation-gated deployment.
_ALTERS = [
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS adjusted_score DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS external_context JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'stored_not_actionable'",
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS confirmation_expires_at TIMESTAMPTZ NULL",
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS response TEXT NULL",
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS responded_at TIMESTAMPTZ NULL",
    "ALTER TABLE ai_safety_events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
]

_table_ready = False
_table_lock = asyncio.Lock()


def guardian_ai_alerts_enabled() -> bool:
    return str(os.getenv(_ENV_GATE, "true")).strip().lower() in {
        "1", "true", "yes", "on", "enabled"
    }


def confirmation_timeout_seconds() -> int:
    try:
        value = int(os.getenv("NISCHINT_AI_CONFIRMATION_TIMEOUT_SECONDS", str(_DEFAULT_CONFIRMATION_TIMEOUT_S)))
    except (TypeError, ValueError):
        value = _DEFAULT_CONFIRMATION_TIMEOUT_S
    return max(15, min(300, value))


async def ensure_ai_safety_event_table() -> None:
    global _table_ready
    if _table_ready:
        return
    async with _table_lock:
        if _table_ready:
            return
        from app.db.session import async_session
        async with async_session() as session:
            await session.execute(text(_DDL))
            for statement in _ALTERS:
                await session.execute(text(statement))
            await session.commit()
        _table_ready = True


def _json(value: Any, fallback: Any) -> str:
    try:
        return json.dumps(value if value is not None else fallback, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps(fallback, separators=(",", ":"))


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _authoritative_anchor(payload: dict[str, Any]) -> str | None:
    """Defense-in-depth Motion/Voice classification.

    Scream/Cry are supporting-only. Location needs separate external-context
    corroboration and is therefore handled after provider evaluation.
    """
    motion = payload.get("motion") or {}
    fall_probability = _clamp01(motion.get("humanFallProbability"))
    try:
        fall_threshold = float(motion.get("humanFallThreshold") or 1)
    except (TypeError, ValueError):
        fall_threshold = 1.0
    if motion.get("ready") and fall_probability >= fall_threshold:
        return "MOTION_HUMAN_FALL"

    voice = payload.get("voice") or {}
    role = str(voice.get("evidenceRole") or "")
    semantic_score = _clamp01(voice.get("semanticScore"))
    distress_score = _clamp01(voice.get("distressScore"))

    if voice.get("ready") and role == "REQUIRED_SEMANTIC" and semantic_score >= 1.0:
        return "VOICE_SEMANTIC_DISTRESS"

    events = {str(item).upper() for item in (voice.get("acousticEvents") or [])}
    if (
        voice.get("ready")
        and role == "STRONG_ACOUSTIC"
        and distress_score >= 0.60
        and events.intersection({"GUNSHOT", "GLASS_BREAK"})
    ):
        return "VOICE_GUNSHOT" if "GUNSHOT" in events else "VOICE_GLASS_BREAK"

    return None


def _location_risk(payload: dict[str, Any]) -> float:
    location = payload.get("location") or {}
    if not location.get("ready") or location.get("featureExtractionParityValidated") is not True:
        return 0.0
    values = [
        location.get("qualityRisk"),
        location.get("abnormalMovementRisk"),
        location.get("gpsQualityFrozenRisk"),
        location.get("routeBehaviorRisk"),
        location.get("trajectoryContextRisk"),
        0.45 if location.get("dwellEvidence") else 0.0,
    ]
    return max((_clamp01(value) for value in values), default=0.0)


async def _external_context(base_score: float, location: dict[str, Any] | None) -> tuple[float, dict[str, Any]]:
    """Fetch existing SACHET/Weather/TomTom signals and apply bounded modifiers.

    No synthetic/fake signal is generated. Missing keys/upstream failures simply
    produce an empty context envelope and leave the score unchanged.
    """
    if not location or location.get("lat") is None or location.get("lng") is None:
        return base_score, {
            "checked": False,
            "reason": "no_location_fix",
            "providers": [],
            "max_effective_risk": 0.0,
            "confidence_before": round(base_score, 4),
            "confidence_after": round(base_score, 4),
        }

    try:
        lat = float(location["lat"])
        lng = float(location["lng"])
    except (TypeError, ValueError):
        return base_score, {
            "checked": False,
            "reason": "invalid_location_fix",
            "providers": [],
            "max_effective_risk": 0.0,
            "confidence_before": round(base_score, 4),
            "confidence_after": round(base_score, 4),
        }

    try:
        from app.services.external_signals.registry import fetch_all_signals
        from app.services.external_signals.modifier import apply_external_modifiers

        signals = await fetch_all_signals(lat, lng)
        relevant = [
            signal for signal in signals
            if str(getattr(signal, "provider", "")).lower() in _RELEVANT_EXTERNAL_PROVIDERS
        ]
        adjusted, audit = apply_external_modifiers(base_score, relevant)
        providers = []
        max_effective = 0.0
        for row in audit.get("providers", []):
            provider = str(row.get("provider") or "").lower()
            if provider in _RELEVANT_EXTERNAL_PROVIDERS:
                providers.append(provider)
                max_effective = max(max_effective, _clamp01(row.get("effective")))
        return _clamp01(adjusted), {
            "checked": True,
            "providers": sorted(set(providers)),
            "max_effective_risk": round(max_effective, 4),
            "audit": audit,
            "lat": lat,
            "lng": lng,
        }
    except Exception as exc:  # fail-quiet; external provider failure never breaks AI safety flow
        logger.warning("[AI_SAFETY] external context unavailable: %r", exc)
        return base_score, {
            "checked": True,
            "providers": [],
            "max_effective_risk": 0.0,
            "provider_error": type(exc).__name__,
            "confidence_before": round(base_score, 4),
            "confidence_after": round(base_score, 4),
        }


def _event_message(anchor: str, reason: str) -> str:
    if reason == "help":
        prefix = "Protected member confirmed they need help after"
    else:
        prefix = "Protected member did not respond to"
    if anchor == "MOTION_HUMAN_FALL":
        return f"{prefix} a NISCHINT AI possible-fall safety check."
    if anchor == "VOICE_GUNSHOT":
        return f"{prefix} a NISCHINT AI possible-gunshot safety check."
    if anchor == "VOICE_GLASS_BREAK":
        return f"{prefix} a NISCHINT AI possible-glass-break safety check."
    if anchor == "VOICE_SEMANTIC_DISTRESS":
        return f"{prefix} a NISCHINT AI spoken-distress safety check."
    if anchor == "LOCATION_EXTERNAL_CONTEXT":
        return f"{prefix} a NISCHINT AI location-and-environment safety check."
    return f"{prefix} a NISCHINT AI safety check."


def _confirmation_payload(
    event_id: str,
    *,
    expires_at: datetime,
    anchor: str | None,
    score: float,
    external_context: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "event_id": event_id,
        "ai_event_id": event_id,
        "eventType": "ai_safety_confirmation",
        "event_type": "ai_safety_confirmation",
        "message": "NISCHINT detected a possible safety concern. Are you safe?",
        "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
        "expires_in_seconds": max(0, int((expires_at - now).total_seconds())),
        "anchor": anchor,
        "score": round(score, 4),
        "external_providers": list(external_context.get("providers") or []),
    }


async def _notify_protected_member_confirmation(
    session: AsyncSession,
    member_id: str,
    confirmation: dict[str, Any],
) -> None:
    """Notify ONLY the protected member. Guardians are not touched here."""
    try:
        from app.services.event_broadcaster import broadcaster
        await broadcaster.broadcast_to_user(member_id, "ai_safety_confirmation", confirmation)
    except Exception as exc:
        logger.warning("[AI_SAFETY] child SSE confirmation failed member=%s: %r", member_id, exc)

    try:
        from app.services.push_service import send_push_to_user
        await asyncio.wait_for(
            send_push_to_user(
                session,
                uuid.UUID(member_id),
                "NISCHINT Safety Check",
                "We detected a possible safety concern. Are you safe?",
                confirmation,
                louder=False,
            ),
            timeout=8.0,
        )
    except Exception as exc:
        logger.warning("[AI_SAFETY] child FCM confirmation failed member=%s: %r", member_id, exc)


async def _load_event_for_member(
    session: AsyncSession,
    event_id: str,
    member_id: str,
    *,
    for_update: bool,
):
    suffix = " FOR UPDATE" if for_update else ""
    result = await session.execute(
        text(
            """
            SELECT id, member_id, client_event_id, observed_at, level, score,
                   adjusted_score, sources, reasons, evidence, location,
                   authoritative_anchor, external_context, status,
                   confirmation_expires_at, response, responded_at,
                   notification_gate_enabled, guardian_alert_dispatched,
                   guardian_alert_id, dispatch_result, created_at, updated_at
              FROM ai_safety_events
             WHERE id = :event_id AND member_id = :member_id
            """ + suffix
        ),
        {"event_id": event_id, "member_id": member_id},
    )
    return result.mappings().first()


async def _dispatch_guardian_for_event(
    session: AsyncSession,
    row: Any,
    *,
    reason: str,
) -> dict[str, Any]:
    event_id = str(row["id"])
    member_id = str(row["member_id"])
    anchor = str(row["authoritative_anchor"] or "AI_SAFETY")
    gate_enabled = guardian_ai_alerts_enabled()

    if not gate_enabled:
        await session.execute(
            text(
                """
                UPDATE ai_safety_events
                   SET status = 'guardian_gate_disabled', response = :response,
                       responded_at = NOW(), updated_at = NOW(),
                       notification_gate_enabled = FALSE
                 WHERE id = :id
                """
            ),
            {"id": event_id, "response": reason},
        )
        await session.commit()
        return {
            "status": "guardian_gate_disabled",
            "event_id": event_id,
            "guardian_alert_dispatched": False,
        }

    sources = row["sources"] if isinstance(row["sources"], list) else []
    external_context = row["external_context"] if isinstance(row["external_context"], dict) else {}
    provider_names = list(external_context.get("providers") or [])
    details = [f"AI evidence anchor: {anchor}"]
    if provider_names:
        details.append("External context: " + ", ".join(provider_names))
    details.append("Protected-member response: NEED HELP" if reason == "help" else "Protected-member response: TIMEOUT")

    from app.services.alert_trigger import trigger_alert
    result = await trigger_alert(
        session,
        kind="ai_safety",
        user_id=member_id,
        severity="critical",
        message=_event_message(anchor, reason),
        details="; ".join(details),
        location=row["location"] if isinstance(row["location"], dict) else None,
        sse_event_type="ai_safety_alert",
        sse_payload_extras={
            "ai_event_id": event_id,
            "client_event_id": row["client_event_id"],
            "ai_anchor": anchor,
            "ai_score": float(row["adjusted_score"] or row["score"] or 0),
            "ai_sources": sources,
            "ai_confirmation_result": reason,
            "ai_external_context_providers": provider_names,
        },
        louder=False,
        idempotency_key=f"ai-confirmed:{event_id}",
        cooldown_s=120,
        persist_alert=True,
        suppress_co_located=False,
    )

    final_status = "escalated_help" if reason == "help" else "escalated_timeout"
    await session.execute(
        text(
            """
            UPDATE ai_safety_events
               SET status = :status, response = :response, responded_at = NOW(),
                   updated_at = NOW(), notification_gate_enabled = TRUE,
                   guardian_alert_dispatched = :dispatched,
                   guardian_alert_id = :alert_id,
                   dispatch_result = CAST(:result AS JSONB)
             WHERE id = :id
            """
        ),
        {
            "id": event_id,
            "status": final_status,
            "response": reason,
            "dispatched": bool(result.dispatched),
            "alert_id": result.alert_id,
            "result": _json(result.to_dict(), {}),
        },
    )
    await session.commit()
    return {
        "status": final_status,
        "event_id": event_id,
        "guardian_alert_dispatched": bool(result.dispatched),
        "dispatch": result.to_dict(),
    }


async def ingest_ai_safety_event(
    session: AsyncSession,
    actor: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist/evaluate one AI candidate; never notify Guardians before confirmation."""
    if not is_protected_member(actor.role):
        raise HTTPException(status_code=403, detail="AI safety events must originate from a protected-member session")

    actor_id = str(actor.id)
    member_id = str(payload.get("protected_member_id") or "")
    if member_id != actor_id:
        raise HTTPException(status_code=403, detail="Protected member mismatch")

    client_event_id = str(payload.get("client_event_id") or "").strip()
    if not client_event_id or len(client_event_id) > 200:
        raise HTTPException(status_code=422, detail="Invalid client_event_id")

    level = str(payload.get("level") or "").lower()
    if level not in {"observe", "elevated", "high"}:
        raise HTTPException(status_code=422, detail="Invalid AI event level")
    score = _clamp01(payload.get("score"))

    try:
        raw_observed_at = str(payload["observed_at"]).strip()
        parsed_observed_at = datetime.fromisoformat(raw_observed_at.replace("Z", "+00:00"))
        if parsed_observed_at.tzinfo is None:
            parsed_observed_at = parsed_observed_at.replace(tzinfo=timezone.utc)
        observed_at = parsed_observed_at.astimezone(timezone.utc)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="observed_at must be an ISO-8601 timestamp") from exc

    sources = [str(item).lower() for item in (payload.get("sources") or []) if str(item).strip()]
    reasons = [str(item)[:500] for item in (payload.get("reasons") or [])][:12]
    location = payload.get("location_fix") if isinstance(payload.get("location_fix"), dict) else None
    location_risk = _location_risk(payload)
    anchor = _authoritative_anchor(payload)

    # Location evidence can become a context candidate only after parity approval.
    # Use its real risk as the backend base; it STILL needs strong external
    # corroboration before it gets an anchor.
    backend_base_score = max(score, location_risk if not anchor else 0.0)
    adjusted_score, external_context = await _external_context(backend_base_score, location)
    if (
        not anchor
        and location_risk >= 0.60
        and _clamp01(external_context.get("max_effective_risk")) >= 0.60
    ):
        anchor = "LOCATION_EXTERNAL_CONTEXT"

    actionable = bool(anchor and adjusted_score >= 0.70)
    status = "pending_confirmation" if actionable else "stored_not_actionable"
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=confirmation_timeout_seconds())
        if actionable else None
    )
    gate_enabled = guardian_ai_alerts_enabled()

    evidence = {
        "motion": payload.get("motion"),
        "voice": payload.get("voice"),
        "location": payload.get("location"),
        "candidate_event_kind": payload.get("candidate_event_kind"),
        "candidate_event_eligible": bool(payload.get("candidate_event_eligible")),
        "backend_context_required": bool(payload.get("backend_context_required")),
        "confirmation_gate_required": True,
        "location_risk": round(location_risk, 4),
    }

    await ensure_ai_safety_event_table()
    event_id = str(uuid.uuid4())
    inserted = await session.execute(
        text(
            """
            INSERT INTO ai_safety_events
                (id, member_id, client_event_id, observed_at, level, score,
                 adjusted_score, sources, reasons, evidence, location,
                 authoritative_anchor, external_context, status,
                 confirmation_expires_at, notification_gate_enabled)
            VALUES
                (:id, :member_id, :client_event_id, CAST(:observed_at AS TIMESTAMPTZ),
                 :level, :score, :adjusted_score, CAST(:sources AS JSONB),
                 CAST(:reasons AS JSONB), CAST(:evidence AS JSONB), CAST(:location AS JSONB),
                 :anchor, CAST(:external_context AS JSONB), :status,
                 :confirmation_expires_at, :gate)
            ON CONFLICT (member_id, client_event_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "id": event_id,
            "member_id": actor_id,
            "client_event_id": client_event_id,
            "observed_at": observed_at,
            "level": level,
            "score": score,
            "adjusted_score": adjusted_score,
            "sources": _json(sources, []),
            "reasons": _json(reasons, []),
            "evidence": _json(evidence, {}),
            "location": _json(location, None),
            "anchor": anchor,
            "external_context": _json(external_context, {}),
            "status": status,
            "confirmation_expires_at": expires_at,
            "gate": gate_enabled,
        },
    )
    row = inserted.first()
    await session.commit()

    if not row:
        existing = await session.execute(
            text(
                """
                SELECT id, status, authoritative_anchor, adjusted_score,
                       confirmation_expires_at, external_context,
                       guardian_alert_dispatched
                  FROM ai_safety_events
                 WHERE member_id = :member_id AND client_event_id = :client_event_id
                """
            ),
            {"member_id": actor_id, "client_event_id": client_event_id},
        )
        current = existing.mappings().first()
        if current and current["status"] == "pending_confirmation" and current["confirmation_expires_at"]:
            confirmation = _confirmation_payload(
                str(current["id"]),
                expires_at=current["confirmation_expires_at"],
                anchor=current["authoritative_anchor"],
                score=float(current["adjusted_score"] or 0),
                external_context=current["external_context"] if isinstance(current["external_context"], dict) else {},
            )
            return {"status": "confirmation_required", "duplicate": True, "confirmation": confirmation}
        return {
            "status": str(current["status"] if current else "duplicate_accepted"),
            "duplicate": True,
            "guardian_alert_dispatched": bool(current["guardian_alert_dispatched"] if current else False),
        }

    if not actionable or expires_at is None:
        return {
            "status": "stored_not_actionable",
            "event_id": event_id,
            "client_event_id": client_event_id,
            "authoritative_anchor": anchor,
            "score": score,
            "adjusted_score": adjusted_score,
            "external_context": external_context,
            "guardian_alert_dispatched": False,
            "confirmation_required": False,
        }

    confirmation = _confirmation_payload(
        event_id,
        expires_at=expires_at,
        anchor=anchor,
        score=adjusted_score,
        external_context=external_context,
    )
    # Commit happened before transport. A push failure cannot erase the pending
    # confirmation; the protected app can recover it from /pending.
    await _notify_protected_member_confirmation(session, actor_id, confirmation)
    return {
        "status": "confirmation_required",
        "event_id": event_id,
        "client_event_id": client_event_id,
        "authoritative_anchor": anchor,
        "score": score,
        "adjusted_score": adjusted_score,
        "external_context": external_context,
        "guardian_alert_dispatched": False,
        "confirmation_required": True,
        "confirmation": confirmation,
    }


async def get_pending_ai_safety_confirmation(
    session: AsyncSession,
    actor: User,
) -> dict[str, Any]:
    if not is_protected_member(actor.role):
        raise HTTPException(status_code=403, detail="Only a protected member can read their AI safety confirmation")
    await ensure_ai_safety_event_table()
    result = await session.execute(
        text(
            """
            SELECT id, member_id, authoritative_anchor, adjusted_score,
                   external_context, confirmation_expires_at, status
              FROM ai_safety_events
             WHERE member_id = :member_id AND status = 'pending_confirmation'
             ORDER BY created_at DESC
             LIMIT 1
            """
        ),
        {"member_id": str(actor.id)},
    )
    row = result.mappings().first()
    if not row:
        return {"status": "none", "confirmation": None}
    expires_at = row["confirmation_expires_at"]
    if not expires_at:
        return {"status": "none", "confirmation": None}
    if expires_at <= datetime.now(timezone.utc):
        locked = await _load_event_for_member(session, str(row["id"]), str(actor.id), for_update=True)
        if locked and locked["status"] == "pending_confirmation":
            await _dispatch_guardian_for_event(session, locked, reason="timeout")
        return {"status": "expired", "confirmation": None}
    confirmation = _confirmation_payload(
        str(row["id"]),
        expires_at=expires_at,
        anchor=row["authoritative_anchor"],
        score=float(row["adjusted_score"] or 0),
        external_context=row["external_context"] if isinstance(row["external_context"], dict) else {},
    )
    return {"status": "pending", "confirmation": confirmation}


async def respond_to_ai_safety_confirmation(
    session: AsyncSession,
    actor: User,
    event_id: str,
    response: str,
) -> dict[str, Any]:
    if not is_protected_member(actor.role):
        raise HTTPException(status_code=403, detail="Only the protected member can answer their AI safety confirmation")
    response = str(response or "").strip().lower()
    if response not in {"safe", "help"}:
        raise HTTPException(status_code=400, detail="Response must be 'safe' or 'help'")
    await ensure_ai_safety_event_table()

    row = await _load_event_for_member(session, event_id, str(actor.id), for_update=True)
    if not row:
        raise HTTPException(status_code=404, detail="AI safety event not found")
    if row["status"] != "pending_confirmation":
        return {
            "status": str(row["status"]),
            "event_id": event_id,
            "guardian_alert_dispatched": bool(row["guardian_alert_dispatched"]),
        }

    expires_at = row["confirmation_expires_at"]
    if expires_at and expires_at <= datetime.now(timezone.utc):
        return await _dispatch_guardian_for_event(session, row, reason="timeout")

    if response == "safe":
        await session.execute(
            text(
                """
                UPDATE ai_safety_events
                   SET status = 'resolved_safe', response = 'safe', responded_at = NOW(),
                       updated_at = NOW(), guardian_alert_dispatched = FALSE
                 WHERE id = :id
                """
            ),
            {"id": event_id},
        )
        await session.commit()
        return {
            "status": "resolved_safe",
            "event_id": event_id,
            "guardian_alert_dispatched": False,
        }

    return await _dispatch_guardian_for_event(session, row, reason="help")


async def expire_stale_ai_safety_confirmations(limit: int = 20) -> int:
    """Scheduler hook: unanswered high-confidence AI checks notify Guardians once."""
    await ensure_ai_safety_event_table()
    from app.db.session import async_session

    escalated = 0
    for _ in range(max(1, min(100, int(limit)))):
        async with async_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, member_id, client_event_id, observed_at, level, score,
                           adjusted_score, sources, reasons, evidence, location,
                           authoritative_anchor, external_context, status,
                           confirmation_expires_at, response, responded_at,
                           notification_gate_enabled, guardian_alert_dispatched,
                           guardian_alert_id, dispatch_result, created_at, updated_at
                      FROM ai_safety_events
                     WHERE status = 'pending_confirmation'
                       AND confirmation_expires_at IS NOT NULL
                       AND confirmation_expires_at <= NOW()
                     ORDER BY confirmation_expires_at ASC
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                    """
                )
            )
            row = result.mappings().first()
            if not row:
                break
            outcome = await _dispatch_guardian_for_event(session, row, reason="timeout")
            if outcome.get("guardian_alert_dispatched"):
                escalated += 1
    return escalated
