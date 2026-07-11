"""NISCH-008 — Live emergency stream session model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# State enum mirrored as Python constants — DB has the matching CHECK.
STREAM_OFFERED    = "offered"
STREAM_DECLINED   = "declined"
STREAM_CONNECTING = "connecting"
STREAM_LIVE       = "live"
STREAM_ENDED      = "ended"

ALLOWED_STREAM_STATES = frozenset({
    STREAM_OFFERED, STREAM_DECLINED, STREAM_CONNECTING,
    STREAM_LIVE, STREAM_ENDED,
})

# Allowed forward transitions. `ended` is terminal; `declined` is
# terminal too (the user can re-trigger via a fresh incident-level
# auto-offer if confidence rises again).
ALLOWED_STREAM_TRANSITIONS: dict[str, frozenset[str]] = {
    STREAM_OFFERED:    frozenset({STREAM_CONNECTING, STREAM_DECLINED, STREAM_ENDED}),
    STREAM_CONNECTING: frozenset({STREAM_LIVE, STREAM_ENDED}),
    STREAM_LIVE:       frozenset({STREAM_ENDED}),
    STREAM_DECLINED:   frozenset(),
    STREAM_ENDED:      frozenset(),
}


class StreamSession(Base):
    __tablename__ = "stream_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety_incidents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STREAM_OFFERED,
    )
    stream_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="audio",
    )
    ice_servers:   Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recording_url: Mapped[str | None]  = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guardian_join_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    offered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StreamSession {self.id} state={self.state} "
            f"incident={self.incident_id}>"
        )
