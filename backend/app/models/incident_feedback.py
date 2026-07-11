"""NISCH-009 — Guardian incident feedback model.

One verdict per (incident, guardian) — UPSERT contract enforced by
the unique index `uq_incident_feedback_incident_guardian`.

The forensic audit trail of every verdict (including changes) lives
in `safety_incident_events` with `actor_type='guardian_feedback'`,
not in this table — this table only carries the *current* verdict.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Single source of truth for the verdict enum at the app layer. The
# DB also carries a CHECK constraint with the same set — both must
# stay in sync.
VERDICT_MARK_SAFE      = "mark_safe"
VERDICT_CONFIRM_RISK   = "confirm_risk"
VERDICT_REPORT_ANOMALY = "report_anomaly"

ALLOWED_VERDICTS = frozenset({
    VERDICT_MARK_SAFE,
    VERDICT_CONFIRM_RISK,
    VERDICT_REPORT_ANOMALY,
})


class IncidentFeedback(Base):
    __tablename__ = "incident_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety_incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    guardian_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    note:    Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<IncidentFeedback {self.id} incident={self.incident_id} "
            f"guardian={self.guardian_id} verdict={self.verdict}>"
        )
