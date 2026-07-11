"""NISCH-006 Day 3 — Durable transition log for SafetyIncident.

Append-only event log. Every state transition (including the
DETECTED creation event) lands one row here. The combination of
`safety_incidents` + `safety_incident_events` is the forensic
truth pair: the parent table is the *current state*, the child table
is the *journey*.

Strict design:
  * `from_state` is NULL for the creation event (DETECTED). All other
    events must have both fields set.
  * `actor_type` ∈ {'guardian', 'system', 'scheduler'} — operators
    need to know whether a human or the auto-resolver closed an
    incident.
  * `metadata` is JSONB for forward-compat. We populate `confidence`
    and `escalation_level` at minimum so a future analytics surface
    has cohort data without joins.
  * ON DELETE CASCADE on the FK — TODO(GDPR): revisit cascade
    behaviour. Today, hard-deleting an incident wipes its events
    cleanly (right call for a child-safety system; GDPR erasure is
    a later sprint that may need ON DELETE SET NULL + nullable FK).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SafetyIncidentEvent(Base):
    __tablename__ = "safety_incident_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety_incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # NULL on the creation event (DETECTED). Always set on a transition.
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state:   Mapped[str]        = mapped_column(String(20), nullable=False)

    actor_id:    Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 'guardian' | 'system' | 'scheduler'
    actor_type:  Mapped[str | None]       = mapped_column(String(20), nullable=True)

    # 'incident_state:<state>' — for TTFA grouping.
    ttfa_tag:     Mapped[str | None]  = mapped_column(String(60), nullable=True)
    sla_degraded: Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False)

    # Forward-compat envelope: confidence, escalation_level, ring radius, etc.
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SafetyIncidentEvent {self.id} {self.from_state}→{self.to_state} "
            f"by={self.actor_type}>"
        )
