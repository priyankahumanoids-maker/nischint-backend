from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.family_circle_permissions import (
    ACTION_INVITE_MEMBER,
    ACTION_TRIGGER_SOS,
    ACTION_VIEW_DASHBOARD,
    ACTION_VIEW_LOCATION,
    CONSENT_LOCATION,
    ENTITLEMENT_ACTIVE,
    ENTITLEMENT_LIFELINE,
    PermissionContext,
    ConsentState,
    permission_decision,
)
from app.services import family_circle_entitlement_service as ent
from app.services.family_circle_billing_contract import VerifiedBillingEvent

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')


def circle(plan: str, *, start=None, end=None):
    return SimpleNamespace(
        id='00000000-0000-0000-0000-000000000001',
        owner_user_id='00000000-0000-0000-0000-000000000002',
        plan=plan,
        trial_started_at=start,
        trial_ends_at=end,
    )


def test_protected_owner_can_administer_but_cannot_track_guardian_in_individual():
    admin_ctx = PermissionContext(
        actor_user_id='owner', actor_role='owner', actor_seat='protected',
        plan='individual', entitlement=ENTITLEMENT_ACTIVE,
    )
    assert permission_decision(admin_ctx, ACTION_INVITE_MEMBER).allowed

    view_ctx = PermissionContext(
        actor_user_id='owner', actor_role='owner', actor_seat='protected',
        plan='individual', entitlement=ENTITLEMENT_ACTIVE,
        target_user_id='guardian', target_role='adult_member', target_seat='guardian',
        target_consent=ConsentState({CONSENT_LOCATION: True}),
    )
    assert not permission_decision(view_ctx, ACTION_VIEW_LOCATION).allowed


def test_family_visibility_remains_mutual_under_plan_not_role():
    ctx = PermissionContext(
        actor_user_id='a', actor_role='adult_member', actor_seat='member',
        plan='family', entitlement=ENTITLEMENT_ACTIVE,
        target_user_id='b', target_role='owner', target_seat='member',
        target_consent=ConsentState({CONSENT_LOCATION: True}),
    )
    assert permission_decision(ctx, ACTION_VIEW_LOCATION).allowed


def test_trial_entitlement_is_exact_and_falls_to_lifeline():
    now = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    c = circle('trial', start=now - timedelta(days=1), end=now + timedelta(days=6))
    active = asyncio.run(ent.resolve_entitlement(None, c, now=now))
    assert active.permission_entitlement == ENTITLEMENT_ACTIVE
    expired = asyncio.run(ent.resolve_entitlement(None, c, now=c.trial_ends_at))
    assert expired.permission_entitlement == ENTITLEMENT_LIFELINE
    assert expired.payment_required is True


def test_paid_plan_without_verified_payment_is_lifeline(monkeypatch):
    async def no_row(session, circle_id): return None
    monkeypatch.setattr(ent, '_row', no_row)
    snap = asyncio.run(ent.resolve_entitlement(None, circle('individual')))
    assert snap.state == 'payment_pending'
    assert snap.permission_entitlement == ENTITLEMENT_LIFELINE
    assert snap.payment_required is True


def test_three_day_renewal_grace_keeps_full_features(monkeypatch):
    now = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    async def row(session, circle_id):
        return {'state': 'grace', 'current_period_end': now, 'grace_until': now + timedelta(days=3), 'cancel_at_period_end': False, 'pending_plan': None}
    monkeypatch.setattr(ent, '_row', row)
    snap = asyncio.run(ent.resolve_entitlement(None, circle('family'), now=now + timedelta(days=2)))
    assert snap.permission_entitlement == 'grace'
    expired = asyncio.run(ent.resolve_entitlement(None, circle('family'), now=now + timedelta(days=3)))
    assert expired.permission_entitlement == ENTITLEMENT_LIFELINE


def test_lifeline_keeps_sos_but_locks_dashboard():
    ctx = PermissionContext(actor_user_id='x', actor_role='owner', actor_seat='protected', plan='individual', entitlement='lifeline')
    assert permission_decision(ctx, ACTION_TRIGGER_SOS).allowed
    assert not permission_decision(ctx, ACTION_VIEW_DASHBOARD).allowed


def test_billing_contract_is_provider_neutral_and_has_no_live_gateway_adapter():
    src = read('app/services/family_circle_billing_contract.py')
    api = read('app/api/family_circle_phase6.py')
    assert 'BillingProviderAdapter' in src
    assert 'VerifiedBillingEvent' in src
    assert 'import razorpay' not in src.lower()
    assert 'httpx' not in src.lower()
    assert 'gateway_enabled' in api and 'False' in api
    assert 'webhook' not in api.lower()


def test_verified_event_requires_provider_event_id_and_sha256_digest():
    with pytest.raises(ValueError):
        VerifiedBillingEvent('razorpay', '', 'payment_activated', datetime.now(timezone.utc), '0'*64)
    with pytest.raises(ValueError):
        VerifiedBillingEvent('razorpay', 'evt1', 'payment_activated', datetime.now(timezone.utc), 'bad')


