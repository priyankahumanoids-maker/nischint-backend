"""Additive repair for ambiguous historical dp01 and FC06 upgrades.

The removed duplicate dp01 risk-index file has AST-identical upgrade/downgrade
functions to the retained dp02 risk-index revision. Neither historical revision
value changes: dp01 remains the ACK revision and dp02 remains its child.
An already stamped dp01 might have applied only indexes, so repair missing ACK
columns here without deleting data. No foreign keys are replaced by this repair.
"""
from alembic import op
from sqlalchemy import text
from app.migrations.fc04_family_consent_authority import _DDL as CONSENT_DDL
from app.migrations.fc06_family_entitlement_lifecycle_audit import DDL as LIFECYCLE_DDL
from app.migrations.family_constraint_compat import converge_constraints, converge_existing_indexes

revision = "fc07_schema_compat"
down_revision = "fc06_family_entitlement_lifecycle_audit"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE guardian_alerts ADD COLUMN IF NOT EXISTS context_json JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE guardian_alerts ADD COLUMN IF NOT EXISTS ack_type VARCHAR(16)",
    "ALTER TABLE guardian_alerts ADD COLUMN IF NOT EXISTS seen_deadline TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_guardian_alerts_seen_lapse ON guardian_alerts(seen_deadline) WHERE ack_type='seen'",
    "CREATE INDEX IF NOT EXISTS ix_guardian_alerts_created_at ON guardian_alerts(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_incidents_created_at_type ON incidents(created_at DESC, incident_type)",
    "CREATE INDEX IF NOT EXISTS ix_incidents_open_unacked ON incidents(status, created_at DESC) WHERE acknowledged_at IS NULL AND status='open'",
    "CREATE INDEX IF NOT EXISTS ix_caregiver_statuses_available ON caregiver_statuses(status) WHERE status='available'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_family_audit_event_key_all ON family_circle_audit_log(event_key)",
    "ALTER TABLE family_notification_outbox ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "CREATE INDEX IF NOT EXISTS ix_family_outbox_due ON family_notification_outbox(next_attempt_at) WHERE delivered_at IS NULL",
)


def upgrade():
    bind = op.get_bind()
    # Already-stamped databases receive the same definitions as fresh FC04/06.
    # This does not replay entitlement backfills or run app startup helpers.
    converge_constraints(bind, CONSENT_DDL)
    converge_constraints(bind, LIFECYCLE_DDL)
    for statement in STATEMENTS:
        if not statement.startswith("CREATE "):
            bind.execute(text(statement))
    converge_existing_indexes(bind, STATEMENTS)


def downgrade():
    # Keep additive repairs and historical audit data on downgrade.
    pass
