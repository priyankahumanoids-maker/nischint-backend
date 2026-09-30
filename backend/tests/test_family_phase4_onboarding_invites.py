from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.family_circle_invite_service import (
    INVITE_TTL_HOURS,
    FamilyInviteError,
    canonical_invite_seat,
    disclosure_for,
    invite_code_hash,
    invite_kind_for_dob,
    normalize_invite_code,
)
from app.services.family_circle_onboarding_service import (
    FamilyOnboardingError,
    creator_seat_for_plan,
    is_tracked_seat,
)


def _dob(age: int) -> date:
    today = date.today()
    return date(today.year - age, today.month, min(today.day, 28))


def test_invites_are_48_hours_and_hash_plain_codes():
    assert INVITE_TTL_HOURS == 48
    digest = invite_code_hash("ABC234")
    assert len(digest) == 64
    assert "ABC234" not in digest


@pytest.mark.parametrize("bad", ["", "abc123", "ABCDE", "ABCDE1", "ABC-23", "OOOOOO", "111111"])
def test_invalid_invite_codes_fail_closed(bad):
    with pytest.raises(FamilyInviteError):
        normalize_invite_code(bad)


def test_plan_seat_shapes_match_phase2():
    assert canonical_invite_seat("trial", "protected") == "protected"
    assert canonical_invite_seat("trial", "guardian") == "guardian"
    assert canonical_invite_seat("individual", "protected") == "protected"
    assert canonical_invite_seat("family", "member") == "member"
    with pytest.raises(FamilyInviteError):
        canonical_invite_seat("family", "guardian")


def test_creator_trial_preselect_shape_and_family_member_shape():
    assert creator_seat_for_plan("trial", "protected") == "protected"
    assert creator_seat_for_plan("trial", "guardian") == "guardian"
    assert creator_seat_for_plan("family", None) == "member"
    with pytest.raises(FamilyOnboardingError):
        creator_seat_for_plan("trial", "member")


def test_tracking_shape_is_plan_plus_seat_not_role():
    assert is_tracked_seat("trial", "protected") is True
    assert is_tracked_seat("trial", "guardian") is False
    assert is_tracked_seat("individual", "guardian") is False
    assert is_tracked_seat("family", "member") is True


def test_age_controls_invitee_kind():
    assert invite_kind_for_dob(_dob(17)) == "minor"
    assert invite_kind_for_dob(_dob(18)) == "adult"
    with pytest.raises(FamilyInviteError):
        invite_kind_for_dob(None)


def test_individual_guardian_disclosure_is_one_way_and_untracked():
    tracked, who, data = disclosure_for("individual", "guardian", "adult")
    assert tracked is False
    assert "Protected member" in who
    assert "does not see you" in who
    assert all("your location" not in item.lower() for item in data)


def test_individual_protected_disclosure_is_one_way_and_tracked():
    tracked, who, data = disclosure_for("individual", "protected", "adult")
    assert tracked is True
    assert "Guardians" in who
    assert "do not see Guardians" in who
    assert "Live location" in data


def test_minor_disclosure_never_claims_ai_voice_or_wearable():
    tracked, _, data = disclosure_for("family", "member", "minor")
    assert tracked is True
    rendered = " ".join(data).lower()
    assert "ai" not in rendered
    assert "voice" not in rendered
    assert "wearable" not in rendered


def test_fc05_schema_is_additive_and_after_fc04():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "app/migrations/fc05_family_onboarding_invites.py").read_text(encoding="utf-8")
    server = (root / "server.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS family_circle_invites" in migration
    assert "code_hash VARCHAR(64) NOT NULL UNIQUE" in migration
    assert "family_legal_acceptances" in migration
    assert server.index("fc04_family_consent_authority") < server.index("fc05_family_onboarding_invites")


def test_invite_service_reserves_pending_seats_and_is_single_use_by_contract():
    root = Path(__file__).resolve().parents[1]
    src = (root / "app/services/family_circle_invite_service.py").read_text(encoding="utf-8")
    assert "occupied + pending >= capacity" in src
    assert "status='accepted'" in src
    assert "WHERE id=:id AND status='pending'" in src
    assert "Only the Owner or Co-Admin can invite members." in src
    assert "parental_verification_ref" in src


def test_public_preview_exposes_required_disclosure_not_secret_hash():
    root = Path(__file__).resolve().parents[1]
    api = (root / "app/api/family_circle_onboarding.py").read_text(encoding="utf-8")
    assert '"who_can_see": preview.who_can_see' in api
    assert '"data_shared": list(preview.data_shared)' in api
    assert '"owner_name": preview.owner_name' in api
    assert "code_hash" not in api


def test_auth_canonical_join_is_server_invite_authoritative():
    root = Path(__file__).resolve().parents[1]
    auth = (root / "app/api/auth.py").read_text(encoding="utf-8")
    assert "accept_invite_for_user" in auth
    assert "canonical_preview.seat == \"guardian\"" in auth
    assert "legal_accepted" in auth
    assert "canonical_preview.invitee_kind" in auth
    assert "canonical_preview.seat" in auth



def test_minor_acceptance_materializes_parental_location_consent_only():
    root = Path(__file__).resolve().parents[1]
    src = (root / "app/services/family_circle_invite_service.py").read_text(encoding="utf-8")
    assert 'if actual_kind == "minor"' in src
    assert '("location", "background_location")' in src
    assert 'CURRENT_FAMILY_NOTICE_VERSION' in src
    assert 'parental_basis' in src
    # Phase 3 restrictions stay authoritative: the materialized parental grant
    # loop is explicitly limited to the two child-safety location purposes.
    assert 'for purpose in ("location", "background_location"):' in src
    assert 'for purpose in ("behavioral_ai"' not in src
    assert 'for purpose in ("microphone"' not in src
    assert 'for purpose in ("wearable"' not in src

def test_phase4_does_not_modify_safety_engine_modules():
    # Contract guard: the Phase 4 implementation lives around auth/membership;
    # it does not import or rewrite SOS/location/AI/BLE runtime engines.
    root = Path(__file__).resolve().parents[1]
    api = (root / "app/api/family_circle_onboarding.py").read_text(encoding="utf-8")
    service = (root / "app/services/family_circle_invite_service.py").read_text(encoding="utf-8")
    forbidden = ["sos", "background_location", "ble_service", "behavior_ai", "voice_distress"]
    combined = (api + service).lower()
    for token in forbidden:
        assert f"import {token}" not in combined
