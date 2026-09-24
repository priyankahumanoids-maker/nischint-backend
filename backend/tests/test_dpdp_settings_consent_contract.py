from app.api import consents


def test_existing_health_categories_remain_unchanged():
    assert consents.CATEGORIES == (
        "location_tracking",
        "audio_recording",
        "health_vitals",
        "push_notifications",
        "biometric_sensors",
    )


def test_settings_adds_emergency_contact_consent_without_changing_health_categories():
    assert "emergency_contact_sharing" in consents.SETTINGS_CATEGORIES
    meta = consents._metadata_for_category("emergency_contact_sharing")
    assert meta["required_for"] == "emergency_contact_delivery"


def test_member_specific_guardian_consent_uses_existing_audit_table_category_namespace():
    category = "dependent_profile:45829299-2b08-49fa-a2a0-dd5145a7a2d9"
    assert consents._is_supported_category(category) is True
    assert consents._dependent_profile_id(category) == "45829299-2b08-49fa-a2a0-dd5145a7a2d9"
    assert consents._metadata_for_category(category)["required_for"] == "dependent_profile"


def test_invalid_dynamic_consent_category_is_rejected():
    assert consents._is_supported_category("dependent_profile:not-a-uuid") is False
