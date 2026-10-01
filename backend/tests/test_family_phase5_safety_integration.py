from __future__ import annotations

from pathlib import Path

from app.core.family_circle_permissions import (
    ACTION_PRODUCE_AI_PROFILE,
    ACTION_PRODUCE_LOCATION,
    ACTION_PRODUCE_VOICE_DISTRESS,
    ACTION_PRODUCE_WEARABLE,
    ACTION_TRIGGER_SOS,
    ACTION_VIEW_AI_PROFILE,
    ACTION_VIEW_LOCATION,
    CONSENT_AI_BEHAVIORAL,
    CONSENT_LOCATION,
    CONSENT_MICROPHONE,
    CONSENT_WEARABLE,
    ENTITLEMENT_ACTIVE,
    ConsentState,
    PermissionContext,
    permission_decision,
)

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def ctx(*, plan="family", actor_role="adult_member", actor_seat="member", actor_consent=None,
        target_role="adult_member", target_seat="member", target_consent=None, target=True):
    return PermissionContext(
        actor_user_id="11111111-1111-1111-1111-111111111111",
        actor_role=actor_role,
        actor_seat=actor_seat,
        plan=plan,
        entitlement=ENTITLEMENT_ACTIVE,
        same_circle=True,
        actor_consent=ConsentState(actor_consent or {}),
        target_user_id="22222222-2222-2222-2222-222222222222" if target else None,
        target_role=target_role if target else None,
        target_seat=target_seat if target else None,
        target_consent=ConsentState(target_consent or {}),
    )


def test_trial_guardian_cannot_produce_location():
    decision = permission_decision(
        ctx(plan="trial", actor_role="adult_member", actor_seat="guardian",
            actor_consent={CONSENT_LOCATION: True}, target=False),
        ACTION_PRODUCE_LOCATION,
    )
    assert not decision.allowed
    assert decision.code == "seat_not_tracked"


def test_trial_guardian_can_view_protected_location_with_consent():
    decision = permission_decision(
        ctx(plan="trial", actor_role="adult_member", actor_seat="guardian",
            target_role="adult_member", target_seat="protected",
            target_consent={CONSENT_LOCATION: True}),
        ACTION_VIEW_LOCATION,
    )
    assert decision.allowed


def test_trial_protected_cannot_view_guardian_location():
    decision = permission_decision(
        ctx(plan="trial", actor_role="adult_member", actor_seat="protected",
            target_role="adult_member", target_seat="guardian",
            target_consent={CONSENT_LOCATION: True}),
        ACTION_VIEW_LOCATION,
    )
    assert not decision.allowed


def test_minor_behavioral_ai_remains_forbidden_even_with_consent():
    decision = permission_decision(
        ctx(actor_role="minor", actor_consent={CONSENT_AI_BEHAVIORAL: True}, target=False),
        ACTION_PRODUCE_AI_PROFILE,
    )
    assert not decision.allowed
    assert decision.code == "minor_ai_forbidden"


def test_minor_voice_and_wearable_remain_forbidden():
    voice = permission_decision(
        ctx(actor_role="minor", actor_consent={CONSENT_MICROPHONE: True}, target=False),
        ACTION_PRODUCE_VOICE_DISTRESS,
    )
    wearable = permission_decision(
        ctx(actor_role="minor", actor_consent={CONSENT_WEARABLE: True}, target=False),
        ACTION_PRODUCE_WEARABLE,
    )
    assert not voice.allowed and voice.code == "minor_voice_forbidden"
    assert not wearable.allowed and wearable.code == "minor_wearable_forbidden"


def test_sos_remains_available_without_ordinary_consent():
    decision = permission_decision(ctx(actor_consent={}, target=False), ACTION_TRIGGER_SOS)
    assert decision.allowed


def test_runtime_adapter_uses_shared_permission_engine_and_pause_for_views_only():
    src = read("app/services/family_circle_runtime_authority.py")
    assert "permission_decision(ctx, action)" in src
    assert "action in _VIEW_ACTIONS" in src
    assert 'RuntimeDecision(False, False, "legacy_fallback")' in src
    assert "alert_recipient_ids" in src
    assert "Phase 6 replaces this" in src


def test_runtime_endpoint_is_read_only_snapshot_surface():
    src = read("app/api/family_circle_runtime.py")
    assert '@router.get("/me")' in src
    assert "runtime_snapshot(session, user.id)" in src
    assert "@router.post" not in src


