"""NISCH-012.0 — External signal audit columns on safety_incidents.

`external_signals` JSONB stores the audit envelope from
`apply_external_modifiers`. `confidence_pre_external` preserves the
original ML/heuristic confidence so the timeline can render
"AI said 0.78, weather bumped to 0.93".

Both columns nullable — pre-12.0 incidents keep working unchanged.
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "em1a2b3c4dz01"
down_revision = "dk1a2b3c4dz01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "safety_incidents",
        sa.Column("external_signals", JSONB, nullable=True),
    )
    op.add_column(
        "safety_incidents",
        sa.Column("confidence_pre_external", sa.Float, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("safety_incidents", "confidence_pre_external")
    op.drop_column("safety_incidents", "external_signals")
