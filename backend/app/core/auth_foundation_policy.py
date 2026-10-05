"""7C-1 pure policies. No configuration, provider, database or startup imports.

These policies are not yet wired into legacy public OTP routes.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

OTP_TTL_SECONDS = 300
OTP_RESEND_COOLDOWN_SECONDS = 30
OTP_MAX_ATTEMPTS = 5
PHONE_LOCK_SECONDS = 900
PHONE_RECOVERY_SECONDS = 24 * 60 * 60
SOS_SCOPE = "emergency:raise"
STEP_UP_ACTIONS = frozenset({
    "ownership_transfer", "circle_delete", "member_remove",
    "plan_cancel", "phone_change", "minor_add",
})


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return value


def normalize_phone(value: str) -> str:
    # Do not guess a country code or silently rewrite national numbers.
    value = value.strip()
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
        raise ValueError("An E.164 phone identity is required")
    return value


def keyed_identity(key: bytes, domain: str, value: str) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("An injected identity key of at least 32 bytes is required")
    return hmac.new(key, (domain + "\0" + value).encode(), hashlib.sha256).hexdigest()


def phone_security_key(phone: str, key: bytes) -> str:
    return keyed_identity(key, "phone-security-v1", normalize_phone(phone))


def installation_key(user_id: UUID, installation_id: UUID, key: bytes) -> str:
    return keyed_identity(key, "auth-installation-v1", f"{UUID(str(user_id))}:{UUID(str(installation_id))}")


@dataclass(frozen=True)
class PhoneState:
    failures: int = 0
    locked_until: datetime | None = None

    def __post_init__(self):
        if not 0 <= self.failures <= OTP_MAX_ATTEMPTS:
            raise ValueError("Invalid phone failure state")
        if self.locked_until is not None:
            aware(self.locked_until)

    def locked(self, now: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > aware(now)


def phone_result(state: PhoneState, *, success: bool, now: datetime) -> PhoneState:
    aware(now)
    if state.locked(now):
        return state  # No resend/purpose/success can lift an active lock.
    if success:
        return PhoneState()
    count = 0 if state.locked_until is not None else state.failures
    count = min(count + 1, OTP_MAX_ATTEMPTS)
    return PhoneState(count, now + timedelta(seconds=PHONE_LOCK_SECONDS) if count == OTP_MAX_ATTEMPTS else None)


@dataclass(frozen=True)
class ActionBinding:
    user_id: UUID
    session_id: UUID
    action: str
    circle_id: UUID | None = None
    target_id: UUID | None = None

    def __post_init__(self):
        if self.action not in STEP_UP_ACTIONS:
            raise ValueError("Unsupported step-up action")
        for field in ("user_id", "session_id", "circle_id", "target_id"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, UUID(str(value)))
        if self.action != "phone_change" and self.circle_id is None:
            raise ValueError("Circle binding required")
        if self.action in {"ownership_transfer", "member_remove", "minor_add", "phone_change"} and self.target_id is None:
            raise ValueError("Target binding required (phone change uses operation ID)")

    @property
    def purpose(self) -> str:
        return "stepup:" + self.action


def proof_valid(actual: ActionBinding, expected: ActionBinding, verified_at: datetime,
                expires_at: datetime, now: datetime) -> bool:
    return (actual == expected and aware(verified_at) <= aware(now) < aware(expires_at)
            <= verified_at + timedelta(seconds=OTP_TTL_SECONDS))


def sos_valid(*, scope: str, issued_at: datetime, expires_at: datetime,
              revoked_at: datetime | None, now: datetime) -> bool:
    return (scope == SOS_SCOPE and revoked_at is None
            and aware(issued_at) <= aware(now) < aware(expires_at))


def totp_step_allowed(step: int, last_step: int | None, now: datetime) -> bool:
    """Replay/window check AFTER a later verifier establishes the TOTP MAC."""
    current = int(aware(now).timestamp()) // 30
    return (type(step) is int and step >= 0 and abs(step - current) <= 1
            and (last_step is None or step > last_step))


def phone_change_ready(*, recovery: bool, requested_at: datetime,
                       eligible_after: datetime, old_verified_at: datetime | None,
                       new_verified_at: datetime | None, now: datetime) -> bool:
    aware(now)
    if aware(requested_at) > now or new_verified_at is None:
        return False
    if not requested_at <= aware(new_verified_at) <= now:
        return False
    if recovery:
        return aware(eligible_after) >= requested_at + timedelta(seconds=PHONE_RECOVERY_SECONDS) and now >= eligible_after
    return old_verified_at is not None and requested_at <= aware(old_verified_at) <= now
