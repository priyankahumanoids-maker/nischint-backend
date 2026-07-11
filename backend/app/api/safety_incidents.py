"""NISCH-006 Day 3 — Incident timeline endpoint.

`GET /api/incidents/{incident_id}/timeline` — ordered forensic replay
of every state transition for a SafetyIncident, with `elapsed_ms`
deltas computed server-side.

Auth boundary:
  * The caller must be a guardian linked to the incident's child via
    `Relationship.status='accepted'`, OR an admin/operator.
  * Anything else → 403.
  * Unknown incident → 404.

This is the data source the NISCH-007 Incident Feed UI consumes to
render a per-incident replay ("7:32 PM — Loud distress detected →
340 ms later — Validating → 1.2 s later — Escalated …").
"""
from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.relationship import Relationship
from app.models.safety_incident import SafetyIncident
from app.models.safety_incident_event import SafetyIncidentEvent
from app.models.stream_session import STREAM_ENDED, StreamSession
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["Safety Incidents"])


async def _is_authorized(
    session: AsyncSession, user: User, child_id: uuid.UUID
) -> bool:
    """Caller may read this child's incidents iff:
      * they are an admin or operator (org-wide read), OR
      * they are the child themselves, OR
      * they have an `accepted` Relationship row linking guardian→child.
    """
    if user.role in ("admin", "operator"):
        return True
    if user.id == child_id:
        return True
    rel = (await session.execute(
        select(Relationship).where(
            Relationship.guardian_id == user.id,
            Relationship.child_id == child_id,
            Relationship.status == "accepted",
        )
    )).scalar_one_or_none()
    return rel is not None


@router.get("/{incident_id}/timeline")
async def get_incident_timeline(
    incident_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Ordered transition history for one safety incident.

    Returns the parent incident envelope plus a chronological
    `timeline` array. `elapsed_ms` is the delta from the *previous*
    event's timestamp; the first event is always 0.
    """
    inc = (await session.execute(
        select(SafetyIncident).where(SafetyIncident.id == incident_id)
    )).scalar_one_or_none()
    if inc is None:
        raise HTTPException(404, "incident not found")

    if not await _is_authorized(session, user, inc.child_id):
        raise HTTPException(403, "not authorized for this incident")

    events = (await session.execute(
        select(SafetyIncidentEvent)
        .where(SafetyIncidentEvent.incident_id == incident_id)
        .order_by(SafetyIncidentEvent.created_at.asc())
    )).scalars().all()

    # Audit guard: a missing creation event indicates either an old
    # row from before Day 3 OR an event-write regression. Log loudly
    # but still return a usable response.
    if not events:
        logger.warning(
            f"[INCIDENT_TIMELINE] incident={incident_id} has zero events — "
            f"pre-Day-3 row or event-write failure?"
        )

    timeline: list[dict] = []
    prev_ts = None
    for e in events:
        elapsed_ms = 0
        if prev_ts is not None:
            elapsed_ms = int((e.created_at - prev_ts).total_seconds() * 1000)
        timeline.append({
            "id":           str(e.id),
            "from_state":   e.from_state,
            "to_state":     e.to_state,
            "actor_type":   e.actor_type,
            "actor_id":     str(e.actor_id) if e.actor_id else None,
            "ttfa_tag":     e.ttfa_tag,
            "sla_degraded": bool(e.sla_degraded),
            "metadata":     e.extra or {},
            "created_at":   e.created_at.isoformat(),
            "elapsed_ms":   elapsed_ms,
        })
        prev_ts = e.created_at

    # NISCH-008 — surface the most recent ENDED stream session (if any)
    # so the mobile timeline can render a 🎙 Listen chip for forensic
    # replay. We expose ENDED only — in-flight streams are still
    # mutating and don't have a stable recording_url. For an ended
    # stream with no recording_url (uploader hadn't finished or no
    # recorder was attached), `recording_url` is `null` and the chip
    # gracefully falls back to "Recording unavailable".
    stream_row = (await session.execute(
        select(StreamSession)
        .where(StreamSession.incident_id == incident_id)
        .where(StreamSession.state == STREAM_ENDED)
        .order_by(StreamSession.ended_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    stream_block = None
    if stream_row is not None:
        # `recording_url` is returned verbatim. When the WebRTC sprint
        # wires the on-device upload pipeline, that pipeline will
        # write a pre-signed (24h) S3 URL into this column directly,
        # so we don't need to re-sign here. Forward-compatible.
        stream_block = {
            "stream_id":        str(stream_row.id),
            "state":            stream_row.state,
            "stream_type":      stream_row.stream_type,
            "duration_seconds": stream_row.duration_seconds,
            "recording_url":    stream_row.recording_url,
            "started_at":       stream_row.started_at.isoformat() if stream_row.started_at else None,
            "ended_at":         stream_row.ended_at.isoformat() if stream_row.ended_at else None,
            "guardian_join_count": int(stream_row.guardian_join_count or 0),
        }

    return {
        "incident_id":              str(inc.id),
        "child_id":                 str(inc.child_id),
        "incident_type":            inc.incident_type,
        "severity":                 inc.severity,
        "current_state":            inc.state,
        "sla_degraded_at_dispatch": bool(inc.sla_degraded_at_dispatch),
        "created_at":               inc.created_at.isoformat(),
        "resolved_at":              inc.resolved_at.isoformat() if inc.resolved_at else None,
        "archived_at":              inc.archived_at.isoformat() if inc.archived_at else None,
        "timeline":                 timeline,
        "stream":                   stream_block,
    }
