"""R1 lifecycle operation persistence. Source only; do not run at startup."""
from alembic import op
import sqlalchemy as sa

revision = "fc08_r1_lifecycle"
down_revision = "auth05_security_foundation"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table in ("users", "family_circles", "circle_memberships", "family_circle_audit_log", "family_notification_outbox"):
        if not inspector.has_table(table):
            raise RuntimeError("R1 prerequisite missing: " + table)
    if inspector.has_table("family_lifecycle_operations"):
        raise RuntimeError("R1 operation table already exists; review partial deployment")
    op.execute("""
        CREATE TABLE family_lifecycle_operations (
            id UUID PRIMARY KEY,
            circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE RESTRICT,
            actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            membership_id UUID REFERENCES circle_memberships(id) ON DELETE SET NULL,
            kind TEXT NOT NULL CHECK (kind IN ('ownership_transfer','member_remove','minor_add','plan_cancel','circle_delete')),
            state TEXT NOT NULL CHECK (state IN ('pending','awaiting_verification','provider_pending','completed','undone','cancelled')),
            details JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            CHECK (expires_at IS NULL OR expires_at >= created_at)
        )
    """)
    op.execute("CREATE INDEX ix_family_lifecycle_pending ON family_lifecycle_operations (circle_id, kind, expires_at) WHERE state = 'pending'")
    op.execute("CREATE UNIQUE INDEX uq_family_pending_transfer ON family_lifecycle_operations (circle_id) WHERE kind = 'ownership_transfer' AND state = 'pending'")


def downgrade():
    raise RuntimeError("R1 contains consent/lifecycle history; destructive downgrade requires separate review")