def test_runtime_authority_uses_canonical_entitlement_not_temporary_active():
    src = read('app/services/family_circle_runtime_authority.py')
    assert 'resolve_entitlement' in src
    assert 'entitlement.permission_entitlement' in src
    assert 'entitlement=ENTITLEMENT_ACTIVE' not in src


def test_age18_transition_has_seven_day_bridge_and_fail_closed_pause():
    src = read('app/services/family_circle_age_transition.py')
    assert 'BRIDGE_DAYS = 7' in src
    assert 'FAMILY_CONSENT_PURPOSES.issubset(decided)' in src
    assert 'birthday_instant_utc' in src
    assert 'event_type="role_changed"' in src or "event_type='role_changed'" in src
    assert 'membership.role = "adult_member"' in src or "membership.role = 'adult_member'" in src
    assert "pause_mode='manual'" in src or 'pause_mode="manual"' in src
    assert 'age18_consent_bridge_expired' in src


def test_pause_leave_and_audit_contracts_exist():
    life = read('app/services/family_circle_lifecycle_service.py')
    audit = read('app/services/family_circle_audit_service.py')
    assert '"1h": timedelta(hours=1)' in life
    assert '"8h": timedelta(hours=8)' in life
    assert 'A member left the circle' in life
    assert 'family_location_view_log' in audit
    assert 'days=max(1, min(int(days), 30))' in audit


def test_append_only_events_are_wired_to_invites_consent_views_and_billing():
    invite = read('app/services/family_circle_invite_service.py')
    consent = read('app/services/family_circle_consent_service.py')
    runtime = read('app/services/family_circle_runtime_authority.py')
    billing = read('app/services/family_circle_entitlement_service.py')
    for token in ('invite_created', 'member_joined', 'invite_revoked', 'parental_consent_recorded'):
        assert token in invite
    assert 'consent_given' in consent and 'consent_withdrawn' in consent
    assert 'record_location_view' in runtime
    assert 'event_type="billing_event"' in billing or "event_type='billing_event'" in billing


def test_fc06_schema_contains_entitlement_billing_audit_location_and_age18_tables():
    ddl = read('app/migrations/fc06_family_entitlement_lifecycle_audit.py')
    for table in (
        'family_circle_entitlements', 'family_billing_events', 'family_circle_audit_log',
        'family_location_view_log', 'family_age18_transitions',
    ):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in ddl


def test_phase6_router_is_registered_and_no_payment_activation_callback_exists():
    main = read('app/api/main.py')
    api = read('app/api/family_circle_phase6.py')
    assert 'family_circle_phase6_router' in main
    assert 'include_router(family_circle_phase6_router)' in main
    assert 'app-success' not in api
    assert 'activate-payment' not in api


def test_phase6_startup_wires_required_fc06_schema():
    server = read('server.py')
    assert 'ensure_family_entitlement_lifecycle_audit_schema' in server
    assert '[FC-06] required startup DDL failed; refusing startup' in server


def test_lifecycle_internal_primitives_cover_remove_coadmin_and_owner_transfer_without_public_bypass():
    life = read('app/services/family_circle_lifecycle_service.py')
    api = read('app/api/family_circle_phase6.py')
    assert 'async def remove_member' in life
    assert 'async def appoint_co_admin' in life
    assert 'async def remove_co_admin' in life
    assert 'async def transfer_ownership' in life
    assert 'new_owner_payment_mandate_required' in life
    assert '/remove-member' not in api
    assert '/transfer-ownership' not in api


def test_verified_billing_event_rejects_non_hex_digest_and_naive_time():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        VerifiedBillingEvent('provider', 'evt1', 'payment_activated', now, 'z'*64)
    with pytest.raises(ValueError):
        VerifiedBillingEvent('provider', 'evt1', 'payment_activated', now.replace(tzinfo=None), '0'*64)


def test_upgrade_and_downgrade_architecture_preserves_seat_semantics():
    billing = read('app/services/family_circle_entitlement_service.py')
    plan_change = read('app/services/family_circle_plan_change_service.py')
    migration = read('app/migrations/fc06_family_entitlement_lifecycle_audit.py')
    assert 'apply_upgrade_to_family' in billing
    assert "SET seat='member'" in plan_change
    assert 'stage_family_to_individual_downgrade' in plan_change
    assert "pending_seat_assignments JSONB" in migration
    assert 'up to two distinct Guardians' in plan_change
    assert 'downgrade_effective' in read('app/services/family_circle_billing_contract.py')


def test_downgrade_is_not_exposed_as_unverified_app_callback():
    api = read('app/api/family_circle_phase6.py')
    billing = read('app/services/family_circle_entitlement_service.py')
    assert 'downgrade_effective' in billing
    assert 'downgrade_effective' not in api
    assert 'payment-success' not in api


def test_v2_former_canonical_members_cannot_reenter_legacy_fallback():
    src = read('app/services/family_circle_runtime_authority.py')
    assert 'canonical_membership_state' in src
    assert 'return "former"' in src
    assert 'former_family_circle_member' in src
    assert 'state == "legacy"' in src


