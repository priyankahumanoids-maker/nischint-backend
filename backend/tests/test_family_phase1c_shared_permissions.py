from __future__ import annotations

import pytest

from app.core.family_circle_permissions import (
    ACTION_ADD_MINOR,
    ACTION_CHANGE_OTHER_ADULT_CONSENT,
    ACTION_CHANGE_OWN_CONSENT,
    ACTION_DIRECT_112,
    ACTION_INVITE_MEMBER,
    ACTION_LEAVE_CIRCLE,
    ACTION_MANAGE_BILLING,
    ACTION_MANAGE_CO_ADMIN,
    ACTION_MANAGE_OTHER_SAFETY,
    ACTION_MANAGE_OWN_SAFETY,
    ACTION_PAUSE_OWN_SHARING,
    ACTION_PRODUCE_ACTIVITY,
    ACTION_PRODUCE_AI_PROFILE,
    ACTION_PRODUCE_LOCATION,
    ACTION_PRODUCE_VOICE_DISTRESS,
    ACTION_PRODUCE_WEARABLE,
    ACTION_RECEIVE_ALERTS,
    ACTION_REMOVE_MEMBER,
    ACTION_TRANSFER_OWNERSHIP,
    ACTION_TRIGGER_SOS,
    ACTION_VIEW_AI_PROFILE,
    ACTION_VIEW_DASHBOARD,
    ACTION_VIEW_LOCATION,
    ACTION_VIEW_LOCATION_HISTORY,
    ACTION_VIEW_WEARABLE,
    ACTION_VIEW_WHO_VIEWED,
    CONSENT_AI_BEHAVIORAL,
    CONSENT_BACKGROUND_LOCATION,
    CONSENT_LOCATION,
    CONSENT_MICROPHONE,
    CONSENT_WEARABLE,
    ENTITLEMENT_ACTIVE,
    ENTITLEMENT_GRACE,
    ENTITLEMENT_LIFELINE,
    PLAN_FAMILY,
    PLAN_INDIVIDUAL,
    PLAN_TRIAL,
    SEAT_GUARDIAN,
    SEAT_MEMBER,
    SEAT_PROTECTED,
    ConsentState,
    FamilyCirclePermissionError,
    PermissionContext,
    permission_decision,
    require_permission,
)
from app.core.family_circle_roles import (
    CIRCLE_ROLE_ADULT_MEMBER,
    CIRCLE_ROLE_CO_ADMIN,
    CIRCLE_ROLE_MINOR,
    CIRCLE_ROLE_OWNER,
)


def consents(*purposes: str) -> ConsentState:
    return ConsentState({purpose: True for purpose in purposes})


def ctx(
    *,
    actor_role=CIRCLE_ROLE_ADULT_MEMBER,
    actor_seat=SEAT_MEMBER,
    plan=PLAN_FAMILY,
    entitlement=ENTITLEMENT_ACTIVE,
    actor_consent=None,
    target_role=None,
    target_seat=None,
    target_consent=None,
    target_user_id=None,
    same_circle=True,
):
    return PermissionContext(
        actor_user_id="actor",
        actor_role=actor_role,
        actor_seat=actor_seat,
        plan=plan,
        entitlement=entitlement,
        same_circle=same_circle,
        actor_consent=actor_consent or ConsentState(),
        target_user_id=target_user_id,
        target_role=target_role,
        target_seat=target_seat,
        target_consent=target_consent or ConsentState(),
    )


def allowed(context, action):
    return permission_decision(context, action).allowed


def test_default_deny_and_invalid_context_are_fail_closed():
    base = ctx()
    assert not allowed(base, "invented_action")
    assert not allowed(ctx(plan="legacy"), ACTION_VIEW_DASHBOARD)
    assert not allowed(ctx(entitlement="unknown"), ACTION_VIEW_DASHBOARD)
    assert not allowed(ctx(plan=PLAN_FAMILY, actor_seat=SEAT_GUARDIAN), ACTION_VIEW_DASHBOARD)
    assert not allowed(ctx(same_circle=False), ACTION_VIEW_DASHBOARD)

    with pytest.raises(FamilyCirclePermissionError):
        require_permission(base, "invented_action")


