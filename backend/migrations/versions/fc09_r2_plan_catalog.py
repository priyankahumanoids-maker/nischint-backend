"""R2 data-driven Family Circle plan catalog.

Source only until explicitly migrated. Current v1.1 product plans are seeded as
rows so seat limits/features are runtime data rather than operational constants.
"""
from alembic import op
import sqlalchemy as sa

revision = "fc09_r2_plan_catalog"
down_revision = "fc08_r1_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table in ("family_circles", "family_circle_entitlements"):
        if not inspector.has_table(table):
            raise RuntimeError("R2 prerequisite missing: " + table)
    if inspector.has_table("family_plan_catalog"):
        raise RuntimeError("R2 plan catalog already exists; review partial deployment")
    op.execute("""
        CREATE TABLE family_plan_catalog (
            plan_key VARCHAR(20) PRIMARY KEY,
            display_name VARCHAR(80) NOT NULL,
            price_inr INTEGER NOT NULL CHECK (price_inr >= 0),
            billing_period VARCHAR(20) NOT NULL,
            trial_days INTEGER NULL CHECK (trial_days IS NULL OR trial_days > 0),
            seat_capacities JSONB NOT NULL CHECK (jsonb_typeof(seat_capacities) = 'object'),
            feature_flags JSONB NOT NULL CHECK (jsonb_typeof(feature_flags) = 'object'),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.get_bind().exec_driver_sql("""
        INSERT INTO family_plan_catalog
            (plan_key, display_name, price_inr, billing_period, trial_days,
             seat_capacities, feature_flags, active, sort_order)
        VALUES
            ('trial', '7-day Free Trial', 0, 'trial', 7,
             '{"protected":1,"guardian":2}'::jsonb,
             '{"mutual_visibility":false,"guardian_tracked":false,"behavioral_ai":"protected_adult_only","lifeline_supported":true}'::jsonb,
             TRUE, 10),
            ('individual', 'Individual', 299, 'month', NULL,
             '{"protected":1,"guardian":2}'::jsonb,
             '{"mutual_visibility":false,"guardian_tracked":false,"behavioral_ai":"protected_adult_only","lifeline_supported":true}'::jsonb,
             TRUE, 20),
            ('family', 'Family', 999, 'month', NULL,
             '{"member":4}'::jsonb,
             '{"mutual_visibility":true,"guardian_tracked":true,"behavioral_ai":"all_adults","lifeline_supported":true}'::jsonb,
             TRUE, 30)
    """)


def downgrade():
    raise RuntimeError("R2 plan data is product authority; destructive downgrade requires separate review")
