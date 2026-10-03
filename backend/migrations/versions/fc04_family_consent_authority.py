"""Alembic revision for fc04_family_consent_authority.

The app-level schema helper remains for controlled startup compatibility; this
file is the authoritative Alembic history node and is deliberately not executed
by the Phase 6 apply/checkpoint workflow.
"""
from alembic import op
from sqlalchemy import text

from app.migrations.fc04_family_consent_authority import _DDL
from app.migrations.family_constraint_compat import converge_constraints

revision = "fc04_family_consent_authority"
down_revision = "fc03_circle_plan_seat_trial"
branch_labels = None
depends_on = None


def _statements():
    return [part.strip() for part in _DDL.split(";") if part.strip()]


def upgrade():
    converge_constraints(op.get_bind(), _DDL)


def downgrade():
    op.execute("DROP TABLE IF EXISTS family_sharing_states CASCADE")
    op.execute("DROP TABLE IF EXISTS family_consent_events CASCADE")
