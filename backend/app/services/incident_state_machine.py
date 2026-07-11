"""NISCH-006 — Incident lifecycle state machine.

Single source of truth for incident state transitions. Every state
change in the safety pipeline MUST go through `transition()` — direct
DB writes to `safety_incidents.state` are forbidden by code review
convention.

States (enforced enum):
    DETECTED  → VALIDATING
    VALIDATING → ESCALATED | RESOLVED
    ESCALATED → ACKNOWLEDGED | RESOLVED
    ACKNOWLEDGED → RESOLVED
    RESOLVED  → ARCHIVED

Strict design:
* Pure transition validation — `is_valid_transition()` does NOT touch DB.
* `transition()` is the only function that writes; it validates first,
  then persists, then emits an SSE event AND a TTFA-recorder sample so
  the alert correlation layer (NISCH-008d) sees lifecycle events too.
* Invalid transitions raise `InvalidTransitionError` with a clear
  message naming the (from, to) pair. NEVER silently swallow.
* SSE / TTFA emission is best-effort — observability must never block
  the persisted transition.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety_incident import SafetyIncident

logger = logging.getLogger(__name__)


class IncidentState(str, Enum):
    DETECTED     = "detected"
    VALIDATING   = "validating"
    ESCALATED    = "escalated"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED     = "resolved"
    ARCHIVED     = "archived"


# Allowed transitions — read-only contract.
ALLOWED_TRANSITIONS: dict[IncidentState, frozenset[IncidentState]] = {
    IncidentState.DETECTED:     frozenset({IncidentState.VALIDATING}),
    IncidentState.VALIDATING:   frozenset({IncidentState.ESCALATED, IncidentState.RESOLVED}),
    IncidentState.ESCALATED:    frozenset({IncidentState.ACKNOWLEDGED, IncidentState.RESOLVED}),
    IncidentState.ACKNOWLEDGED: frozenset({IncidentState.RESOLVED}),
    IncidentState.RESOLVED:     frozenset({IncidentState.ARCHIVED}),
    IncidentState.ARCHIVED:     frozenset(),  # terminal
}


class InvalidTransitionError(ValueError):
    """Raised when a state transition violates the contract."""


@dataclass
class TransitionEvent:
    incident_id: str
    from_state:  IncidentState
    to_state:    IncidentState
    actor_id:    Optional[str]
    note:        Optional[str]
    at:          datetime

    def to_sse(self) -> dict:
        # NOTE: The mobile incident feed (`app/(tabs)/incidents.tsx`)
        # patches rows in place by reading `state_label`, `state` /
        # `to_state`, and `severity` from this payload. The legacy
        # `from`/`to` keys are preserved for any older consumer; the
        # `from_state`/`to_state`/`state_label` keys are the canonical
        # mobile contract verified by `test_nisch007_e2e.py`.
        from app.api.incidents_feed import STATE_LABELS
        return {
            "type":         "incident_state_change",
            "incident_id":  self.incident_id,
            # Canonical contract (mobile reads these):
            "from_state":   self.from_state.value,
            "to_state":     self.to_state.value,
            "state":        self.to_state.value,
            "state_label":  STATE_LABELS.get(self.to_state.value,
                                              self.to_state.value),
            # Legacy compat — older clients/dashboards still on these:
            "from":         self.from_state.value,
            "to":           self.to_state.value,
            "actor_id":     self.actor_id,
            "note":         self.note,
            "timestamp":    self.at.isoformat(),
        }


def is_valid_transition(from_state: IncidentState, to_state: IncidentState) -> bool:
    """Pure check — no DB. Returns True iff the transition is allowed."""
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


def assert_valid_transition(from_state: IncidentState, to_state: IncidentState) -> None:
    if not is_valid_transition(from_state, to_state):
        raise InvalidTransitionError(
            f"invalid transition {from_state.value} → {to_state.value}; "
            f"allowed: {sorted(s.value for s in ALLOWED_TRANSITIONS.get(from_state, frozenset()))}"
        )


async def transition(
    session: AsyncSession,
    incident: SafetyIncident,
    new_state: IncidentState,
    *,
    actor_id: Optional[uuid.UUID] = None,
    actor_type: str = "system",
    note: Optional[str] = None,
) -> TransitionEvent:
    """Move `incident` to `new_state`. Validates, persists, emits.

    Caller is responsible for the surrounding transaction. We `flush()`
    so SELECT/UPDATE ordering is correct inside the request.

    `actor_type` ∈ {'guardian', 'system', 'scheduler'} — must be
    truthful so the timeline can show *who* drove each transition.
    """
    current = IncidentState(incident.state)
    assert_valid_transition(current, new_state)

    now = datetime.now(timezone.utc)
    incident.state = new_state.value
    incident.updated_at = now
    if new_state is IncidentState.ACKNOWLEDGED and actor_id is not None:
        incident.acknowledged_by = actor_id
        incident.acknowledged_at = now
    if new_state is IncidentState.RESOLVED:
        incident.resolved_at = now
    if new_state is IncidentState.ARCHIVED:
        incident.archived_at = now

    # Day 3 — durable event row, atomic with the state mutation.
    # Lazy import keeps pure unit tests of the state machine
    # decoupled from the DB model layer.
    try:
        from app.models.safety_incident_event import SafetyIncidentEvent
        evt = SafetyIncidentEvent(
            incident_id=incident.id,
            from_state=current.value,
            to_state=new_state.value,
            actor_id=actor_id,
            actor_type=actor_type,
            ttfa_tag=f"incident_state:{new_state.value}",
            sla_degraded=bool(getattr(incident, "sla_degraded_at_dispatch", False)),
            extra={
                "confidence": float(getattr(incident, "confidence", 1.0) or 1.0),
                "escalation_level": int(getattr(incident, "escalation_level", 0) or 0),
                "note": note,
            },
            created_at=now,
        )
        session.add(evt)
    except Exception as e:  # noqa: BLE001
        # Atomic write contract: if the event row can't be added,
        # we still allow the state mutation to flush — the in-memory
        # transition is the most important fact for the live alert
        # path. The forensic record is best-effort. A flush failure
        # downstream WILL bubble out and the caller's transaction
        # will roll back the state change too — that's the correct
        # safety property.
        logger.warning(f"[INCIDENT_STATE] event row construct failed: {e}")

    await session.flush()

    # NISCH-008 — Auto-offer a live stream when an incident hits
    # ESCALATED. Best-effort; the lifecycle transition itself must
    # never block on streaming infrastructure (Twilio NTS, broadcaster).
    if new_state is IncidentState.ESCALATED:
        try:
            from app.services.stream_initiator import (
                offer_stream_for_incident,
            )
            await offer_stream_for_incident(session, incident)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[INCIDENT_STATE] stream auto-offer failed: {e!r}")

    event = TransitionEvent(
        incident_id=str(incident.id),
        from_state=current,
        to_state=new_state,
        actor_id=str(actor_id) if actor_id else None,
        note=note,
        at=now,
    )

    # Best-effort observability emissions.
    _emit_sse(event, child_id=str(incident.child_id))
    _emit_ttfa(event)
    logger.info(
        f"[INCIDENT_STATE] {event.from_state.value} → {event.to_state.value} "
        f"id={event.incident_id} child={incident.child_id} actor={event.actor_id} "
        f"actor_type={actor_type}"
    )
    return event


def _emit_sse(event: TransitionEvent, *, child_id: str) -> None:
    try:
        # Lazy import — avoid pulling broadcaster during pure unit tests.
        import asyncio
        from app.services.event_broadcaster import broadcaster
        coro = broadcaster.broadcast_to_user(child_id, "incident_state_change", event.to_sse())
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.create_task(coro)
        else:
            asyncio.run(coro)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[INCIDENT_STATE] SSE emit failed (non-fatal): {e}")


def _emit_ttfa(event: TransitionEvent) -> None:
    try:
        from app.services import ttfa_recorder
        ttfa_recorder.record(
            kind=f"incident_state:{event.to_state.value}",
            ttfa_ms=0,
            priority="critical" if event.to_state in {
                IncidentState.ESCALATED, IncidentState.DETECTED,
            } else "warning",
        )
    except Exception:
        pass


__all__ = [
    "IncidentState",
    "ALLOWED_TRANSITIONS",
    "InvalidTransitionError",
    "TransitionEvent",
    "is_valid_transition",
    "assert_valid_transition",
    "transition",
]
