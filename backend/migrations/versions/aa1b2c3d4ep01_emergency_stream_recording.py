"""NISCH-008 — Emergency stream recording storage + audit trail.

Adds two tables that hang off the existing `stream_sessions` row
(which already models the WebRTC call lifecycle). This migration
covers the **stored** side of the stream — pre-signed chunk uploads
and the playback audit log demanded by DPDP.

Tables introduced:
  * `stream_recording_chunks` — one row per uploaded audio chunk or
    1-fps thumbnail. The `s3_key` is the authoritative object pointer
    (works for both real S3 and the stub-mode local-disk path).
  * `stream_playback_audits` — append-only "who watched what when"
    log. Every pre-signed GET issuance writes one row. Required for
    DPDP — auditors must be able to ask "show me everyone who
    accessed media for incident X".

Scope: schema only. Behavior lives in `services/emergency_stream_service.py`.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "aa1b2c3d4ep01"
down_revision = "ep1a2b3c4ec01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_recording_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("stream_sessions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("sequence", sa.Integer, nullable=False),
        # "audio_chunk" | "video_thumbnail"
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("upload_status", sa.String(16),
                  nullable=False, server_default="pending"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        # Per-chunk hash for forensic chain-of-custody. Optional —
        # mobile clients that don't compute it leave it null.
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.UniqueConstraint("session_id", "sequence", "media_type",
                            name="uq_stream_chunk_seq"),
        sa.CheckConstraint(
            "media_type IN ('audio_chunk', 'video_thumbnail')",
            name="ck_stream_chunk_media_type",
        ),
        sa.CheckConstraint(
            "upload_status IN ('pending', 'uploaded', 'failed', 'expired')",
            name="ck_stream_chunk_status",
        ),
    )
    op.create_index(
        "ix_stream_chunks_session_seq",
        "stream_recording_chunks",
        ["session_id", "sequence"],
    )
    # Retention sweeper picks rows by this index.
    op.create_index(
        "ix_stream_chunks_expires_at",
        "stream_recording_chunks",
        ["expires_at"],
    )

    op.create_table(
        "stream_playback_audits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("stream_sessions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("chunk_id", UUID(as_uuid=True),
                  sa.ForeignKey("stream_recording_chunks.id",
                                ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("viewer_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("viewer_role", sa.String(16), nullable=False),
        # "session_summary" | "chunk_playback" | "session_listing"
        sa.Column("access_type", sa.String(32), nullable=False),
        sa.Column("ip_address",   sa.String(64), nullable=True),
        sa.Column("user_agent",   sa.Text,       nullable=True),
        sa.Column("extra",        JSONB,
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("accessed_at",  sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "viewer_role IN ('operator', 'guardian', 'admin', 'child', 'woman')",
            name="ck_playback_audit_role",
        ),
    )
    op.create_index(
        "ix_playback_audits_accessed_at",
        "stream_playback_audits",
        ["accessed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_playback_audits_accessed_at",
                  table_name="stream_playback_audits")
    op.drop_table("stream_playback_audits")
    op.drop_index("ix_stream_chunks_expires_at",
                  table_name="stream_recording_chunks")
    op.drop_index("ix_stream_chunks_session_seq",
                  table_name="stream_recording_chunks")
    op.drop_table("stream_recording_chunks")
