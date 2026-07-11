"""NISCH-006 — Safety incident model.

Distinct from the existing `incidents` (senior-care). This is the
child-centric lifecycle table that anchors NISCH-006/007/009.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SafetyIncident(Base):
    __tablename__ = "safety_incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    incident_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity:      Mapped[str] = mapped_column(String(20), nullable=False)
    state:         Mapped[str] = mapped_column(String(20), nullable=False, default="detected", index=True)
    confidence:    Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # SLA annotation — populated at dispatch if SLA verdict was non-green.
    sla_incident_id:           Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sla_degraded_at_dispatch:  Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    acknowledged_by:  Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    escalation_level: Mapped[int]         = mapped_column(Integer, nullable=False, default=0)
    extra:            Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # NISCH-012.0 — external signal modifier audit. Populated at
    # incident-open time when one or more registered providers
    # returned a high-risk signal at the incident's location.
    # Nullable — incidents without location, or without any signals
    # crossing the threshold, leave both fields unset.
    external_signals:        Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    confidence_pre_external: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SafetyIncident {self.id} {self.state} type={self.incident_type}>"
