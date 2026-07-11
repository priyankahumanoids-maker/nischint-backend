"""NISCH-008 — Live emergency stream sessions table.

`stream_sessions` represents one offered/accepted/live stream tied to a
specific `safety_incidents` row. The state machine intentionally does
NOT live in Postgres — we use a thin string column with the contract
enforced in `services/stream_initiator.py`.

States (locked):
    offered    — auto-emitted on ESCALATED transition; awaiting child accept
    declined   — child explicitly declined OR 30s offer timeout fired
    connecting — child accepted; WebRTC handshake in flight
    live       — at least one guardian connected, child sending media
    ended      — child or all guardians disconnected; recording ready

ON DELETE CASCADE on the FK — when an incident is wiped (GDPR or
rollback) the stream history goes with it.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "dk1a2b3c4dz01"
down_revision = "cj1a2b3c4dy01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("safety_incidents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(20), nullable=False,
                  server_default=sa.text("'offered'")),
        sa.Column("stream_type", sa.String(10), nullable=False,
                  server_default=sa.text("'audio'")),
        sa.Column("ice_servers", postgresql.JSONB, nullable=True),
        sa.Column("recording_url", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("guardian_join_count", sa.Integer, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "idx_stream_incident", "stream_sessions", ["incident_id"],
    )
    # Hot-path: scheduler sweeps `offered` rows older than 30s to
    # auto-decline.
    op.create_index(
        "idx_stream_state_offered_at",
        "stream_sessions", ["state", "offered_at"],
    )

    op.create_check_constraint(
        "ck_stream_state",
        "stream_sessions",
        "state IN ('offered','declined','connecting','live','ended')",
    )
    op.create_check_constraint(
        "ck_stream_type",
        "stream_sessions",
        "stream_type IN ('audio','video')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stream_type", "stream_sessions", type_="check")
    op.drop_constraint("ck_stream_state", "stream_sessions", type_="check")
    op.drop_index("idx_stream_state_offered_at", table_name="stream_sessions")
    op.drop_index("idx_stream_incident", table_name="stream_sessions")
    op.drop_table("stream_sessions")