def test_role_matrix_owner_coadmin_adult_minor():
    owner = ctx(actor_role=CIRCLE_ROLE_OWNER)
    coadmin = ctx(actor_role=CIRCLE_ROLE_CO_ADMIN)
    adult = ctx(actor_role=CIRCLE_ROLE_ADULT_MEMBER)
    minor = ctx(actor_role=CIRCLE_ROLE_MINOR)

    assert allowed(owner, ACTION_MANAGE_BILLING)
    assert not allowed(coadmin, ACTION_MANAGE_BILLING)
    assert not allowed(adult, ACTION_MANAGE_BILLING)
    assert not allowed(minor, ACTION_MANAGE_BILLING)

    assert allowed(owner, ACTION_TRANSFER_OWNERSHIP)
    assert allowed(owner, ACTION_MANAGE_CO_ADMIN)
    assert not allowed(coadmin, ACTION_TRANSFER_OWNERSHIP)
    assert not allowed(coadmin, ACTION_MANAGE_CO_ADMIN)

    assert allowed(owner, ACTION_INVITE_MEMBER)
    assert allowed(coadmin, ACTION_INVITE_MEMBER)
    assert not allowed(adult, ACTION_INVITE_MEMBER)
    assert not allowed(minor, ACTION_INVITE_MEMBER)

    assert allowed(owner, ACTION_ADD_MINOR)
    assert allowed(coadmin, ACTION_ADD_MINOR)
    assert not allowed(adult, ACTION_ADD_MINOR)
    assert not allowed(minor, ACTION_ADD_MINOR)

    target_kwargs = dict(
        target_user_id="target",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_MEMBER,
    )
    assert allowed(ctx(actor_role=CIRCLE_ROLE_OWNER, **target_kwargs), ACTION_MANAGE_OTHER_SAFETY)
    assert allowed(ctx(actor_role=CIRCLE_ROLE_CO_ADMIN, **target_kwargs), ACTION_MANAGE_OTHER_SAFETY)
    assert not allowed(ctx(actor_role=CIRCLE_ROLE_ADULT_MEMBER, **target_kwargs), ACTION_MANAGE_OTHER_SAFETY)
    assert not allowed(ctx(actor_role=CIRCLE_ROLE_MINOR, **target_kwargs), ACTION_MANAGE_OTHER_SAFETY)

    assert allowed(owner, ACTION_MANAGE_OWN_SAFETY)
    assert allowed(coadmin, ACTION_MANAGE_OWN_SAFETY)
    assert allowed(adult, ACTION_MANAGE_OWN_SAFETY)
    assert not allowed(minor, ACTION_MANAGE_OWN_SAFETY)


def test_remove_member_matrix_blocks_coadmin_from_owner():
    owner_removes_any = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        target_user_id="target",
        target_role=CIRCLE_ROLE_CO_ADMIN,
        target_seat=SEAT_MEMBER,
    )
    assert allowed(owner_removes_any, ACTION_REMOVE_MEMBER)

    coadmin_removes_adult = ctx(
        actor_role=CIRCLE_ROLE_CO_ADMIN,
        target_user_id="target",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_MEMBER,
    )
    assert allowed(coadmin_removes_adult, ACTION_REMOVE_MEMBER)

    coadmin_removes_owner = ctx(
        actor_role=CIRCLE_ROLE_CO_ADMIN,
        target_user_id="target",
        target_role=CIRCLE_ROLE_OWNER,
        target_seat=SEAT_MEMBER,
    )
    assert not allowed(coadmin_removes_owner, ACTION_REMOVE_MEMBER)

    adult_removes = ctx(
        actor_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_user_id="target",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_MEMBER,
    )
    assert not allowed(adult_removes, ACTION_REMOVE_MEMBER)


