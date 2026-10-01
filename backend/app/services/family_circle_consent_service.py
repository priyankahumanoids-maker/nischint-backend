"""Single authoritative Family Circle consent write/read service.

Canonical grants are purpose-specific, current-notice, and adult-self owned.
Legacy Privacy settings may propagate *withdrawals* into this authority so a
visible revoke always fails closed; legacy grants never silently create a new
canonical Family Circle consent grant.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_consent_policy import (
    CURRENT_FAMILY_NOTICE_VERSION,
    FAMILY_CONSENT_PURPOSES,
    SUPPORTED_LANGUAGES,
    normalize_purpose,
    purpose_allowed_for_subject,
    subject_may_self_consent,
)
from app.models.family_circle import CircleMembership
from app.models.user import User
from app.services.family_circle_audit_service import append_family_audit

LEGACY_WITHDRAWAL_MAP: dict[str, tuple[str, ...]] = {
    # Revoking the old combined always-on location switch must immediately stop
    # both foreground and background canonical sharing. Re-grant remains
    # granular and must occur through the Family Circle consent surface.
    "location_tracking": ("location", "background_location"),
    "audio_recording": ("microphone",),
    "health_vitals": ("wearable",),
}


async def _active_membership(session: AsyncSession, user_id) -> CircleMembership | None:
    return (
        await session.execute(
            select(CircleMembership).where(
                CircleMembership.user_id == user_id,
                CircleMembership.status == "active",
            )
        )
    ).scalar_one_or_none()


async def record_self_consent(
    session: AsyncSession,
    *,
    user: User,
    decisions: dict[str, bool],
    notice_version: str,
    language: str,
    device_id: str | None = None,
) -> dict[str, bool]:
    membership = await _active_membership(session, user.id)
    if membership is None:
        raise PermissionError("family_circle_required")
    if not subject_may_self_consent(user.date_of_birth):
        raise PermissionError("minor_self_consent_forbidden")
    if notice_version != CURRENT_FAMILY_NOTICE_VERSION:
        raise ValueError("current_family_consent_notice_required")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("unsupported_consent_language")
    if not decisions:
        raise ValueError("at_least_one_consent_decision_required")

    normalized: dict[str, bool] = {}
    for raw_purpose, granted in decisions.items():
        purpose = normalize_purpose(raw_purpose)
        if purpose not in FAMILY_CONSENT_PURPOSES or not purpose_allowed_for_subject(user.date_of_birth, purpose):
            raise PermissionError(f"consent_purpose_not_allowed:{purpose}")
        normalized[purpose] = bool(granted)

    for purpose, granted in normalized.items():
        await session.execute(
            text(
                """
                INSERT INTO family_consent_events (
                    id, subject_user_id, actor_user_id, purpose, state,
                    notice_version, language, device_id, created_at
                ) VALUES (
                    :id, :subject_user_id, :actor_user_id, :purpose, :state,
                    :notice_version, :language, :device_id, :created_at
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "subject_user_id": user.id,
                "actor_user_id": user.id,
                "purpose": purpose,
                "state": "granted" if granted else "withdrawn",
                "notice_version": notice_version,
                "language": language,
                "device_id": device_id,
                "created_at": datetime.now(timezone.utc),
            },
        )
        await append_family_audit(
            session,
            circle_id=membership.circle_id,
            actor_user_id=user.id,
            subject_user_id=user.id,
            event_type="consent_given" if granted else "consent_withdrawn",
            details={"purpose": purpose, "notice_version": notice_version, "language": language},
        )
    return normalized


async def current_self_consent_decisions(session: AsyncSession, *, user_id) -> dict[str, bool]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (purpose) purpose, state
                  FROM family_consent_events
                 WHERE subject_user_id=:uid AND actor_user_id=:uid
                   AND notice_version=:notice_version
                 ORDER BY purpose, created_at DESC, id DESC
                """
            ),
            {"uid": str(user_id), "notice_version": CURRENT_FAMILY_NOTICE_VERSION},
        )
    ).mappings().all()
    return {str(r["purpose"]): str(r["state"]) == "granted" for r in rows}


async def sync_legacy_withdrawal(
    session: AsyncSession,
    *,
    user: User,
    legacy_category: str,
    language: str = "en",
) -> bool:
    """Propagate a legacy Privacy-screen revoke into canonical authority.

    This function intentionally never turns a legacy grant into a canonical
    grant. Withdrawal must be easy and immediate; grant requires current Family
    Circle notice and a purpose-specific user decision.
    """
    membership = await _active_membership(session, user.id)
    purposes = LEGACY_WITHDRAWAL_MAP.get(str(legacy_category))
    if membership is None or not purposes:
        return False
    for purpose in purposes:
        await session.execute(
            text(
                """
                INSERT INTO family_consent_events (
                    id, subject_user_id, actor_user_id, purpose, state,
                    notice_version, language, device_id, created_at
                ) VALUES (
                    :id, :uid, :uid, :purpose, 'withdrawn',
                    :notice_version, :language, NULL, NOW()
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "uid": user.id,
                "purpose": purpose,
                "notice_version": CURRENT_FAMILY_NOTICE_VERSION,
                "language": language if language in SUPPORTED_LANGUAGES else "en",
            },
        )
        await append_family_audit(
            session,
            circle_id=membership.circle_id,
            actor_user_id=user.id,
            subject_user_id=user.id,
            event_type="consent_withdrawn",
            details={"purpose": purpose, "source": "legacy_privacy_screen"},
        )
    return True


__all__ = [
    "LEGACY_WITHDRAWAL_MAP", "record_self_consent", "current_self_consent_decisions",
    "sync_legacy_withdrawal",
]
