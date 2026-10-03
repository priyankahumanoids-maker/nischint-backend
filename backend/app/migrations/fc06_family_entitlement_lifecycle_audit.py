"""FC-06 - canonical Family Circle entitlement, lifecycle and audit foundation.

Additive only. It does not integrate a live payment gateway. Paid-plan activation
remains impossible until a future verified provider adapter supplies a normalized
billing event.
"""
from __future__ import annotations

from sqlalchemy import text


DDL = r'''
CREATE TABLE IF NOT EXISTS family_circle_entitlements (
    circle_id UUID PRIMARY KEY REFERENCES family_circles(id) ON DELETE CASCADE,
    state VARCHAR(24) NOT NULL,
    provider VARCHAR(24) NULL,
    provider_subscription_ref VARCHAR(160) NULL,
    current_period_start TIMESTAMPTZ NULL,
    current_period_end TIMESTAMPTZ NULL,
    grace_until TIMESTAMPTZ NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    pending_plan VARCHAR(20) NULL,
    pending_plan_effective_at TIMESTAMPTZ NULL,
    pending_seat_assignments JSONB NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_family_entitlement_state CHECK (
        state IN ('trial_active','payment_pending','paid_active','grace','lifeline')
    ),
    CONSTRAINT ck_family_entitlement_pending_plan CHECK (
        pending_plan IS NULL OR pending_plan IN ('individual','family')
    )
);

ALTER TABLE family_circle_entitlements
    ADD COLUMN IF NOT EXISTS pending_seat_assignments JSONB NULL;

CREATE TABLE IF NOT EXISTS family_billing_events (
    id UUID PRIMARY KEY,
    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE CASCADE,
    provider VARCHAR(24) NOT NULL,
    provider_event_id VARCHAR(180) NOT NULL,
    event_type VARCHAR(48) NOT NULL,
    payload_digest VARCHAR(64) NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_family_billing_provider_event UNIQUE(provider, provider_event_id)
);
CREATE INDEX IF NOT EXISTS ix_family_billing_events_circle_time
    ON family_billing_events(circle_id, created_at DESC);

CREATE TABLE IF NOT EXISTS family_circle_audit_log (
    id UUID PRIMARY KEY,
    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE RESTRICT,
    event_key VARCHAR(220) NULL UNIQUE,
    actor_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    subject_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    event_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_family_audit_circle_time
    ON family_circle_audit_log(circle_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_family_audit_subject_time
    ON family_circle_audit_log(subject_user_id, created_at DESC);

ALTER TABLE family_circle_audit_log ADD COLUMN IF NOT EXISTS event_key VARCHAR(220) NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_family_audit_event_key ON family_circle_audit_log(event_key) WHERE event_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_family_audit_event_key_all ON family_circle_audit_log(event_key);

CREATE TABLE IF NOT EXISTS family_location_view_log (
    id UUID PRIMARY KEY,
    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE RESTRICT,
    viewer_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    viewer_kind VARCHAR(24) NOT NULL DEFAULT 'member',
    viewer_label VARCHAR(160) NULL,
    subject_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    view_kind VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_family_location_view_kind CHECK (view_kind IN ('live','history')),
    CONSTRAINT ck_family_location_viewer_kind CHECK (viewer_kind IN ('member','public_link','staff','emergency'))
);
CREATE INDEX IF NOT EXISTS ix_family_location_view_subject_time
    ON family_location_view_log(subject_user_id, created_at DESC);

ALTER TABLE family_location_view_log ALTER COLUMN viewer_user_id DROP NOT NULL;
ALTER TABLE family_location_view_log ADD COLUMN IF NOT EXISTS viewer_kind VARCHAR(24) NOT NULL DEFAULT 'member';
ALTER TABLE family_location_view_log ADD COLUMN IF NOT EXISTS viewer_label VARCHAR(160) NULL;


INSERT INTO family_circle_entitlements (circle_id, state, current_period_end, updated_at)
SELECT id,
       CASE WHEN plan='trial' THEN 'trial_active' ELSE 'payment_pending' END,
       CASE WHEN plan='trial' THEN trial_ends_at ELSE NULL END,
       NOW()
  FROM family_circles
 WHERE status='active' AND plan IN ('trial','individual','family')
ON CONFLICT (circle_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS family_notification_outbox (
    id UUID PRIMARY KEY,
    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE RESTRICT,
    recipient_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    event_key VARCHAR(220) NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    title VARCHAR(160) NOT NULL,
    body VARCHAR(500) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR(300) NULL,
    delivered_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_family_notification_outbox_recipient_pending
    ON family_notification_outbox(recipient_user_id, created_at) WHERE delivered_at IS NULL;
ALTER TABLE family_notification_outbox ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS ix_family_outbox_due ON family_notification_outbox(next_attempt_at) WHERE delivered_at IS NULL;

CREATE TABLE IF NOT EXISTS family_age18_transitions (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE CASCADE,
    transitioned_at TIMESTAMPTZ NOT NULL,
    consent_due_at TIMESTAMPTZ NOT NULL,
    consent_completed_at TIMESTAMPTZ NULL,
    bridge_expired_at TIMESTAMPTZ NULL
);
'''


async def ensure_family_entitlement_lifecycle_audit_schema() -> None:
    from app.db.session import engine
    async with engine.begin() as conn:
        for statement in [s.strip() for s in DDL.split(';') if s.strip()]:
            await conn.execute(text(statement))


__all__ = ['DDL', 'ensure_family_entitlement_lifecycle_audit_schema']
