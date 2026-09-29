"""Shared deny-by-default Family Circle v1.0 permission engine.

Phase 1C centralises the product-policy decision only.  It deliberately does
not query legacy relationship tables or expose HTTP endpoints.  Later phases
must build every Family Circle endpoint on this module rather than duplicating
role/plan/seat/consent/entitlement checks.

The four independent policy dimensions remain separate:
* role        -> administrative control inside the Circle
* plan/seat   -> who is tracked and who can see whom
* consent     -> which data purposes the tracked person has allowed
* entitlement -> whether ordinary paid/trial features are currently available

Unknown or internally inconsistent inputs are denied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.core.family_circle_roles import (
    CIRCLE_ROLE_ADULT_MEMBER,
    CIRCLE_ROLE_CO_ADMIN,
    CIRCLE_ROLE_MINOR,
    CIRCLE_ROLE_OWNER,
    CIRCLE_ROLES,
)

# Canonical Family Circle v1.0 plan vocabulary.
PLAN_TRIAL = "trial"
PLAN_INDIVIDUAL = "individual"
PLAN_FAMILY = "family"
PLANS = frozenset({PLAN_TRIAL, PLAN_INDIVIDUAL, PLAN_FAMILY})

# Seat is intentionally independent from administrative role.
SEAT_PROTECTED = "protected"
SEAT_GUARDIAN = "guardian"
SEAT_MEMBER = "member"  # Family plan: every member is mutually tracked/visible.
SEATS = frozenset({SEAT_PROTECTED, SEAT_GUARDIAN, SEAT_MEMBER})

# Entitlement is independent from the selected plan.  Trial/paid/grace use
# ordinary features; Lifeline keeps emergency and privacy-self-service only.
ENTITLEMENT_ACTIVE = "active"
ENTITLEMENT_GRACE = "grace"
ENTITLEMENT_LIFELINE = "lifeline"
ENTITLEMENTS = frozenset(
    {ENTITLEMENT_ACTIVE, ENTITLEMENT_GRACE, ENTITLEMENT_LIFELINE}
)
FULL_FEATURE_ENTITLEMENTS = frozenset({ENTITLEMENT_ACTIVE, ENTITLEMENT_GRACE})

# Granular consent purposes from Family Circle Spec v1.0 section 4.
CONSENT_LOCATION = "location"
CONSENT_BACKGROUND_LOCATION = "background_location"
CONSENT_AI_BEHAVIORAL = "ai_behavioral_monitoring"
CONSENT_MICROPHONE = "microphone"
CONSENT_WEARABLE = "wearable"
CONSENT_PURPOSES = frozenset(
    {
        CONSENT_LOCATION,
        CONSENT_BACKGROUND_LOCATION,
        CONSENT_AI_BEHAVIORAL,
        CONSENT_MICROPHONE,
        CONSENT_WEARABLE,
    }
)

# Shared action vocabulary.  Endpoints added later should depend on these
# decisions instead of embedding their own role/plan/seat checks.
ACTION_MANAGE_BILLING = "manage_billing"
ACTION_TRANSFER_OWNERSHIP = "transfer_ownership"
ACTION_MANAGE_CO_ADMIN = "manage_co_admin"
ACTION_INVITE_MEMBER = "invite_member"
ACTION_REMOVE_MEMBER = "remove_member"
ACTION_ADD_MINOR = "add_minor"
ACTION_MANAGE_OTHER_SAFETY = "manage_other_safety"
ACTION_MANAGE_OWN_SAFETY = "manage_own_safety"
ACTION_CHANGE_OWN_CONSENT = "change_own_consent"
ACTION_CHANGE_OTHER_ADULT_CONSENT = "change_other_adult_consent"
ACTION_PAUSE_OWN_SHARING = "pause_own_sharing"
ACTION_LEAVE_CIRCLE = "leave_circle"
ACTION_TRIGGER_SOS = "trigger_sos"
ACTION_DIRECT_112 = "direct_112"
ACTION_RECEIVE_ALERTS = "receive_alerts"
ACTION_VIEW_WHO_VIEWED = "view_who_viewed"
ACTION_VIEW_DASHBOARD = "view_dashboard"
ACTION_VIEW_LOCATION = "view_location"
ACTION_VIEW_LOCATION_HISTORY = "view_location_history"
ACTION_VIEW_AI_PROFILE = "view_ai_profile"
ACTION_VIEW_ACTIVITY = "view_activity"
ACTION_VIEW_WEARABLE = "view_wearable"
ACTION_PRODUCE_LOCATION = "produce_location"
ACTION_PRODUCE_AI_PROFILE = "produce_ai_profile"
ACTION_PRODUCE_ACTIVITY = "produce_activity"
ACTION_PRODUCE_VOICE_DISTRESS = "produce_voice_distress"
ACTION_PRODUCE_WEARABLE = "produce_wearable"

ACTIONS = frozenset(
    {
        ACTION_MANAGE_BILLING,
        ACTION_TRANSFER_OWNERSHIP,
        ACTION_MANAGE_CO_ADMIN,
        ACTION_INVITE_MEMBER,
        ACTION_REMOVE_MEMBER,
        ACTION_ADD_MINOR,
        ACTION_MANAGE_OTHER_SAFETY,
        ACTION_MANAGE_OWN_SAFETY,
        ACTION_CHANGE_OWN_CONSENT,
        ACTION_CHANGE_OTHER_ADULT_CONSENT,
        ACTION_PAUSE_OWN_SHARING,
        ACTION_LEAVE_CIRCLE,
        ACTION_TRIGGER_SOS,
        ACTION_DIRECT_112,
        ACTION_RECEIVE_ALERTS,
        ACTION_VIEW_WHO_VIEWED,
        ACTION_VIEW_DASHBOARD,
        ACTION_VIEW_LOCATION,
        ACTION_VIEW_LOCATION_HISTORY,
        ACTION_VIEW_AI_PROFILE,
        ACTION_VIEW_ACTIVITY,
        ACTION_VIEW_WEARABLE,
        ACTION_PRODUCE_LOCATION,
        ACTION_PRODUCE_AI_PROFILE,
        ACTION_PRODUCE_ACTIVITY,
        ACTION_PRODUCE_VOICE_DISTRESS,
        ACTION_PRODUCE_WEARABLE,
    }
)


class FamilyCirclePermissionError(PermissionError):
    """Raised by ``require_permission`` for a denied Family Circle action."""


@dataclass(frozen=True)
class ConsentState:
    """Canonical consent snapshot for the target/tracked person.

    Phase 3 will map persisted DPDP consent records into this shape.  Missing
    purposes are false by default; no caller can gain access by omitting data.
    """

    values: Mapping[str, bool] = field(default_factory=dict)

    def granted(self, purpose: str) -> bool:
        return purpose in CONSENT_PURPOSES and self.values.get(purpose) is True


@dataclass(frozen=True)
class PermissionContext:
    actor_user_id: str
    actor_role: str
    actor_seat: str
    plan: str
    entitlement: str
    same_circle: bool = True
    actor_consent: ConsentState = field(default_factory=ConsentState)
    target_user_id: str | None = None
    target_role: str | None = None
    target_seat: str | None = None
    target_consent: ConsentState = field(default_factory=ConsentState)

    @property
    def target_is_self(self) -> bool:
        return self.target_user_id is not None and self.target_user_id == self.actor_user_id


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    code: str


_ALLOW = PermissionDecision(True, "allowed")


def _deny(code: str) -> PermissionDecision:
    return PermissionDecision(False, code)


def _valid_plan_seat(plan: str, seat: str) -> bool:
    if plan in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        return seat in {SEAT_PROTECTED, SEAT_GUARDIAN}
    if plan == PLAN_FAMILY:
        return seat == SEAT_MEMBER
    return False


def _base_context_error(ctx: PermissionContext, *, needs_target: bool) -> str | None:
    if ctx.actor_role not in CIRCLE_ROLES:
        return "invalid_actor_role"
    if ctx.plan not in PLANS:
        return "invalid_plan"
    if ctx.entitlement not in ENTITLEMENTS:
        return "invalid_entitlement"
    if not _valid_plan_seat(ctx.plan, ctx.actor_seat):
        return "invalid_actor_seat_for_plan"
    if not ctx.same_circle:
        return "different_circle"

    # A Minor can never be a Guardian seat.  Family uses the neutral member seat.
    if ctx.actor_role == CIRCLE_ROLE_MINOR and ctx.actor_seat == SEAT_GUARDIAN:
        return "minor_cannot_be_guardian_seat"

    if needs_target:
        if not ctx.target_user_id or ctx.target_role not in CIRCLE_ROLES:
            return "missing_or_invalid_target"
        if ctx.target_seat is None or not _valid_plan_seat(ctx.plan, ctx.target_seat):
            return "invalid_target_seat_for_plan"
        if ctx.target_role == CIRCLE_ROLE_MINOR and ctx.target_seat == SEAT_GUARDIAN:
            return "minor_cannot_be_guardian_seat"

    return None


def _full_entitlement(ctx: PermissionContext) -> bool:
    return ctx.entitlement in FULL_FEATURE_ENTITLEMENTS


def _tracked(plan: str, seat: str) -> bool:
    if plan in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        return seat == SEAT_PROTECTED
    if plan == PLAN_FAMILY:
        return seat == SEAT_MEMBER
    return False


def _can_see_target(ctx: PermissionContext) -> bool:
    """Plan/seat visibility only; consent/feature type is checked separately."""
    if ctx.target_is_self:
        return True
    if ctx.plan in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        return ctx.actor_seat == SEAT_GUARDIAN and ctx.target_seat == SEAT_PROTECTED
    if ctx.plan == PLAN_FAMILY:
        return ctx.actor_seat == SEAT_MEMBER and ctx.target_seat == SEAT_MEMBER
    return False


def _target_consent(ctx: PermissionContext, purpose: str) -> bool:
    return ctx.target_consent.granted(purpose)


def _actor_consent(ctx: PermissionContext, purpose: str) -> bool:
    return ctx.actor_consent.granted(purpose)


def permission_decision(ctx: PermissionContext, action: str) -> PermissionDecision:
    """Return the canonical permission decision for one Family Circle action.

    The function is deny-by-default: unsupported action values, missing target
    context, invalid plan/seat combinations, cross-circle access and missing
    required consent are all denied.
    """
    if action not in ACTIONS:
        return _deny("unknown_action")

    target_actions = {
        ACTION_REMOVE_MEMBER,
        ACTION_MANAGE_OTHER_SAFETY,
        ACTION_CHANGE_OTHER_ADULT_CONSENT,
        ACTION_VIEW_LOCATION,
        ACTION_VIEW_LOCATION_HISTORY,
        ACTION_VIEW_AI_PROFILE,
        ACTION_VIEW_ACTIVITY,
        ACTION_VIEW_WEARABLE,
    }
    err = _base_context_error(ctx, needs_target=action in target_actions)
    if err:
        return _deny(err)

    role = ctx.actor_role
    full = _full_entitlement(ctx)

    # Emergency paths remain available in Lifeline mode.
    if action in {ACTION_TRIGGER_SOS, ACTION_DIRECT_112, ACTION_RECEIVE_ALERTS}:
        return _ALLOW

    # Privacy self-service is never blocked by subscription state.  Minors do
    # not self-administer consent/sharing under the v1.0 rules.
    if action == ACTION_CHANGE_OWN_CONSENT:
        return _ALLOW if role != CIRCLE_ROLE_MINOR else _deny("minor_self_consent_forbidden")
    if action == ACTION_CHANGE_OTHER_ADULT_CONSENT:
        return _deny("another_adult_controls_own_consent")
    if action == ACTION_PAUSE_OWN_SHARING:
        if role == CIRCLE_ROLE_MINOR:
            return _deny("minor_pause_forbidden")
        return _ALLOW if _tracked(ctx.plan, ctx.actor_seat) else _deny("seat_not_tracked")

    # Section 4 says an adult (except the Owner) may leave at any time.
    # Subscription/Lifeline state must not trap a person in a Circle.
    if action == ACTION_LEAVE_CIRCLE:
        if role == CIRCLE_ROLE_OWNER:
            return _deny("owner_must_transfer_or_cancel")
        return _ALLOW if role != CIRCLE_ROLE_MINOR else _deny("minor_leave_forbidden")

    # Owner must still be able to restore/inspect billing in Lifeline mode.
    if action == ACTION_MANAGE_BILLING:
        return _ALLOW if role == CIRCLE_ROLE_OWNER else _deny("owner_only_billing")

    # Ordinary features are locked in Lifeline mode.
    if not full:
        return _deny("lifeline_locked")

    if action in {ACTION_TRANSFER_OWNERSHIP, ACTION_MANAGE_CO_ADMIN}:
        return _ALLOW if role == CIRCLE_ROLE_OWNER else _deny("owner_only")

    if action == ACTION_INVITE_MEMBER:
        return _ALLOW if role in {CIRCLE_ROLE_OWNER, CIRCLE_ROLE_CO_ADMIN} else _deny("admin_only_invite")

    if action == ACTION_ADD_MINOR:
        # Parental/lawful-guardian verification is a separate Phase 3 input;
        # role permission alone is necessary but not sufficient.
        return _ALLOW if role in {CIRCLE_ROLE_OWNER, CIRCLE_ROLE_CO_ADMIN} else _deny("admin_only_add_minor")

    if action == ACTION_REMOVE_MEMBER:
        if role == CIRCLE_ROLE_OWNER:
            return _ALLOW
        if role == CIRCLE_ROLE_CO_ADMIN and ctx.target_role != CIRCLE_ROLE_OWNER:
            return _ALLOW
        return _deny("remove_not_allowed")

    if action == ACTION_MANAGE_OTHER_SAFETY:
        if role not in {CIRCLE_ROLE_OWNER, CIRCLE_ROLE_CO_ADMIN}:
            return _deny("admin_only_safety_config")
        return _ALLOW if _tracked(ctx.plan, ctx.target_seat or "") else _deny("target_seat_not_tracked")

    if action == ACTION_MANAGE_OWN_SAFETY:
        if role == CIRCLE_ROLE_MINOR:
            return _deny("minor_settings_forbidden")
        return _ALLOW if _tracked(ctx.plan, ctx.actor_seat) else _deny("seat_not_tracked")

    if action == ACTION_VIEW_WHO_VIEWED:
        return _ALLOW

    if action == ACTION_VIEW_DASHBOARD:
        return _ALLOW

    # Producer gates prevent Individual/Trial Guardians from generating tracked
    # data even if OS permissions happen to be granted on their device.
    if action == ACTION_PRODUCE_LOCATION:
        if not _tracked(ctx.plan, ctx.actor_seat):
            return _deny("seat_not_tracked")
        return _ALLOW if _actor_consent(ctx, CONSENT_LOCATION) else _deny("location_consent_required")

    if action == ACTION_PRODUCE_ACTIVITY:
        if not _tracked(ctx.plan, ctx.actor_seat):
            return _deny("seat_not_tracked")
        if role == CIRCLE_ROLE_MINOR:
            # v1.0 limits minors to live location, zones, SOS and alerts.
            return _deny("minor_activity_forbidden")
        return _ALLOW if _actor_consent(ctx, CONSENT_BACKGROUND_LOCATION) else _deny("background_location_consent_required")

    if action == ACTION_PRODUCE_AI_PROFILE:
        if not _tracked(ctx.plan, ctx.actor_seat):
            return _deny("seat_not_tracked")
        if role == CIRCLE_ROLE_MINOR:
            return _deny("minor_ai_forbidden")
        return _ALLOW if _actor_consent(ctx, CONSENT_AI_BEHAVIORAL) else _deny("ai_consent_required")

    if action == ACTION_PRODUCE_VOICE_DISTRESS:
        if not _tracked(ctx.plan, ctx.actor_seat):
            return _deny("seat_not_tracked")
        if role == CIRCLE_ROLE_MINOR:
            return _deny("minor_voice_forbidden")
        return _ALLOW if _actor_consent(ctx, CONSENT_MICROPHONE) else _deny("microphone_consent_required")

    if action == ACTION_PRODUCE_WEARABLE:
        if not _tracked(ctx.plan, ctx.actor_seat):
            return _deny("seat_not_tracked")
        if role == CIRCLE_ROLE_MINOR:
            return _deny("minor_wearable_forbidden")
        return _ALLOW if _actor_consent(ctx, CONSENT_WEARABLE) else _deny("wearable_consent_required")

    # Viewer gates enforce plan visibility before the underlying data query is
    # executed.  Phase 5 will translate these decisions into SQL query scope.
    if action in {
        ACTION_VIEW_LOCATION,
        ACTION_VIEW_LOCATION_HISTORY,
        ACTION_VIEW_AI_PROFILE,
        ACTION_VIEW_ACTIVITY,
        ACTION_VIEW_WEARABLE,
    }:
        if not _can_see_target(ctx):
            return _deny("target_not_visible_under_plan")
        if not _tracked(ctx.plan, ctx.target_seat or ""):
            return _deny("target_seat_not_tracked")

        if action == ACTION_VIEW_LOCATION:
            return _ALLOW if _target_consent(ctx, CONSENT_LOCATION) else _deny("location_consent_required")

        if action == ACTION_VIEW_LOCATION_HISTORY:
            if not _target_consent(ctx, CONSENT_LOCATION):
                return _deny("location_consent_required")
            return (
                _ALLOW
                if _target_consent(ctx, CONSENT_BACKGROUND_LOCATION)
                else _deny("background_location_consent_required")
            )

        if ctx.target_role == CIRCLE_ROLE_MINOR:
            if action == ACTION_VIEW_AI_PROFILE:
                return _deny("minor_ai_forbidden")
            if action == ACTION_VIEW_ACTIVITY:
                return _deny("minor_activity_forbidden")
            if action == ACTION_VIEW_WEARABLE:
                return _deny("minor_wearable_forbidden")

        purpose = {
            ACTION_VIEW_AI_PROFILE: CONSENT_AI_BEHAVIORAL,
            ACTION_VIEW_ACTIVITY: CONSENT_BACKGROUND_LOCATION,
            ACTION_VIEW_WEARABLE: CONSENT_WEARABLE,
        }[action]
        return _ALLOW if _target_consent(ctx, purpose) else _deny(f"{purpose}_consent_required")

    return _deny("default_deny")


def require_permission(ctx: PermissionContext, action: str) -> None:
    decision = permission_decision(ctx, action)
    if not decision.allowed:
        raise FamilyCirclePermissionError(decision.code)


__all__ = [name for name in globals() if name.startswith(("ACTION_", "CONSENT_", "ENTITLEMENT_", "PLAN_", "SEAT_"))] + [
    "ACTIONS",
    "PLANS",
    "SEATS",
    "ENTITLEMENTS",
    "FULL_FEATURE_ENTITLEMENTS",
    "CONSENT_PURPOSES",
    "ConsentState",
    "PermissionContext",
    "PermissionDecision",
    "FamilyCirclePermissionError",
    "permission_decision",
    "require_permission",
]
