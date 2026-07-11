"""System Incidents — historical truth layer for `system_health_delta`.

Strict scope (locked in PRD):
  • Persist + snapshot + correlate. Nothing more.
  • NO alerting, NO ticketing, NO workflow.
  • Write-only on severity transitions away from `healthy`.
  • Resolved when severity returns to `healthy`.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, JSON, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemIncident(Base):
    __tablename__ = "system_incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    started_at:  Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | resolved
    severity_peak:  Mapped[str] = mapped_column(String(16), nullable=False)             # warning | degraded
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)             # scheduler | ai | queue
    trigger_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Snapshot of all 5 domains at incident start.
    snapshot_json:   Mapped[dict] = mapped_column(type_=JSON, default=dict, nullable=False)
    # Snapshot at resolution (lightweight — just the closing state).
    resolution_json: Mapped[dict | None] = mapped_column(type_=JSON, nullable=True)

    # Auto-tagged from the snapshot at open + refreshed at resolve.
    # One of: scheduler | ai | queue | db | redis.
    # See `services/incident_classifier.py`.
    root_cause_domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