def test_no_one_can_change_another_adults_consent_and_minor_self_admin_is_blocked():
    for role in (CIRCLE_ROLE_OWNER, CIRCLE_ROLE_CO_ADMIN, CIRCLE_ROLE_ADULT_MEMBER):
        c = ctx(
            actor_role=role,
            target_user_id="target",
            target_role=CIRCLE_ROLE_ADULT_MEMBER,
            target_seat=SEAT_MEMBER,
        )
        assert not allowed(c, ACTION_CHANGE_OTHER_ADULT_CONSENT)
        assert allowed(ctx(actor_role=role), ACTION_CHANGE_OWN_CONSENT)
        assert allowed(ctx(actor_role=role), ACTION_PAUSE_OWN_SHARING)

    assert not allowed(ctx(actor_role=CIRCLE_ROLE_MINOR), ACTION_CHANGE_OWN_CONSENT)
    assert not allowed(ctx(actor_role=CIRCLE_ROLE_MINOR), ACTION_PAUSE_OWN_SHARING)
    assert not allowed(ctx(actor_role=CIRCLE_ROLE_MINOR), ACTION_LEAVE_CIRCLE)


def test_leave_rules_preserve_owner_transfer_requirement():
    assert not allowed(ctx(actor_role=CIRCLE_ROLE_OWNER), ACTION_LEAVE_CIRCLE)
    assert allowed(ctx(actor_role=CIRCLE_ROLE_CO_ADMIN), ACTION_LEAVE_CIRCLE)
    assert allowed(ctx(actor_role=CIRCLE_ROLE_ADULT_MEMBER), ACTION_LEAVE_CIRCLE)
    assert not allowed(ctx(actor_role=CIRCLE_ROLE_MINOR), ACTION_LEAVE_CIRCLE)


def test_individual_and_trial_visibility_is_strictly_one_way():
    for plan in (PLAN_TRIAL, PLAN_INDIVIDUAL):
        guardian_to_protected = ctx(
            actor_role=CIRCLE_ROLE_OWNER,
            actor_seat=SEAT_GUARDIAN,
            plan=plan,
            target_user_id="protected",
            target_role=CIRCLE_ROLE_ADULT_MEMBER,
            target_seat=SEAT_PROTECTED,
            target_consent=consents(CONSENT_LOCATION, CONSENT_BACKGROUND_LOCATION),
        )
        assert allowed(guardian_to_protected, ACTION_VIEW_LOCATION)
        assert allowed(guardian_to_protected, ACTION_VIEW_LOCATION_HISTORY)

        protected_to_guardian = ctx(
            actor_role=CIRCLE_ROLE_ADULT_MEMBER,
            actor_seat=SEAT_PROTECTED,
            plan=plan,
            target_user_id="guardian",
            target_role=CIRCLE_ROLE_OWNER,
            target_seat=SEAT_GUARDIAN,
            target_consent=consents(CONSENT_LOCATION),
        )
        assert not allowed(protected_to_guardian, ACTION_VIEW_LOCATION)

        guardian_produces = ctx(
            actor_role=CIRCLE_ROLE_OWNER,
            actor_seat=SEAT_GUARDIAN,
            plan=plan,
            actor_consent=consents(
                CONSENT_LOCATION,
                CONSENT_BACKGROUND_LOCATION,
                CONSENT_AI_BEHAVIORAL,
            ),
        )
        assert not allowed(guardian_produces, ACTION_PRODUCE_LOCATION)
        assert not allowed(guardian_produces, ACTION_PRODUCE_ACTIVITY)
        assert not allowed(guardian_produces, ACTION_PRODUCE_AI_PROFILE)


def test_family_visibility_is_mutual_but_consent_is_still_required():
    visible = ctx(
        actor_role=CIRCLE_ROLE_ADULT_MEMBER,
        actor_seat=SEAT_MEMBER,
        plan=PLAN_FAMILY,
        target_user_id="other",
        target_role=CIRCLE_ROLE_OWNER,
        target_seat=SEAT_MEMBER,
        target_consent=consents(CONSENT_LOCATION, CONSENT_AI_BEHAVIORAL, CONSENT_WEARABLE),
    )
    assert allowed(visible, ACTION_VIEW_LOCATION)
    assert not allowed(visible, ACTION_VIEW_LOCATION_HISTORY)
    assert allowed(visible, ACTION_VIEW_AI_PROFILE)
    assert allowed(visible, ACTION_VIEW_WEARABLE)

    no_consent = ctx(
        target_user_id="other",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_MEMBER,
    )
    assert not allowed(no_consent, ACTION_VIEW_LOCATION)
    assert not allowed(no_consent, ACTION_VIEW_AI_PROFILE)
    assert not allowed(no_consent, ACTION_VIEW_WEARABLE)


