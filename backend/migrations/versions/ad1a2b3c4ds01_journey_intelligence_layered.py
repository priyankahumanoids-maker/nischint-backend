"""Migration: Journey Intelligence — layered onto guardian_sessions.

Per /app/memory/SYSTEM_INVARIANTS.md and the locked execution brief:
  • `guardian_sessions` is the SOLE lifecycle state owner — extend it,
    never replace it. Adding 5 offline-tracking columns.
  • `journey_points` is an APPEND-ONLY event log, NOT a state source.
    FK back to `guardian_sessions(id)`. UNIQUE(session_id, seq) so the
    monotonic sequence is enforced at the DB.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "ad1a2b3c4ds01"
down_revision = "ac1a2b3c4dr01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 5 offline-tracking columns on guardian_sessions ──────────────
    op.add_column("guardian_sessions",
                  sa.Column("is_offline", sa.Boolean,
                            nullable=False, server_default=sa.text("false")))
    op.add_column("guardian_sessions",
                  sa.Column("last_seen_online_at",
                            sa.DateTime(timezone=True), nullable=True))
    op.add_column("guardian_sessions",
                  sa.Column("total_points", sa.Integer,
                            nullable=False, server_default="0"))
    op.add_column("guardian_sessions",
                  sa.Column("offline_gaps", sa.Integer,
                            nullable=False, server_default="0"))
    op.add_column("guardian_sessions",
                  sa.Column("max_gap_seconds", sa.Integer,
                            nullable=False, server_default="0"))
    # Hot-path index for the watchdog scan.
    op.create_index(
        "ix_guardian_sessions_active_not_offline",
        "guardian_sessions",
        ["previous_update_at"],
        postgresql_where=sa.text("status = 'active' AND is_offline = false"),
    )
    # Backfill last_seen_online_at = started_at for existing rows so
    # the watchdog doesn't immediately flip everything to offline.
    op.execute(
        "UPDATE guardian_sessions SET last_seen_online_at = started_at "
        "WHERE last_seen_online_at IS NULL"
    )

    # ── journey_points (append-only event log) ───────────────────────
    op.create_table(
        "journey_points",
        sa.Column("id", sa.BigInteger,
                  sa.Identity(always=False), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("guardian_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("accuracy", sa.Float, nullable=True),
        sa.Column("speed_mps", sa.Float, nullable=True),
        # quality: good | unstable | offline
        sa.Column("quality", sa.String(16), nullable=False,
                  server_default="good"),
        sa.Column("gap_before_s", sa.Integer, nullable=True),
        sa.Column("gps_recorded_at",
                  sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_received_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_unique_constraint(
        "uq_journey_points_session_seq",
        "journey_points",
        ["session_id", "seq"],
    )
    op.create_index("ix_journey_points_session_seq",
                    "journey_points", ["session_id", "seq"])
    op.create_index("ix_journey_points_recorded_at",
                    "journey_points", ["server_received_at"],
                    postgresql_using="btree")


def downgrade() -> None:
    op.drop_index("ix_journey_points_recorded_at", table_name="journey_points")
    op.drop_index("ix_journey_points_session_seq", table_name="journey_points")
    op.drop_constraint("uq_journey_points_session_seq",
                       "journey_points", type_="unique")
    op.drop_table("journey_points")
    op.drop_index("ix_guardian_sessions_active_not_offline",
                  table_name="guardian_sessions")
    for col in ("max_gap_seconds", "offline_gaps", "total_points",
                "last_seen_online_at", "is_offline"):
        op.drop_column("guardian_sessions", col)
