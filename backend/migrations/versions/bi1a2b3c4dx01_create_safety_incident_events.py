"""NISCH-006 Day 3 — durable transition log for SafetyIncident.

`safety_incident_events` rows are written atomically with each state
transition. ON DELETE CASCADE — TODO(GDPR): revisit cascade behavior
when the child-data erasure sprint lands.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "bi1a2b3c4dx01"
down_revision = "ah1a2b3c4dw01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_incident_events",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("safety_incidents.id", ondelete="CASCADE"),
                  nullable=False),
        # NULL on the creation (DETECTED) event; non-null on transitions.
        sa.Column("from_state", sa.String(20), nullable=True),
        sa.Column("to_state",   sa.String(20), nullable=False),
        sa.Column("actor_id",   postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=True),
        sa.Column("ttfa_tag",   sa.String(60), nullable=True),
        sa.Column("sla_degraded", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # Hot-path index for the timeline endpoint: per-incident chronological scan.
    op.create_index(
        "idx_sie_incident_id",
        "safety_incident_events", ["incident_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_sie_incident_id", table_name="safety_incident_events")
    op.drop_table("safety_incident_events")