def test_minors_are_location_only_and_never_ai_voice_activity_or_wearable():
    minor = ctx(
        actor_role=CIRCLE_ROLE_MINOR,
        actor_seat=SEAT_MEMBER,
        plan=PLAN_FAMILY,
        actor_consent=consents(
            CONSENT_LOCATION,
            CONSENT_BACKGROUND_LOCATION,
            CONSENT_AI_BEHAVIORAL,
            CONSENT_MICROPHONE,
            CONSENT_WEARABLE,
        ),
    )
    assert allowed(minor, ACTION_PRODUCE_LOCATION)
    assert not allowed(minor, ACTION_PRODUCE_ACTIVITY)
    assert not allowed(minor, ACTION_PRODUCE_AI_PROFILE)
    assert not allowed(minor, ACTION_PRODUCE_VOICE_DISTRESS)
    assert not allowed(minor, ACTION_PRODUCE_WEARABLE)

    viewer = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        target_user_id="child",
        target_role=CIRCLE_ROLE_MINOR,
        target_seat=SEAT_MEMBER,
        target_consent=consents(
            CONSENT_LOCATION,
            CONSENT_AI_BEHAVIORAL,
            CONSENT_WEARABLE,
        ),
    )
    assert allowed(viewer, ACTION_VIEW_LOCATION)
    assert not allowed(viewer, ACTION_VIEW_AI_PROFILE)
    assert not allowed(viewer, ACTION_VIEW_WEARABLE)


def test_lifeline_keeps_emergency_billing_and_privacy_self_service_only():
    lifeline_owner = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        entitlement=ENTITLEMENT_LIFELINE,
    )
    assert allowed(lifeline_owner, ACTION_TRIGGER_SOS)
    assert allowed(lifeline_owner, ACTION_DIRECT_112)
    assert allowed(lifeline_owner, ACTION_RECEIVE_ALERTS)
    assert allowed(lifeline_owner, ACTION_MANAGE_BILLING)
    assert allowed(lifeline_owner, ACTION_CHANGE_OWN_CONSENT)
    assert allowed(lifeline_owner, ACTION_PAUSE_OWN_SHARING)

    assert not allowed(lifeline_owner, ACTION_VIEW_DASHBOARD)
    assert not allowed(lifeline_owner, ACTION_INVITE_MEMBER)

    # Leaving is an at-any-time lifecycle/privacy escape hatch for non-Owners.
    lifeline_adult = ctx(
        actor_role=CIRCLE_ROLE_ADULT_MEMBER,
        entitlement=ENTITLEMENT_LIFELINE,
    )
    assert allowed(lifeline_adult, ACTION_LEAVE_CIRCLE)

    lifeline_view = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        entitlement=ENTITLEMENT_LIFELINE,
        target_user_id="other",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_MEMBER,
        target_consent=consents(CONSENT_LOCATION),
    )
    assert not allowed(lifeline_view, ACTION_VIEW_LOCATION)


def test_grace_keeps_full_features_before_lifeline():
    grace = ctx(
        actor_role=CIRCLE_ROLE_CO_ADMIN,
        entitlement=ENTITLEMENT_GRACE,
    )
    assert allowed(grace, ACTION_INVITE_MEMBER)
    assert allowed(grace, ACTION_VIEW_DASHBOARD)


