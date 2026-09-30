"""Family Circle Phase 3 consent/minor policy primitives.

Pure policy only. Runtime producers remain unchanged and consume these decisions
through service/API gates. Unknown DOB fails closed for age-sensitive purposes.
"""
from __future__ import annotations

from datetime import date

from app.core.age_policy import is_minor

PURPOSE_LOCATION = "location"
PURPOSE_BACKGROUND_LOCATION = "background_location"
PURPOSE_BEHAVIORAL_AI = "behavioral_ai"
PURPOSE_MICROPHONE = "microphone"
PURPOSE_WEARABLE = "wearable"

FAMILY_CONSENT_PURPOSES = frozenset({
    PURPOSE_LOCATION, PURPOSE_BACKGROUND_LOCATION, PURPOSE_BEHAVIORAL_AI,
    PURPOSE_MICROPHONE, PURPOSE_WEARABLE,
})
RESTRICTED_FOR_MINOR = frozenset({PURPOSE_BEHAVIORAL_AI, PURPOSE_MICROPHONE, PURPOSE_WEARABLE})
CURRENT_FAMILY_NOTICE_VERSION = "family-circle-1.1"
SUPPORTED_LANGUAGES = frozenset({"en", "hi"})


def normalize_purpose(value: object) -> str:
    purpose = str(value or "").strip().lower()
    if purpose not in FAMILY_CONSENT_PURPOSES:
        raise ValueError("Unsupported Family Circle consent purpose")
    return purpose


def subject_may_self_consent(date_of_birth: date | None) -> bool:
    return date_of_birth is not None and not is_minor(date_of_birth)


def purpose_allowed_for_subject(date_of_birth: date | None, purpose: object) -> bool:
    p = normalize_purpose(purpose)
    if date_of_birth is None:
        return False
    if is_minor(date_of_birth) and p in RESTRICTED_FOR_MINOR:
        return False
    return True


def notice_is_current(version: object) -> bool:
    return str(version or "").strip() == CURRENT_FAMILY_NOTICE_VERSION
