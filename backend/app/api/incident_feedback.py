"""NISCH-009 — Guardian Feedback Loop API.

`POST /api/incidents/{id}/feedback` — submit a verdict. UPSERT.
`GET  /api/incidents/{id}/feedback` — read aggregated counts +
                                       caller's own verdict.

Closed-network rule (locked by tests):
  * Caller MUST be either:
      - admin / operator (org-wide write), OR
      - a guardian linked to the incident's child via
        `Relationship.status='accepted'`
  * Anyone else → 403. No anonymous reports — that's the whole point.

Forensic trail: every accepted verdict (insert OR update) writes a
`safety_incident_events` row with `actor_type='guardian_feedback'`.
The state column does not change for the event row alone — only
the auto-resolve transition (driven by the aggregator) creates a
real state change.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.incident_feedback import (
    ALLOWED_VERDICTS, IncidentFeedback,
)
from app.models.relationship import Relationship
from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.models.user import User
from app.services.feedback_aggregator import apply_feedback_decision

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["Safety Incidents"])


NOTE_MAX_LEN = 200


class FeedbackIn(BaseModel):
    verdict: str = Field(..., description="mark_safe|confirm_risk|report_anomaly")
    note: Optional[str] = Field(None, max_length=NOTE_MAX_LEN)


async def _is_authorized(
    session: AsyncSession, user: User, child_id: uuid.UUID,
) -> bool:
    """Closed-network rule: admin/operator pass, otherwise an
    `accepted` Relationship is required. Self (child = user) is NOT
    auto-permitted — a child should not be voting on their own
    incident; that's not a guardian feedback signal."""
    role = (user.role or "").lower()
    if role in ("admin", "operator"):
        return True
    rel = (await session.execute(
        select(Relationship).where(
            Relationship.guardian_id == user.id,
            Relationship.child_id == child_id,
            Relationship.status == "accepted",
        )
    )).scalar_one_or_none()
    return rel is not None


async def _load_incident(
    session: AsyncSession, incident_id: uuid.UUID,
) -> SafetyIncident:
    inc = (await session.execute(
        select(SafetyIncident).where(SafetyIncident.id == incident_id)
    )).scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "incident not found")
    return inc


@router.post("/{incident_id}/feedback")
async def submit_incident_feedback(
    incident_id: uuid.UUID,
    body: FeedbackIn,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Submit or update a verdict on an incident.

    UPSERT on (incident_id, guardian_id). Latest verdict wins; the
    forensic event log preserves the prior verdict via the
    `previous_verdict` field in `extra`.
    """
    if body.verdict not in ALLOWED_VERDICTS:
        raise HTTPException(
            400,
            f"verdict must be one of {sorted(ALLOWED_VERDICTS)}",
        )

    inc = await _load_incident(session, incident_id)

    if not await _is_authorized(session, user, inc.child_id):
        raise HTTPException(403, "not authorized — closed network only")

    # Cannot vote on already-archived incidents — they're terminal
    # and feedback can no longer move the AI loop. Resolved is OK
    # (a resurrection vote is meaningful).
    if inc.state == "archived":
        raise HTTPException(409, "incident archived; feedback closed")

    note = (body.note or "").strip() or None
    now = datetime.now(timezone.utc)

    # UPSERT — find existing row first.
    existing = (await session.execute(
        select(IncidentFeedback).where(
            IncidentFeedback.incident_id == incident_id,
            IncidentFeedback.guardian_id == user.id,
        )
    )).scalar_one_or_none()

    is_update = existing is not None
    previous_verdict = existing.verdict if existing else None

    if existing is not None:
        existing.verdict = body.verdict
        existing.note = note
        existing.updated_at = now
        feedback_row = existing
    else:
        feedback_row = IncidentFeedback(
            incident_id=incident_id,
            guardian_id=user.id,
            verdict=body.verdict,
            note=note,
            created_at=now,
            updated_at=now,
        )
        session.add(feedback_row)

    await session.flush()

    # Forensic trail: one row per submission (insert OR update). The
    # state stays the same on this event — we only emit a state
    # change if the aggregator's auto-resolve fires below.
    audit = SafetyIncidentEvent(
        incident_id=incident_id,
        from_state=inc.state,
        to_state=inc.state,
        actor_id=user.id,
        actor_type="guardian_feedback",
        ttfa_tag=f"feedback:{body.verdict}",
        sla_degraded=False,
        extra={
            "verdict":          body.verdict,
            "previous_verdict": previous_verdict,
            "is_update":        is_update,
            "note":             note,
        },
        created_at=now,
    )
    session.add(audit)
    await session.flush()

    # Run the aggregator AFTER the new row is visible. It mutates
    # confidence + may auto-resolve the incident.
    decision = await apply_feedback_decision(
        session, inc, actor_id=user.id,
    )

    return {
        "feedback": {
            "id":           str(feedback_row.id),
            "incident_id":  str(incident_id),
            "guardian_id":  str(user.id),
            "verdict":      feedback_row.verdict,
            "note":         feedback_row.note,
            "created_at":   feedback_row.created_at.isoformat(),
            "updated_at":   feedback_row.updated_at.isoformat(),
            "is_update":    is_update,
        },
        "aggregate": {
            "counts":            decision["counts"],
            "classification":    decision["classification"],
            "confidence_before": decision["confidence_before"],
            "confidence_after":  decision["confidence_after"],
            "auto_resolved":     decision["auto_resolved"],
            "current_state":     inc.state,
        },
    }


@router.get("/{incident_id}/feedback")
async def get_incident_feedback(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Aggregated feedback for an incident.

    Returns per-verdict counts plus the caller's own verdict (so the
    UI can render "you voted: Mark Safe — change?" without an extra
    round trip)."""
    inc = await _load_incident(session, incident_id)

    if not await _is_authorized(session, user, inc.child_id):
        raise HTTPException(403, "not authorized — closed network only")

    rows = (await session.execute(
        select(IncidentFeedback).where(
            IncidentFeedback.incident_id == incident_id
        )
    )).scalars().all()

    counts = {"mark_safe": 0, "confirm_risk": 0, "report_anomaly": 0}
    own: Optional[dict] = None
    for r in rows:
        if r.verdict in counts:
            counts[r.verdict] += 1
        if r.guardian_id == user.id:
            own = {
                "verdict":    r.verdict,
                "note":       r.note,
                "updated_at": r.updated_at.isoformat(),
            }

    total = sum(counts.values())
    return {
        "incident_id":   str(incident_id),
        "current_state": inc.state,
        "counts":        counts,
        "total":         total,
        "own_verdict":   own,
    }


__all__ = ["router"]