def test_dashboard_filters_location_before_returning_family_data():
    src = read("app/services/guardian_dashboard_engine.py")
    assert "plan_visible_target_ids" in src
    assert "filter_targets_for_action" in src
    assert "ACTION_VIEW_LOCATION" in src
    assert "ACTION_VIEW_LOCATION_HISTORY" in src


def test_live_guardian_surface_filters_location_and_ai_separately():
    src = read("app/api/guardian_live.py")
    assert "ACTION_VIEW_LOCATION" in src
    assert "ACTION_VIEW_AI_PROFILE" in src
    assert "filter_targets_for_action" in src


def test_geofence_location_producer_is_authorized_and_ai_learning_is_separate():
    src = read("app/api/geofence.py")
    assert "ACTION_PRODUCE_LOCATION" in src
    assert "ACTION_PRODUCE_AI_PROFILE" in src
    assert "family_ai_allowed" in src
    assert "protected_behavior_advisory" in src


def test_safe_walk_and_route_monitor_use_activity_authority():
    guardian = read("app/api/guardian.py")
    route = read("app/api/route_monitor.py")
    assert guardian.count("ACTION_PRODUCE_ACTIVITY") >= 2
    assert route.count("ACTION_PRODUCE_ACTIVITY") >= 2
    assert "ACTION_VIEW_LOCATION" in guardian


def test_alert_and_sos_scope_do_not_depend_on_ordinary_pause():
    alerts = read("app/services/alert_trigger.py")
    emergency = read("app/api/emergency.py")
    adapter = read("app/services/family_circle_runtime_authority.py")
    assert "alert_recipient_ids" in alerts
    assert "plan_visible_target_ids" in emergency
    assert "ACTION_TRIGGER_SOS" in emergency
    # Emergency fan-out is intentionally not filtered through sharing_paused.
    alert_block = adapter[adapter.index("async def alert_recipient_ids"):adapter.index("async def runtime_snapshot")]
    assert "sharing_paused" not in alert_block


def test_motion_voice_and_ai_ingestion_are_server_gated():
    motion = read("app/api/signals_motion.py") + read("app/api/motion_features.py")
    sensors = read("app/api/sensors.py")
    assert motion.count("ACTION_PRODUCE_AI_PROFILE") >= 2
    assert "ACTION_PRODUCE_VOICE_DISTRESS" in sensors
    assert "ACTION_PRODUCE_AI_PROFILE" in sensors


def test_wearable_write_and_dependent_read_are_family_authorized():
    src = read("app/api/wearable.py")
    assert "ACTION_PRODUCE_WEARABLE" in src
    assert "ACTION_VIEW_WEARABLE" in src
    assert "ACTION_MANAGE_OTHER_SAFETY" in src


def test_monitoring_policy_does_not_trust_legacy_user_role_for_canonical_family_member():
    src = read("app/services/member_monitoring_policy.py")
    assert "membership_snapshot" in src
    assert "Another adult cannot change" in src
    assert "ACTION_MANAGE_OWN_SAFETY" in src
    assert "ACTION_MANAGE_OTHER_SAFETY" in src


def test_public_tracking_link_reauthorizes_every_read_and_pause():
    src = read("app/api/location_sharing.py")
    assert "_canonical_public_share_state" in src
    assert "sharing_paused(session, user_id)" in src
    assert src.count("_canonical_public_share_state(") >= 4
    assert "Location sharing is currently paused" in src


def test_public_tracking_suppresses_ai_without_behavioral_ai_authority():
    src = read("app/api/location_sharing.py")
    assert "ai_insight=_compute_ai_insight(gs) if ai_allowed else None" in src
    assert 'risk_level=(gs.risk_level or "SAFE") if ai_allowed else "SAFE"' in src
    assert 'ctx.ai_context = "Location safety context available"' in src


def test_family_runtime_router_is_registered():
    src = read("app/api/main.py")
    assert "family_circle_runtime_router" in src
    assert "include_router(family_circle_runtime_router)" in src

def test_runtime_snapshot_keeps_background_location_distinct_from_activity_ai():
    src = read("app/services/family_circle_runtime_authority.py")
    assert '"can_produce_background_location"' in src
    assert "actor_consent.granted(CONSENT_BACKGROUND_LOCATION)" in src
    assert "It is not ACTION_PRODUCE_ACTIVITY" in src
