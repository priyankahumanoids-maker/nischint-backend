"""NISCH-008 — Per-chunk row for a stored emergency stream session.

One row per uploaded audio chunk OR 1-fps video thumbnail. The
authoritative pointer is `s3_key`; in `MOCK_S3=true` mode this is a
relative path on local disk, in real mode it's the S3 object key.

Lifecycle:
    presign issued → upload_status = "pending"
    client uploaded → upload_status = "uploaded", uploaded_at set
    retention sweeper deletes the S3/local object and the row when
    `expires_at <= now()`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


MEDIA_AUDIO_CHUNK     = "audio_chunk"
MEDIA_VIDEO_THUMBNAIL = "video_thumbnail"

CHUNK_PENDING  = "pending"
CHUNK_UPLOADED = "uploaded"
CHUNK_FAILED   = "failed"
CHUNK_EXPIRED  = "expired"


class StreamRecordingChunk(Base):
    __tablename__ = "stream_recording_chunks"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", "media_type",
                         name="uq_stream_chunk_seq"),
        CheckConstraint(
            "media_type IN ('audio_chunk', 'video_thumbnail')",
            name="ck_stream_chunk_media_type",
        ),
        CheckConstraint(
            "upload_status IN ('pending', 'uploaded', 'failed', 'expired')",
            name="ck_stream_chunk_status",
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
    sequence:     Mapped[int]    = mapped_column(Integer, nullable=False)
    media_type:   Mapped[str]    = mapped_column(String(32), nullable=False)
    content_type: Mapped[str]    = mapped_column(String(64), nullable=False)
    s3_key:       Mapped[str]    = mapped_column(Text, nullable=False)
    size_bytes:   Mapped[int]    = mapped_column(Integer, nullable=False)

    upload_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CHUNK_PENDING,
    )
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    content_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StreamRecordingChunk session={self.session_id} "
            f"seq={self.sequence} type={self.media_type} "
            f"status={self.upload_status}>"
        )
