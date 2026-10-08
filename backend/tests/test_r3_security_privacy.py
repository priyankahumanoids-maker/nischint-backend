from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def test_phone_login_binds_installation_without_otp_bypass():
    source = text("app/api/phone_auth.py")
    assert "installation_id: UUID | None" in source
    assert "associate_installation" in source
    assert "verify_phone_code" in source
    assert "fixed otp" not in source.lower()

def test_push_registration_dispatches_deduped_new_device_notice():
    source = text("app/api/push.py")
    service = text("app/services/auth_installation_service.py")
    assert "dispatch_pending_new_device_notice" in source
    assert "associate_push_token" in source
    assert "notice_state='delivered'" in service
    assert 'state != "pending"' in service
    assert "other_signed_in_push_tokens" in service
    assert "new_device_login" in service

def test_who_viewed_actual_disclosure_boundaries_remain_covered():
    live = text("app/api/guardian_live.py")
    stream = text("app/api/stream.py")
    guardian = text("app/api/guardian.py")
    emergency = text("app/api/emergency.py")
    sharing = text("app/api/location_sharing.py")
    assert "record_location_disclosure" in live
    assert "record_disclosure=True" in live
    assert "record_disclosure=True" in stream
    assert "record_location_disclosure" in stream
    assert "record_disclosure=True" in guardian
    assert "record_location_disclosure" in emergency
    assert "record_location_disclosure" in sharing

def test_family_audit_required_lifecycle_events_remain_present():
    joined = "\n".join(text(path) for path in [
        "app/services/family_circle_invite_service.py",
        "app/services/family_circle_lifecycle_service.py",
        "app/services/family_circle_management_service.py",
        "app/services/family_circle_consent_service.py",
        "app/services/family_circle_plan_change_service.py",
    ])
    for event in [
        "invite_created", "member_joined", "member_removed", "member_left",
        "role_changed", "ownership_transfer_accepted", "consent_given",
        "consent_withdrawn", "sharing_paused", "sharing_resumed",
        "parental_consent_recorded", "plan_changed",
    ]:
        assert event in joined
