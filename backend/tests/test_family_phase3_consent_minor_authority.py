from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.family_consent_policy import (
    CURRENT_FAMILY_NOTICE_VERSION,
    notice_is_current,
    normalize_purpose,
    purpose_allowed_for_subject,
    subject_may_self_consent,
)


def _dob_for_age(age: int) -> date:
    today = date.today()
    return date(today.year - age, today.month, min(today.day, 28))


def test_adult_self_consent_and_unknown_dob_fail_closed():
    assert subject_may_self_consent(_dob_for_age(18)) is True
    assert subject_may_self_consent(_dob_for_age(17)) is False
    assert subject_may_self_consent(None) is False


@pytest.mark.parametrize('purpose', ['behavioral_ai', 'microphone', 'wearable'])
def test_minor_restricted_purposes_are_denied(purpose):
    assert purpose_allowed_for_subject(_dob_for_age(17), purpose) is False
    assert purpose_allowed_for_subject(_dob_for_age(18), purpose) is True


@pytest.mark.parametrize('purpose', ['location', 'background_location'])
def test_minor_safety_location_purposes_remain_available(purpose):
    assert purpose_allowed_for_subject(_dob_for_age(17), purpose) is True


def test_notice_version_is_exact_and_unknown_purpose_denied():
    assert notice_is_current(CURRENT_FAMILY_NOTICE_VERSION)
    assert not notice_is_current('1.0')
    with pytest.raises(ValueError):
        normalize_purpose('voice_profile')


def test_fc04_is_additive_and_server_runs_after_fc03():
    root = Path(__file__).resolve().parents[1]
    migration = (root / 'app/migrations/fc04_family_consent_authority.py').read_text(encoding='utf-8')
    server = (root / 'server.py').read_text(encoding='utf-8')
    assert 'CREATE TABLE IF NOT EXISTS family_consent_events' in migration
    assert 'CREATE TABLE IF NOT EXISTS family_sharing_states' in migration
    assert server.index('fc03_circle_plan_seat_trial') < server.index('fc04_family_consent_authority')


def test_monitoring_policy_blocks_remote_adult_and_minor_ai_voice():
    root = Path(__file__).resolve().parents[1]
    src = (root / 'app/services/member_monitoring_policy.py').read_text(encoding='utf-8')
    assert "Another adult cannot change this member's monitoring" in src
    assert 'Behavioral AI and voice distress are unavailable for minors.' in src
    assert 'str(actor.id) == target_id' in src