def test_consent_gates_each_tracked_data_purpose():
    adult = ctx(
        actor_role=CIRCLE_ROLE_ADULT_MEMBER,
        actor_seat=SEAT_MEMBER,
        plan=PLAN_FAMILY,
        actor_consent=consents(
            CONSENT_LOCATION,
            CONSENT_BACKGROUND_LOCATION,
            CONSENT_AI_BEHAVIORAL,
            CONSENT_MICROPHONE,
            CONSENT_WEARABLE,
        ),
    )
    assert allowed(adult, ACTION_PRODUCE_LOCATION)
    assert allowed(adult, ACTION_PRODUCE_ACTIVITY)
    assert allowed(adult, ACTION_PRODUCE_AI_PROFILE)
    assert allowed(adult, ACTION_PRODUCE_VOICE_DISTRESS)
    assert allowed(adult, ACTION_PRODUCE_WEARABLE)

    missing = ctx(actor_role=CIRCLE_ROLE_ADULT_MEMBER)
    assert not allowed(missing, ACTION_PRODUCE_LOCATION)
    assert not allowed(missing, ACTION_PRODUCE_ACTIVITY)
    assert not allowed(missing, ACTION_PRODUCE_AI_PROFILE)
    assert not allowed(missing, ACTION_PRODUCE_VOICE_DISTRESS)
    assert not allowed(missing, ACTION_PRODUCE_WEARABLE)


def test_cross_circle_target_access_is_refused_before_visibility_or_consent():
    c = ctx(
        same_circle=False,
        target_user_id="other",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_MEMBER,
        target_consent=consents(CONSENT_LOCATION),
    )
    decision = permission_decision(c, ACTION_VIEW_LOCATION)
    assert not decision.allowed
    assert decision.code == "different_circle"



def test_untracked_individual_guardian_cannot_configure_or_pause_tracking_for_self_or_untracked_target():
    guardian = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        actor_seat=SEAT_GUARDIAN,
        plan=PLAN_INDIVIDUAL,
    )
    assert not allowed(guardian, ACTION_MANAGE_OWN_SAFETY)
    assert not allowed(guardian, ACTION_PAUSE_OWN_SHARING)

    target_guardian = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        actor_seat=SEAT_GUARDIAN,
        plan=PLAN_INDIVIDUAL,
        target_user_id="co-guardian",
        target_role=CIRCLE_ROLE_CO_ADMIN,
        target_seat=SEAT_GUARDIAN,
    )
    assert not allowed(target_guardian, ACTION_MANAGE_OTHER_SAFETY)

    target_protected = ctx(
        actor_role=CIRCLE_ROLE_OWNER,
        actor_seat=SEAT_GUARDIAN,
        plan=PLAN_INDIVIDUAL,
        target_user_id="protected",
        target_role=CIRCLE_ROLE_ADULT_MEMBER,
        target_seat=SEAT_PROTECTED,
    )
    assert allowed(target_protected, ACTION_MANAGE_OTHER_SAFETY)


def test_who_viewed_role_matrix_is_available_only_with_full_entitlement():
    for role in (CIRCLE_ROLE_OWNER, CIRCLE_ROLE_CO_ADMIN, CIRCLE_ROLE_ADULT_MEMBER, CIRCLE_ROLE_MINOR):
        assert allowed(ctx(actor_role=role), ACTION_VIEW_WHO_VIEWED)
        assert not allowed(ctx(actor_role=role, entitlement=ENTITLEMENT_LIFELINE), ACTION_VIEW_WHO_VIEWED)


def test_minor_guardian_seat_is_invalid_under_trial_or_individual():
    c = ctx(
        actor_role=CIRCLE_ROLE_MINOR,
        actor_seat=SEAT_GUARDIAN,
        plan=PLAN_INDIVIDUAL,
    )
    decision = permission_decision(c, ACTION_TRIGGER_SOS)
    assert not decision.allowed
    assert decision.code == "minor_cannot_be_guardian_seat"


def test_permission_engine_stays_pure_and_separate_from_legacy_auth_and_db_layers():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "core" / "family_circle_permissions.py").read_text(encoding="utf-8")
    assert "subscription_service" not in source
    assert "product_roles" not in source
    assert "HTTPException" not in source
    assert "sqlalchemy" not in source
    assert "guardian_relationships" not in source
    assert "relationships" not in source
