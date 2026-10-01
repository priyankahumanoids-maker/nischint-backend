"""Alembic revision for fc06_family_entitlement_lifecycle_audit.

The app-level schema helper remains for controlled startup compatibility; this
file is the authoritative Alembic history node and is deliberately not executed
by the Phase 6 apply/checkpoint workflow.
"""
from alembic import op
from sqlalchemy import text

from app.migrations.fc06_family_entitlement_lifecycle_audit import DDL

revision = "fc06_family_entitlement_lifecycle_audit"
down_revision = "fc05_family_onboarding_invites"
branch_labels = None
depends_on = None


def _statements():
    return [part.strip() for part in DDL.split(";") if part.strip()]


def upgrade():
    bind = op.get_bind()
    for statement in _statements():
        bind.execute(text(statement))


def downgrade():
    op.execute("DROP TABLE IF EXISTS family_age18_transitions CASCADE")
    op.execute("DROP TABLE IF EXISTS family_notification_outbox CASCADE")
    op.execute("DROP TABLE IF EXISTS family_location_view_log CASCADE")
    op.execute("DROP TABLE IF EXISTS family_circle_audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS family_billing_events CASCADE")
    op.execute("DROP TABLE IF EXISTS family_circle_entitlements CASCADE")
