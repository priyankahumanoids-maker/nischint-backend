"""Unified Alert Trigger — the single front door for guardian-facing alerts.

Background: an audit (`/app/memory/SPIKE_NISCH-001_TRIGGER.md`) found that
50+ services call `broadcast_to_user`, 8 services create `GuardianAlert`
rows directly, and 11 services call `send_push_to_user` directly — each
with subtly different dedup, formatting, and instrumentation.

This module is the unified surface. All new alert producers MUST route
through `trigger_alert(...)`. Existing producers migrate one at a time
behind feature flags.

Pipeline (in order):
    1.  Resolve `guardian_ids` from BOTH `Guardian` (contact-based) and
        `Relationship` (code-based linking) tables.
    2.  Redis-backed dedup gate (cooldown per `kind` + `idempotency_key`).
    3.  Create one `GuardianAlert` row (NEVER NULL `user_id`).
    4.  Fan out SSE `event_type` to every linked guardian via the
        existing `event_broadcaster`.
    5.  Push + SMS via the existing `guardian_notification_dispatcher`
        (which respects per-guardian preferences, SMS rate-limit, and
        DND-bypass on critical alerts).
    6.  Stamp `[ALERT_TTFA]` log line — single source of truth for the
        TTFA p95 KRA (NISCH-003).

Non-negotiables:
- `user_id` is the child / wearer / monitored user. Never `None`.
- SSE broadcast and DB write are best-effort independent — if the DB
  write fails, the SSE has already been delivered (better one redundant
  delivery than a missed alert).
- The Redis dedup gate is OPT-IN per call: pass `idempotency_key=None`
  to bypass dedup. Default `cooldown_s=30`.
- This function does NOT replace `risk_emitter.maybe_emit_risk_update`.
  `risk_update` is a score-delta event — no GuardianAlert row, no push,
  no SMS. They share the *pattern* (Redis dedup), not the *code*.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import Guardian, GuardianAlert, GuardianSession
from app.models.relationship import Relationship
from app.models.user import User
from app.core.product_roles import is_co_guardian, is_protected_member
from app.services import redis_service, ttfa_recorder
from app.services.alert_formatter import format_alert
from app.services.alert_proximity import is_co_located, is_suppressible_kind
from app.services.event_broadcaster import broadcaster
from app.services.event_dedup import should_emit as _dedup_should_emit, reset_local as _dedup_reset_local

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────
_DEFAULT_COOLDOWN_S = 30


# ── Result type ─────────────────────────────────────────────────────
@dataclass
class TriggerResult:
    dispatched: bool
    alert_id: Optional[str]
    guardians_notified: int
    dedup_skipped: bool
    reason: Optional[str]
    ttfa_ms: int
    escalation_status: str = "unknown"   # "ok" | "failed" | "skipped" | "unknown"

    def to_dict(self) -> dict:
        return {
            "dispatched":         self.dispatched,
            "alert_id":           self.alert_id,
            "guardians_notified": self.guardians_notified,
            "dedup_skipped":      self.dedup_skipped,
            "reason":             self.reason,
            "ttfa_ms":            self.ttfa_ms,
            "escalation_status":  self.escalation_status,
        }


# ── Dedup gate (delegated to NISCH-005 generic helper) ──────────────
def _dedup_key(kind: str, user_id: str, idempotency_key: str) -> str:
    """Compose the cross-emitter key used for dedup lookups.

    Kept as a thin helper so test_alert_trigger can still address the
    same key the production path uses.
    """
    return f"{user_id}:{idempotency_key}"


def _dedup_should_skip(kind: str, user_id: str, idempotency_key: Optional[str], cooldown_s: int) -> bool:
    """Return True if we should SUPPRESS this trigger (recent duplicate).

    Wraps the generic `event_dedup.should_emit` so the alert path keeps
    its "skip" semantics while the rest of the system uses the positive
    "should emit" form.
    """
    if not idempotency_key or cooldown_s <= 0:
        return False
    composed = _dedup_key(kind, user_id, idempotency_key)
    return not _dedup_should_emit(kind, composed, cooldown_s=cooldown_s)


def reset_dedup_state(kind: Optional[str] = None, user_id: Optional[str] = None) -> None:
    """Test-only helper. Clears local dedup state. Does NOT scan Redis."""
    if kind is None and user_id is None:
        _dedup_reset_local()
        return
    # The composed local key starts with `<kind>:<user_id>:`
    _dedup_reset_local(kind=kind, key=user_id)


# ── Guardian resolution (single source of truth) ────────────────────
async def _resolve_guardian_ids(session: AsyncSession, child_user_id: str) -> tuple[list[str], Optional[str]]:
    """Resolve every guardian for a child by walking BOTH the
    `Guardian` (contact-based) table AND the `Relationship` (code-based
    link) table, deduping. Returns `(guardian_ids, child_name)`.

    Inlined from voice_distress_service + guardian_mode_engine (which had
    near-identical implementations) so the unified door has its own copy
    and the legacy paths can be deleted as they migrate.
    """
    try:
        cu_uuid = uuid.UUID(child_user_id)
    except (ValueError, AttributeError):
        return [], None

    # Child's display name
    child_user = (await session.execute(select(User).where(User.id == cu_uuid))).scalar_one_or_none()
    child_name = child_user.full_name if (child_user and child_user.full_name) else None

    seen: set[str] = set()
    out: list[str] = []

    # Path 1: Guardian (contact) table — contacts may have an email that
    # maps to an actual User account; if so, that User is a guardian.
    g_rows = (await session.execute(
        select(Guardian).where(
            Guardian.user_id == cu_uuid,
            Guardian.is_active.is_(True),
        )
    )).scalars().all()
    for gc in g_rows:
        if gc.email:
            gu = (await session.execute(select(User).where(User.email == gc.email))).scalar_one_or_none()
            if gu and str(gu.id) not in seen:
                seen.add(str(gu.id))
                out.append(str(gu.id))

    # Path 2: Relationship table — code-based linking (the new primary path).
    rels = (await session.execute(
        select(Relationship).where(
            Relationship.child_id == cu_uuid,
            Relationship.status == "accepted",
        )
    )).scalars().all()
    for r in rels:
        gid = str(r.guardian_id)
        if gid not in seen:
            seen.add(gid)
            out.append(gid)

    # Path 3: Guardian Network relationships (QR/link-based co-guardians).
    try:
        from app.models.guardian_network import GuardianRelationship
        network_rels = (await session.execute(
            select(GuardianRelationship).where(
                GuardianRelationship.user_id == cu_uuid,
                GuardianRelationship.guardian_user_id.isnot(None),
                GuardianRelationship.is_active.is_(True),
            )
        )).scalars().all()
        for rel in network_rels:
            gid = str(rel.guardian_user_id)
            if gid not in seen:
                seen.add(gid)
                out.append(gid)
    except Exception as exc:
        logger.warning(
            "[ALERT_TRIGGER] guardian-network resolution failed child=%s: %s",
            child_user_id,
            exc,
        )

    # Path 4: Direct parent link on User record (User.guardian_id).
    if child_user and child_user.guardian_id:
        primary_guardian_id = child_user.guardian_id
        gid = str(primary_guardian_id)
        if gid not in seen:
            seen.add(gid)
            out.append(gid)

        # A co-parent created through the current Family Circle invite is
        # represented as users.guardian_id -> the same primary guardian.
        # Dashboard monitoring already inherits that primary family scope.
        # Keep alert delivery consistent with the same family model, but only
        # for real protected-member events — never when resolving a guardian
        # account itself.
        if is_protected_member(child_user.role):
            co_parent_rows = (
                await session.execute(
                    select(User).where(
                        User.guardian_id == primary_guardian_id,
                        User.is_active.is_(True),
                    )
                )
            ).scalars().all()
            for candidate in co_parent_rows:
                if not is_co_guardian(candidate.role):
                    continue
                co_parent_id = str(candidate.id)
                if co_parent_id not in seen:
                    seen.add(co_parent_id)
                    out.append(co_parent_id)

    return out, child_name


# ── Public entry point ──────────────────────────────────────────────
async def trigger_alert(
    session: AsyncSession,
    *,
    kind: str,
    user_id: str,
    severity: str,
    message: str,
    details: Optional[str] = None,
    location: Optional[dict] = None,
    session_id: Optional[str] = None,
    sse_event_type: str = "safety_alert",
    sse_payload_extras: Optional[dict] = None,
    louder: bool = False,
    idempotency_key: Optional[str] = None,
    cooldown_s: int = _DEFAULT_COOLDOWN_S,
    persist_alert: bool = True,
    suppress_co_located: bool = True,
) -> TriggerResult:
    """Single front door for every guardian-facing alert.

    Args:
        kind:               event family — e.g. "voice_distress",
                            "geofence_breach", "sos", "fall", "wandering".
                            Used for dedup keying + dispatch routing.
        user_id:            the child / wearer / monitored user (NEVER None).
        severity:           "info" | "warning" | "critical".
        message:            human-readable line shown to guardian.
        details:            longer free-text. Optional.
        location:           {"lat": float, "lng": float} or None.
        session_id:         link to GuardianSession when applicable.
                            Stored on the alert; nullable since
                            session-less alerts (e.g. SOS without active
                            journey) are valid.
        sse_event_type:     SSE event name. Defaults to "safety_alert"
                            but callers may keep their existing names
                            ("voice_alert", "emergency_triggered", ...)
                            during incremental migration so frontends
                            don't break.
        sse_payload_extras: additional fields merged into the SSE body
                            beyond the standard alert envelope.
        louder:             escalates the push to the critical_safety
                            channel (siren_loop sound, DND bypass).
        idempotency_key:    if set, suppresses duplicate triggers within
                            `cooldown_s`. Pass None to disable dedup.
        cooldown_s:         dedup window in seconds. Default 30.
        persist_alert:      set False for transient signals that should
                            NOT create a GuardianAlert row (e.g. info-
                            level "child arrived safely"). Default True.
        suppress_co_located: when True (default), guardians demonstrably
                            within 150m of the child get filtered out
                            of SSE fan-out for non-critical kinds. NEVER
                            applies to life-safety kinds (sos, voice
                            distress, fall, help_requested) — those
                            kinds are not in `SUPPRESSIBLE_KINDS`.

    Returns: TriggerResult — see dataclass.
    """
    t0 = time.monotonic()
    user_id = str(user_id)

    # 1. Dedup gate
    if _dedup_should_skip(kind, user_id, idempotency_key, cooldown_s):
        ttfa_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            f"[ALERT_TRIGGER] kind={kind} user={user_id} idem={idempotency_key} "
            f"DEDUP_SKIPPED ttfa_ms={ttfa_ms}"
        )
        return TriggerResult(
            dispatched=False, alert_id=None, guardians_notified=0,
            dedup_skipped=True, reason="dedup_cooldown", ttfa_ms=ttfa_ms,
        )

    # 2. Resolve guardians + child name
    guardian_ids, child_name = await _resolve_guardian_ids(session, user_id)

    # 2a. NISCH-006 — open SafetyIncident in DETECTED state. Best-effort:
    #     a failure here MUST NOT block alert delivery.
    #     Skipped for transient signals (`persist_alert=False`) — those
    #     don't carry a lifecycle either; they're info pings.
    #
    #     NISCH-012.0 — `location` is forwarded so the engine can run
    #     the external-signal modifier (weather risk → confidence bump,
    #     additive cap +0.20). The engine fail-quiets internally with
    #     a hard 1.5s timeout per provider, so this stays inside the
    #     alert hot-path budget.
    incident = None
    if persist_alert:
        from app.services import safety_incident_engine as _sie
        incident = await _sie.open_incident_for_alert(
            session,
            child_id=user_id,
            kind=kind,
            severity=severity,
            location=location,
        )

    # 2b. Format canonical envelope (NISCH-004) — single source of truth for
    #     title/body/priority/sound/channels. Pure function, no I/O.
    envelope = format_alert(kind, {
        "child_name": child_name,
        "severity":   severity,
        "message":    message,
        "location":   location,
    })
    # Honor envelope's `louder` unless caller explicitly overrode it.
    effective_louder = bool(louder or envelope.get("louder"))

    # 3. Persist GuardianAlert row (best-effort — never blocks delivery)
    alert_obj: Optional[GuardianAlert] = None
    alert_id: Optional[str] = None
    if persist_alert:
        try:
            ses_uuid: Optional[uuid.UUID] = None
            if session_id:
                try:
                    ses_uuid = uuid.UUID(str(session_id))
                except (ValueError, TypeError):
                    ses_uuid = None
            alert_obj = GuardianAlert(
                session_id=ses_uuid,
                user_id=uuid.UUID(user_id),
                alert_type=kind,
                severity=severity,
                message=message,
                details=details,
                location=location,
            )
            session.add(alert_obj)
            await session.flush()
            alert_id = str(alert_obj.id)
            # NISCH-006: backfill the linkage on the incident so ACK
            # path can find it via `extra->>'alert_id'`.
            if incident is not None and alert_id is not None:
                try:
                    extra = dict(incident.extra or {})
                    extra["alert_id"] = alert_id
                    incident.extra = extra
                    await session.flush()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[ALERT_TRIGGER] persist failed kind={kind} user={user_id}: {e}")
            # Continue — SSE delivery is more important than the row.

    # NISCH-006: DETECTED → VALIDATING — dedup gate passed, alert is real.
    if incident is not None:
        from app.services import safety_incident_engine as _sie
        await _sie.advance_to_validating(session, incident)

    # 4. SSE fan-out
    sse_body = {
        "type":        kind.upper(),
        "alert_id":    alert_id,
        "child_id":    user_id,
        "child_name":  child_name or "Unknown",
        "severity":    severity,
        "message":     message,
        "details":     details,
        "location":    location,
        "session_id":  session_id,
        "louder":      effective_louder,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "envelope":    envelope,  # NISCH-004 canonical render contract
        **(sse_payload_extras or {}),
    }

    # 4a. Co-location suppression (NISCH-002B) — for non-critical kinds only,
    #     skip guardians who are demonstrably standing next to the child.
    #     Fail-safe: any uncertainty → notify.
    suppressed_gids: set[str] = set()
    if (
        suppress_co_located
        and is_suppressible_kind(kind)
        and location and location.get("lat") is not None and location.get("lng") is not None
    ):
        try:
            child_lat = float(location["lat"])
            child_lng = float(location["lng"])
            guardian_users = (await session.execute(
                select(User).where(User.id.in_([uuid.UUID(g) for g in guardian_ids]))
            )).scalars().all() if guardian_ids else []
            for gu in guardian_users:
                if is_co_located(
                    guardian_lat=gu.last_known_lat,
                    guardian_lng=gu.last_known_lng,
                    guardian_last_at=gu.last_known_at,
                    child_lat=child_lat,
                    child_lng=child_lng,
                ):
                    suppressed_gids.add(str(gu.id))
            if suppressed_gids:
                logger.info(
                    f"[ALERT_TRIGGER] co-located suppression kind={kind} "
                    f"suppressed={len(suppressed_gids)}/{len(guardian_ids)}"
                )
        except Exception as e:
            # Fail-safe: anything goes wrong → suppress nothing.
            logger.warning(f"[ALERT_TRIGGER] proximity check failed; notifying everyone: {e}")
            suppressed_gids.clear()

    notified = 0
    for gid in guardian_ids:
        if gid in suppressed_gids:
            continue
        try:
            await broadcaster.broadcast_to_user(gid, sse_event_type, sse_body)
            notified += 1
        except Exception as e:
            logger.warning(f"[ALERT_TRIGGER] sse fan-out failed gid={gid}: {e}")

    # 5. Push + SMS via the existing dispatcher (handles preferences,
    #    rate-limit, channel selection). Skipped when no row was
    #    persisted because the dispatcher signature requires an alert.
    escalation_status = "skipped"
    if alert_obj is not None and guardian_ids:
        try:
            from app.services.guardian_notification_dispatcher import dispatch_guardian_alert
            await dispatch_guardian_alert(
                session, alert_obj, user_id, session_id or "",
                louder=effective_louder,
                guardian_user_ids=guardian_ids,
            )
            escalation_status = "ok"
        except Exception as e:
            escalation_status = "failed"
            logger.error(f"[ALERT_TRIGGER] push/sms dispatch failed: {e}")
            # Fail-safe: SSE has already gone out (step 4). Twilio failure
            # MUST NOT silence the alert. We log + flag, never re-raise.

    # 5b. NISCH-006: VALIDATING → ESCALATED — dispatch has been attempted.
    #     Even if push/SMS failed, SSE has already gone out (step 4); the
    #     incident IS escalated from the system's perspective.
    if incident is not None:
        from app.services import safety_incident_engine as _sie
        await _sie.advance_to_escalated(session, incident)

    # 6. TTFA log — single line per dispatch, drives the NISCH-003 stats endpoint.
    ttfa_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        f"[ALERT_TTFA] kind={kind} user={user_id} severity={severity} "
        f"guardians={notified}/{len(guardian_ids)} alert_id={alert_id} "
        f"louder={effective_louder} priority={envelope.get('priority')} "
        f"ttfa_ms={ttfa_ms}"
    )
    ttfa_recorder.record(
        kind=kind,
        ttfa_ms=ttfa_ms,
        guardians=notified,
        louder=effective_louder,
        priority=envelope.get("priority"),
    )

    # ── ALERT_TRIGGER_V2 shadow hook (fire-and-forget) ─────────────
    # V2 is observation-only today: it computes the dispatch plan it
    # *would* execute and diffs against V1. Result + diff land in
    # Redis (counters + capped event log) for offline analysis.
    # Wrapped in `create_task` so V1 latency is unaffected.
    try:
        import asyncio as _asyncio
        notified_gids = [
            g for g in guardian_ids if g not in suppressed_gids
        ]
        _asyncio.create_task(_run_v2_shadow_safe(
            kind=kind,
            user_id=user_id,
            guardian_ids_resolved=guardian_ids,
            v1_dispatched=True,
            v1_guardian_ids_notified=notified_gids,
            alert_id=alert_id,
        ))
    except Exception as e:  # noqa: BLE001
        # No event loop / shutdown in progress — log and move on.
        logger.warning("[ALERT_TRIGGER] V2 shadow schedule failed: %r", e)

    return TriggerResult(
        dispatched=True,
        alert_id=alert_id,
        guardians_notified=notified,
        dedup_skipped=False,
        reason=None,
        ttfa_ms=ttfa_ms,
        escalation_status=escalation_status,
    )


async def _run_v2_shadow_safe(
    *,
    kind: str,
    user_id: str,
    guardian_ids_resolved: list[str],
    v1_dispatched: bool,
    v1_guardian_ids_notified: list[str],
    alert_id: Optional[str],
) -> None:
    """Fire-and-forget V2 shadow comparison. Opens its own DB session
    so V1's session lifecycle is not coupled to V2 latency.

    Hot-path invariant: this coroutine MUST NOT raise. Any failure is
    logged and swallowed so V1 reads back a clean dispatch result."""
    try:
        from app.services.alert_trigger_v2 import classify_kind
        if classify_kind(kind) == "not_in_scope_v2":
            return
        from app.db.session import async_session
        from app.services import alert_trigger_v2_shadow as _v2s
        async with async_session() as session:
            await _v2s.run_shadow_compare(
                session,
                kind=kind,
                user_id=user_id,
                guardian_ids_resolved=guardian_ids_resolved,
                v1_dispatched=v1_dispatched,
                v1_guardian_ids_notified=v1_guardian_ids_notified,
                alert_id=alert_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[ALERT_TRIGGER] V2 shadow hook failed: %r", e)


__all__ = ["trigger_alert", "TriggerResult", "reset_dedup_state"]
