"""NISCH-006 — safety_incidents lifecycle table.

The child-centric incident lifecycle anchor. Distinct from the existing
`incidents` table (which is the senior-care entity). Every state change
on these rows must go through `app.services.incident_state_machine`.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ah1a2b3c4dw01"
down_revision = "ag1a2b3c4dv01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="detected"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("sla_incident_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sla_degraded_at_dispatch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("idx_safety_incidents_child_state", "safety_incidents", ["child_id", "state"])
    op.create_index("idx_safety_incidents_created", "safety_incidents", [sa.text("created_at DESC")])
    op.create_index("idx_safety_incidents_state", "safety_incidents", ["state"])


def downgrade() -> None:
    op.drop_index("idx_safety_incidents_state", table_name="safety_incidents")
    op.drop_index("idx_safety_incidents_created", table_name="safety_incidents")
    op.drop_index("idx_safety_incidents_child_state", table_name="safety_incidents")
    op.drop_table("safety_incidents")
