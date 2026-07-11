"""NISCH-008 — Append-only playback audit log.

Every pre-signed GET issuance for emergency stream media writes one
row here. Required for DPDP — operators, guardians and admins must
be able to be re-identified to specific media they accessed during
an incident investigation.

This is an *audit* log, not a *cache*. We never update or delete rows
in normal operation; the retention sweeper is the only thing allowed
to clear them, and only after the linked chunk's retention has passed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


ACCESS_SESSION_SUMMARY = "session_summary"
ACCESS_CHUNK_PLAYBACK  = "chunk_playback"
ACCESS_SESSION_LISTING = "session_listing"


class StreamPlaybackAudit(Base):
    __tablename__ = "stream_playback_audits"
    __table_args__ = (
        CheckConstraint(
            "viewer_role IN ('operator', 'guardian', 'admin', 'child', 'woman')",
            name="ck_playback_audit_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stream_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stream_recording_chunks.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    viewer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    viewer_role: Mapped[str] = mapped_column(String(16), nullable=False)
    access_type: Mapped[str] = mapped_column(String(32), nullable=False)

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra:      Mapped[dict]       = mapped_column(JSONB, nullable=False, default=dict)

    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StreamPlaybackAudit session={self.session_id} "
            f"viewer={self.viewer_user_id}/{self.viewer_role} "
            f"type={self.access_type} at={self.accessed_at}>"
        )
