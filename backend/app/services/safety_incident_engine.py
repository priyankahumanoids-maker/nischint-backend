"""NISCH-006 — SafetyIncident lifecycle integration helpers.

Single source of truth for *creating* and *linking* SafetyIncident rows
from the alert pipeline. State transitions still go through
`incident_state_machine.transition` — this module just owns the
"create incident on alert dispatch / find incident on alert ack" wiring
so callers (`alert_trigger`, `alert_ack_engine`) don't have to know
about the state machine internals.

Strict design:
  * Every call here is best-effort — if anything fails, the alert
    pipeline must still deliver. Exceptions are caught and logged at
    WARNING; they never propagate.
  * SLA fetch is non-blocking. Per CEO-mode review: an SLA monitor
    failure must NOT block incident creation. Default to
    `sla_degraded_at_dispatch=False` on any failure.
  * Linkage between SafetyIncident and GuardianAlert is stored in
    `safety_incidents.extra->>'alert_id'`. ACK lookup uses a JSONB
    `@>` query so it works without a dedicated FK.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety_incident import SafetyIncident
from app.services.incident_state_machine import (
    IncidentState,
    InvalidTransitionError,
    transition,
)

logger = logging.getLogger(__name__)


def _safe_sla_snapshot() -> tuple[Optional[uuid.UUID], bool]:
    """Read the live SLA verdict without blocking the dispatch path.

    Returns (sla_incident_id, degraded). Both default safely on any
    failure — an SLA monitor outage MUST NOT prevent incident
    creation. We currently only have the boolean state in the in-memory
    `sla_monitor._last_status`; a future SlaIncidentTracker that issues
    UUIDs can be plugged in here without touching callers.
    """
    try:
        from app.services import sla_monitor
        status = (sla_monitor._last_status or "unknown").lower()
        return None, status in ("amber", "red")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[SAFETY_INCIDENT] SLA snapshot failed (non-fatal): {e}")
        return None, False


async def open_incident_for_alert(
    session: AsyncSession,
    *,
    child_id: str,
    kind: str,
    severity: str,
    alert_id: Optional[str] = None,
    confidence: float = 1.0,
    extra: Optional[dict[str, Any]] = None,
    location: Optional[dict[str, float]] = None,
) -> Optional[SafetyIncident]:
    """Create a SafetyIncident in DETECTED state for an inbound alert.

    Args:
        location: optional {"lat": float, "lng": float}. When present,
            triggers the NISCH-012.0 external-signal modifier path —
            confidence may be bumped (capped at +0.20) based on weather
            (and future Sachet/traffic) at the incident's location.
            The original `confidence` is preserved on
            `confidence_pre_external` for forensic explainability.

    Returns the persisted incident, or None on any failure — callers
    must treat the return value as advisory, never required.
    """
    try:
        try:
            cu = uuid.UUID(str(child_id))
        except (ValueError, TypeError):
            return None

        sla_id, sla_degraded = _safe_sla_snapshot()
        meta: dict[str, Any] = {"alert_id": alert_id} if alert_id else {}
        if extra:
            meta.update(extra)

        # NISCH-012.0 — external signal modifier. Fail-quiet,
        # bounded by the registry's hard PROVIDER_TIMEOUT_S budget so
        # the alert hot-path stays under ~1.6s even with all
        # providers timing out concurrently.
        base_confidence = float(confidence)
        modified_confidence = base_confidence
        external_audit: Optional[dict] = None
        if location and location.get("lat") is not None and location.get("lng") is not None:
            try:
                from app.services.external_signals.registry import (
                    fetch_all_signals,
                )
                from app.services.external_signals.modifier import (
                    apply_external_modifiers,
                )
                signals = await fetch_all_signals(
                    float(location["lat"]), float(location["lng"]),
                )
                if signals:
                    modified_confidence, external_audit = apply_external_modifiers(
                        base_confidence, signals,
                    )
                    if external_audit.get("modifier_applied", 0.0) <= 0:
                        # No actual bump applied (all sub-threshold or
                        # stale) — drop the audit envelope to avoid
                        # cluttering the timeline with a no-op row.
                        external_audit = None
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[SAFETY_INCIDENT] external signal lookup failed "
                    f"(non-fatal): {e!r}"
                )

        # NISCH-010 — predictive-risk modifier. Same fail-quiet
        # discipline as external signals above: never block the
        # alert hot-path, never raise. When the 15-min forecast
        # exceeds 0.7 risk, bump the confidence by 0.05 and stamp
        # the audit envelope so the operator can see WHY the
        # alert escalated.
        if location and location.get("lat") is not None and location.get("lng") is not None:
            try:
                from app.services.risk_prediction.predictor import predict as _predict
                import uuid as _uuid
                pred = await _predict(
                    session,
                    subject_id=_uuid.uuid5(
                        _uuid.NAMESPACE_DNS,
                        f"latlng:{float(location['lat']):.4f},"
                        f"{float(location['lng']):.4f}",
                    ),
                    subject_type="zone",
                    zone_id=None,
                    prediction_window_min=15,
                    persist=False,                # don't pollute ledger from alert path
                )
                if (
                    pred.get("status") == "ok"
                    and float(pred.get("risk_probability") or 0.0) > 0.7
                ):
                    predictive_audit = {
                        "probability": pred["risk_probability"],
                        "window_min":  15,
                        "volatility":  pred.get("zone_volatility", 0.0),
                        "factors":     pred.get("contributing_factors", []),
                        "model_version": pred.get("model_version"),
                    }
                    modified_confidence = min(0.99, modified_confidence + 0.05)
                    if external_audit is None:
                        external_audit = {}
                    external_audit["predictive_risk"] = predictive_audit
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[SAFETY_INCIDENT] predictive risk lookup failed "
                    f"(non-fatal): {e!r}"
                )

        # NISCH-011 — behavioural anomaly observation. SAME non-blocking
        # discipline. Locked rule: ONLY `critical_behavioral_shift` with
        # corroborating zone risk influences dispatch — every other
        # taxonomy class is observational. The detector handles its own
        # ledger persistence + DLQ fallback; this block just sources
        # an observation, fuses, and stamps the audit envelope.
        if location and location.get("lat") is not None and location.get("lng") is not None:
            try:
                from app.services.behavioral.detector import assess_and_record
                observation = {
                    "speed_mps": float(location.get("speed_mps", 0.0) or 0.0),
                    "dwell_s":   float(location.get("dwell_s",   0.0) or 0.0),
                    "anomaly_type": kind or "behavioural_deviation",
                }
                # Pull the zone risk from predictive_audit (if present),
                # else from the modified confidence — best available
                # signal without re-running the predictor.
                zone_risk = 0.0
                if external_audit and isinstance(
                    external_audit.get("predictive_risk"), dict,
                ):
                    zone_risk = float(
                        external_audit["predictive_risk"].get("probability") or 0.0,
                    )
                behavioral = await assess_and_record(
                    session,
                    entity_id=cu,
                    observation=observation,
                    zone_risk=zone_risk,
                )
                if behavioral.get("status") in {"ok", "dlq_fallback"} \
                        and behavioral.get("dispatch_influence"):
                    # Critical shift AND corroborating zone risk —
                    # only path that's permitted to bump dispatch
                    # confidence (capped at 0.99).
                    modified_confidence = min(
                        0.99, modified_confidence + 0.03,
                    )
                    if external_audit is None:
                        external_audit = {}
                    external_audit["behavioral_anomaly"] = {
                        "deviation_class": behavioral["deviation_class"],
                        "anomaly_score":   behavioral["anomaly_score"],
                        "fused_risk":      behavioral["fused_risk"],
                        "forecast_divergence_index":
                            behavioral.get("forecast_divergence_index"),
                        "pipeline_version": behavioral["pipeline_version"],
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[SAFETY_INCIDENT] behavioural anomaly lookup failed "
                    f"(non-fatal): {e!r}"
                )

        inc = SafetyIncident(
            child_id=cu,
            incident_type=kind,
            severity=(severity or "info"),
            state=IncidentState.DETECTED.value,
            confidence=float(modified_confidence),
            sla_incident_id=sla_id,
            sla_degraded_at_dispatch=bool(sla_degraded),
            extra=meta or None,
            external_signals=external_audit,
            confidence_pre_external=(
                base_confidence if external_audit is not None else None
            ),
        )
        session.add(inc)
        await session.flush()

        # Day 3 — write the DETECTED creation event. `from_state=None`
        # marks this as the genesis row; the timeline endpoint uses the
        # NULL to render "X detected" rather than "Y → X".
        try:
            from app.models.safety_incident_event import SafetyIncidentEvent
            session.add(SafetyIncidentEvent(
                incident_id=inc.id,
                from_state=None,
                to_state=IncidentState.DETECTED.value,
                actor_id=None,
                actor_type="system",
                ttfa_tag=f"incident_state:{IncidentState.DETECTED.value}",
                sla_degraded=bool(sla_degraded),
                extra={
                    "confidence": float(modified_confidence),
                    "escalation_level": 0,
                    "alert_id": alert_id,
                    "kind": kind,
                },
            ))
            # NISCH-012.0 — forensic row when an external signal moved
            # the needle. We deliberately fire this AS A SEPARATE EVENT
            # (not folded into the DETECTED row) so the timeline UI
            # can render it as its own line: "weather bumped confidence
            # from 0.78 to 0.93".
            if external_audit is not None:
                session.add(SafetyIncidentEvent(
                    incident_id=inc.id,
                    from_state=IncidentState.DETECTED.value,
                    to_state=IncidentState.DETECTED.value,
                    actor_id=None,
                    actor_type="external_signal",
                    ttfa_tag="confidence_modifier",
                    sla_degraded=False,
                    extra={
                        "confidence_before": external_audit.get("confidence_before"),
                        "confidence_after":  external_audit.get("confidence_after"),
                        "modifier_applied":  external_audit.get("modifier_applied"),
                        "modifier_capped":   external_audit.get("modifier_capped"),
                        "providers": [
                            {
                                "provider":    p["provider"],
                                "signal_type": p["signal_type"],
                                "delta":       p.get("delta", 0.0),
                                "applied":     p.get("applied", False),
                            }
                            for p in external_audit.get("providers", [])
                        ],
                    },
                ))
            await session.flush()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SAFETY_INCIDENT] DETECTED event write failed (non-fatal): {e}")

        logger.info(
            f"[SAFETY_INCIDENT] OPEN id={inc.id} child={cu} kind={kind} "
            f"severity={severity} sla_degraded={sla_degraded} alert_id={alert_id}"
        )

        # NISCH-008 — auto-open an emergency recording session on alert+.
        # Fire-and-forget: a stream-session failure must NEVER block the
        # safety-incident creation path. The session itself is dormant
        # until the mobile client picks it up and starts uploading
        # chunks, so an orphan row is harmless.
        if (severity or "info").lower() in ("alert", "critical"):
            try:
                from app.services import emergency_stream_service as _ess
                await _ess.start_recording_session(
                    session,
                    child_id=cu,
                    incident_id=inc.id,
                    trigger=f"safety_brain:{(severity or 'alert').lower()}",
                    risk_score=float(modified_confidence) if modified_confidence is not None else None,
                )
                await session.flush()
                logger.info(
                    f"[NISCH-008] auto-opened stream session for incident "
                    f"id={inc.id} severity={severity}"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[NISCH-008] auto-open failed (non-fatal) "
                    f"incident={inc.id}: {e}"
                )

        return inc
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[SAFETY_INCIDENT] open failed (non-fatal) "
            f"child={child_id} kind={kind}: {e}"
        )
        return None


async def advance_to_validating(
    session: AsyncSession, incident: SafetyIncident
) -> None:
    """DETECTED → VALIDATING. Called once dedup gate has passed and
    guardian resolution is complete (the alert is real)."""
    if incident is None:
        return
    try:
        await transition(session, incident, IncidentState.VALIDATING)
    except InvalidTransitionError:
        # Already past VALIDATING (concurrent path) — silent.
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SAFETY_INCIDENT] VALIDATING failed (non-fatal): {e}")


async def advance_to_escalated(
    session: AsyncSession, incident: SafetyIncident
) -> None:
    """VALIDATING → ESCALATED. Called after dispatch (SSE/Push/SMS) has
    been attempted. Failure to escalate state must NOT block delivery."""
    if incident is None:
        return
    try:
        await transition(session, incident, IncidentState.ESCALATED)
    except InvalidTransitionError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SAFETY_INCIDENT] ESCALATED failed (non-fatal): {e}")


async def find_by_alert_id(
    session: AsyncSession, alert_id: str | uuid.UUID
) -> Optional[SafetyIncident]:
    """Look up the SafetyIncident linked to a GuardianAlert via
    `extra->>'alert_id'`. Returns None when unlinked, or on any
    backend error (e.g. running under a non-Postgres backend in tests).
    """
    aid = str(alert_id)
    try:
        row = (await session.execute(
            select(SafetyIncident)
            .where(text("extra->>'alert_id' = :aid"))
            .params(aid=aid)
            .order_by(SafetyIncident.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        return row
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[SAFETY_INCIDENT] alert lookup failed: {e}")
        return None


async def acknowledge_incident_for_alert(
    session: AsyncSession,
    *,
    alert_id: str | uuid.UUID,
    actor_id: str | uuid.UUID,
) -> Optional[SafetyIncident]:
    """ESCALATED → ACKNOWLEDGED, when a guardian ACKs the linked alert.

    Skips silently when:
      * incident isn't linked
      * incident is already past ESCALATED (e.g. already acknowledged
        or auto-resolved)
    """
    try:
        inc = await find_by_alert_id(session, alert_id)
        if inc is None:
            return None
        try:
            actor_uuid = uuid.UUID(str(actor_id))
        except (ValueError, TypeError):
            actor_uuid = None
        try:
            await transition(
                session, inc, IncidentState.ACKNOWLEDGED,
                actor_id=actor_uuid,
                actor_type="guardian",
                note=f"alert_ack:{alert_id}",
            )
            return inc
        except InvalidTransitionError:
            return inc
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SAFETY_INCIDENT] ack linkage failed (non-fatal): {e}")
        return None


# ── Lifecycle sweeper ───────────────────────────────────────────────
async def sweep_lifecycle(
    session: AsyncSession,
    *,
    escalated_resolve_minutes: int,
    acknowledged_resolve_minutes: int,
    resolved_archive_minutes: int,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Single tick: auto-resolve idle ACK'd / ESCALATED incidents, then
    archive long-RESOLVED ones. Returns counts for observability."""
    now = now or datetime.now(timezone.utc)
    counts = {"resolved_from_ack": 0, "resolved_from_escalated": 0,
              "archived": 0}

    # `SELECT … FOR UPDATE SKIP LOCKED` is a Postgres-only contention
    # primitive; SQLite (used in unit tests) has no equivalent. Probe
    # the bind once and skip the locking clause when unsupported.
    try:
        bind = session.bind or session.get_bind()
        supports_for_update = (bind is not None
                               and bind.dialect.name == "postgresql")
    except Exception:
        supports_for_update = False

    def _q(state_value: str, cutoff: datetime):
        stmt = (select(SafetyIncident)
                .where(SafetyIncident.state == state_value)
                .where(SafetyIncident.updated_at < cutoff)
                .limit(200))
        if supports_for_update:
            stmt = stmt.with_for_update(skip_locked=True)
        return stmt

    # 1) ACKNOWLEDGED idle > N min → RESOLVED
    ack_cutoff = now - timedelta(minutes=acknowledged_resolve_minutes)
    rows = (await session.execute(
        _q(IncidentState.ACKNOWLEDGED.value, ack_cutoff)
    )).scalars().all()
    for inc in rows:
        try:
            await transition(session, inc, IncidentState.RESOLVED,
                             actor_type="scheduler",
                             note="auto_resolve:ack_idle")
            counts["resolved_from_ack"] += 1
        except InvalidTransitionError:
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SAFETY_INCIDENT_SWEEP] resolve(ack) {inc.id} failed: {e}")

    # 2) ESCALATED idle > N min (no ACK arrived) → RESOLVED
    esc_cutoff = now - timedelta(minutes=escalated_resolve_minutes)
    rows = (await session.execute(
        _q(IncidentState.ESCALATED.value, esc_cutoff)
    )).scalars().all()
    for inc in rows:
        try:
            await transition(session, inc, IncidentState.RESOLVED,
                             actor_type="scheduler",
                             note="auto_resolve:escalated_no_ack")
            counts["resolved_from_escalated"] += 1
        except InvalidTransitionError:
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SAFETY_INCIDENT_SWEEP] resolve(esc) {inc.id} failed: {e}")

    # 3) RESOLVED idle > M min → ARCHIVED
    arch_cutoff = now - timedelta(minutes=resolved_archive_minutes)
    rows = (await session.execute(
        _q(IncidentState.RESOLVED.value, arch_cutoff)
    )).scalars().all()
    for inc in rows:
        try:
            await transition(session, inc, IncidentState.ARCHIVED,
                             actor_type="scheduler",
                             note="auto_archive")
            counts["archived"] += 1
        except InvalidTransitionError:
            continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[SAFETY_INCIDENT_SWEEP] archive {inc.id} failed: {e}")

    if any(counts.values()):
        await session.commit()
        logger.info(f"[SAFETY_INCIDENT_SWEEP] {counts}")
    return counts


__all__ = [
    "open_incident_for_alert",
    "advance_to_validating",
    "advance_to_escalated",
    "find_by_alert_id",
    "acknowledge_incident_for_alert",
    "sweep_lifecycle",
]