def test_v2_live_risk_requires_location_separately_from_ai_and_history_uses_history_gate():
    live = read('app/api/guardian_live.py')
    guardian = read('app/api/guardian.py')
    assert 'ACTION_VIEW_AI_PROFILE, ACTION_VIEW_LOCATION' in live
    assert 'list(child_ids), ACTION_VIEW_AI_PROFILE' in live
    assert 'list(child_ids), ACTION_VIEW_LOCATION' in live
    assert 'ACTION_VIEW_LOCATION_HISTORY' in guardian
    assert 'action=ACTION_VIEW_LOCATION_HISTORY' in guardian


def test_v2_sse_and_legacy_producers_reauthorize_canonical_authority():
    stream = read('app/api/stream.py')
    safety = read('app/api/safety_events.py')
    wearable = read('app/api/health_signals.py')
    guardian_mode = read('app/services/guardian_mode_engine.py')
    assert '_family_event_allowed' in stream and 'record_disclosure=True' in stream
    assert 'ACTION_PRODUCE_LOCATION' in safety and 'runtime_decision' in safety
    assert 'ACTION_PRODUCE_WEARABLE' in wearable and 'runtime_decision' in wearable
    assert 'location_recipient_ids' in guardian_mode


def test_v2_canonical_consent_is_current_notice_and_privacy_withdrawal_fail_closed():
    runtime = read('app/services/family_circle_runtime_authority.py')
    consent = read('app/services/family_circle_consent_service.py')
    api = read('app/api/consents.py')
    assert 'CURRENT_FAMILY_NOTICE_VERSION' in runtime
    assert 'notice_version=:notice_version' in runtime
    assert 'record_self_consent' in consent
    assert 'sync_legacy_withdrawal' in consent
    assert 'sync_legacy_withdrawal' in api


def test_v2_owner_invariant_is_preserved_by_role_and_downgrade_primitives():
    life = read('app/services/family_circle_lifecycle_service.py')
    plans = read('app/services/family_circle_plan_change_service.py')
    assert 'owner_cannot_be_co_admin' in life
    assert 'owner_cannot_be_removed' in life
    assert 'The Owner must remain in the circle' in plans
    assert 'Stored downgrade selection would remove the Owner' in plans


def test_v2_age18_bridge_is_birthday_anchored_and_purpose_complete():
    src = read('app/services/family_circle_age_transition.py')
    assert 'birthday_at = birthday_instant_utc' in src
    assert 'due_at = birthday_at + timedelta(days=BRIDGE_DAYS)' in src
    assert 'FAMILY_CONSENT_PURPOSES.issubset(decided)' in src
    assert 'missing_purposes' in src


def test_v2_fc04_fc05_fc06_are_real_alembic_revisions():
    for rel, revision, parent in (
        ('migrations/versions/fc04_family_consent_authority.py', 'fc04_family_consent_authority', 'fc03_circle_plan_seat_trial'),
        ('migrations/versions/fc05_family_onboarding_invites.py', 'fc05_family_onboarding_invites', 'fc04_family_consent_authority'),
        ('migrations/versions/fc06_family_entitlement_lifecycle_audit.py', 'fc06_family_entitlement_lifecycle_audit', 'fc05_family_onboarding_invites'),
    ):
        src = read(rel)
        assert f'revision = "{revision}"' in src
        assert f'down_revision = "{parent}"' in src
        assert 'def upgrade()' in src and 'def downgrade()' in src


def test_v2_who_viewed_supports_non_member_viewers_and_pagination():
    audit = read('app/services/family_circle_audit_service.py')
    api = read('app/api/family_circle_phase6.py')
    sharing = read('app/api/location_sharing.py')
    assert 'viewer_kind' in audit and 'public_link' in audit and 'staff' in audit and 'emergency' in audit
    assert 'LIMIT :limit OFFSET :offset' in audit
    assert 'has_more' in api
    assert 'viewer_kind="public_link"' in sharing


def test_v2_minor_invite_public_path_is_fail_closed_until_verified_stepup_exists():
    api = read('app/api/family_circle_onboarding.py')
    invite = read('app/services/family_circle_invite_service.py')
    assert 'Adding a Minor is temporarily unavailable' in api
    assert 'Minor invite creation requires verified parental consent and step-up verification' in invite


def test_v2_notifications_are_post_commit_and_automatic_resume_is_audited():
    api = read('app/api/family_circle_phase6.py')
    runtime = read('app/services/family_circle_runtime_authority.py')
    outbox = read('app/services/family_circle_notification_outbox.py')
    assert 'await session.commit()' in api and 'deliver_pause_notification' in api
    assert 'sharing_resumed' in runtime and 'automatic' in runtime
    assert 'family_notification_outbox' in outbox


def test_v2_live_gateway_remains_absent():
    roots = [
        read('app/services/family_circle_billing_contract.py'),
        read('app/services/family_circle_entitlement_service.py'),
        read('app/api/family_circle_phase6.py'),
    ]
    joined = '\n'.join(roots).lower()
    assert 'import razorpay' not in joined
    assert 'razorpay.client' not in joined
    assert 'checkout' not in read('app/api/family_circle_phase6.py').lower()
