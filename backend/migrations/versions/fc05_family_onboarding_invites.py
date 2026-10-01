"""Alembic revision for fc05_family_onboarding_invites.

The app-level schema helper remains for controlled startup compatibility; this
file is the authoritative Alembic history node and is deliberately not executed
by the Phase 6 apply/checkpoint workflow.
"""
from alembic import op
from sqlalchemy import text

from app.migrations.fc05_family_onboarding_invites import _DDL

revision = "fc05_family_onboarding_invites"
down_revision = "fc04_family_consent_authority"
branch_labels = None
depends_on = None


def _statements():
    return [part.strip() for part in _DDL.split(";") if part.strip()]


def upgrade():
    bind = op.get_bind()
    for statement in _statements():
        bind.execute(text(statement))


def downgrade():
    op.execute("DROP TABLE IF EXISTS family_legal_acceptances CASCADE")
    op.execute("DROP TABLE IF EXISTS family_circle_invites CASCADE")
