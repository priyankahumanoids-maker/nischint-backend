"""Automatic Minor -> Adult Member transition with birthday-anchored consent bridge."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.age_policy import is_minor
from app.core.family_consent_policy import CURRENT_FAMILY_NOTICE_VERSION, FAMILY_CONSENT_PURPOSES
from app.models.family_circle import CircleMembership
from app.models.user import User
from app.services.family_circle_audit_service import append_family_audit

BRIDGE_DAYS = 7


def eighteenth_birthday(date_of_birth: date) -> date:
    """Return the legal/calendar 18th birthday under the existing age policy.

    Feb-29 birthdays advance on Mar-1 in non-leap years, matching
    ``calculate_age`` / Phase 1A tests.
    """
    year = date_of_birth.year + 18
    try:
        return date(year, date_of_birth.month, date_of_birth.day)
    except ValueError:
        return date(year, 3, 1)


def birthday_instant_utc(date_of_birth: date) -> datetime:
    return datetime.combine(eighteenth_birthday(date_of_birth), time.min, tzinfo=timezone.utc)


async def _current_self_decisions(session: AsyncSession, user_id) -> set[str]:
    result = await session.execute(
        text(
            """
            SELECT DISTINCT ON (purpose) purpose, state
              FROM family_consent_events
             WHERE subject_user_id=:uid
               AND actor_user_id=:uid
               AND notice_version=:notice_version
             ORDER BY purpose, created_at DESC, id DESC
            """
        ),
        {"uid": str(user_id), "notice_version": CURRENT_FAMILY_NOTICE_VERSION},
    )
    # A deliberate grant OR refusal is a decision. The bridge is about the
    # adult making their own choice, not forcing every optional purpose ON.
    return {
        str(row["purpose"])
        for row in result.mappings().all()
        if str(row["state"] or "") in {"granted", "withdrawn"}
    }


async def _has_complete_current_self_decisions(session: AsyncSession, user_id) -> bool:
    decided = await _current_self_decisions(session, user_id)
    return FAMILY_CONSENT_PURPOSES.issubset(decided)


async def reconcile_age18_for_user(session: AsyncSession, user_id, *, now: datetime | None = None) -> None:
    point = now or datetime.now(timezone.utc)
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    user = await session.get(User, user_id)
    if user is None or user.date_of_birth is None:
        return

    membership = (
        await session.execute(
            select(CircleMembership).where(
                CircleMembership.user_id == user.id,
                CircleMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return

    birthday_at = birthday_instant_utc(user.date_of_birth)
    due_at = birthday_at + timedelta(days=BRIDGE_DAYS)

    if membership.role == "minor" and point >= birthday_at and not is_minor(user.date_of_birth, on_date=point.date()):
        membership.role = "adult_member"
        await session.execute(
            text(
                """
                INSERT INTO family_age18_transitions
                    (user_id, circle_id, transitioned_at, consent_due_at)
                VALUES (:uid, :circle_id, :transitioned_at, :consent_due_at)
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {
                "uid": user.id,
                "circle_id": membership.circle_id,
                "transitioned_at": birthday_at,
                "consent_due_at": due_at,
            },
        )
        await append_family_audit(
            session,
            circle_id=membership.circle_id,
            actor_user_id=None,
            subject_user_id=user.id,
            event_type="minor_turned_18",
            details={"birthday_at": birthday_at.isoformat(), "consent_due_at": due_at.isoformat()},
            event_key=f"age18-transition:{user.id}",
        )
        await append_family_audit(
            session,
            circle_id=membership.circle_id,
            actor_user_id=None,
            subject_user_id=user.id,
            event_type="role_changed",
            details={"from": "minor", "to": "adult_member", "reason": "turned_18"},
            event_key=f"age18-role:{user.id}",
        )

    transition = (
        await session.execute(
            text(
                """
                SELECT circle_id, transitioned_at, consent_due_at,
                       consent_completed_at, bridge_expired_at
                  FROM family_age18_transitions
                 WHERE user_id=:uid
                """
            ),
            {"uid": str(user.id)},
        )
    ).mappings().first()
    if not transition or transition["consent_completed_at"] is not None:
        return

    if await _has_complete_current_self_decisions(session, user.id):
        result = await session.execute(
            text(
                """
                UPDATE family_age18_transitions
                   SET consent_completed_at=:at
                 WHERE user_id=:uid AND consent_completed_at IS NULL
             RETURNING user_id
                """
            ),
            {"uid": str(user.id), "at": point},
        )
        if result.scalar_one_or_none() is not None:
            await append_family_audit(
                session,
                circle_id=transition["circle_id"],
                actor_user_id=user.id,
                subject_user_id=user.id,
                event_type="age18_self_consent_completed",
                details={"notice_version": CURRENT_FAMILY_NOTICE_VERSION},
                event_key=f"age18-consent-complete:{user.id}",
            )
        return

    due = transition["consent_due_at"] or due_at
    if getattr(due, "tzinfo", None) is None:
        due = due.replace(tzinfo=timezone.utc)
    if point >= due and transition["bridge_expired_at"] is None:
        await session.execute(
            text(
                """
                INSERT INTO family_sharing_states (user_id, paused, pause_mode, paused_until, updated_at)
                VALUES (:uid, TRUE, 'manual', NULL, :at)
                ON CONFLICT (user_id) DO UPDATE SET
                    paused=TRUE, pause_mode='manual', paused_until=NULL, updated_at=EXCLUDED.updated_at
                """
            ),
            {"uid": str(user.id), "at": point},
        )
        result = await session.execute(
            text(
                """
                UPDATE family_age18_transitions
                   SET bridge_expired_at=:at
                 WHERE user_id=:uid AND bridge_expired_at IS NULL
             RETURNING user_id
                """
            ),
            {"uid": str(user.id), "at": point},
        )
        if result.scalar_one_or_none() is not None:
            await append_family_audit(
                session,
                circle_id=transition["circle_id"],
                actor_user_id=None,
                subject_user_id=user.id,
                event_type="age18_consent_bridge_expired",
                details={"consent_due_at": due.isoformat()},
                event_key=f"age18-bridge-expired:{user.id}",
            )


async def age18_status(session: AsyncSession, user_id) -> dict:
    row = (
        await session.execute(
            text(
                """
                SELECT transitioned_at, consent_due_at, consent_completed_at, bridge_expired_at
                  FROM family_age18_transitions WHERE user_id=:uid
                """
            ),
            {"uid": str(user_id)},
        )
    ).mappings().first()
    if not row:
        return {"transitioned": False, "requires_own_consent": False}
    decisions = await _current_self_decisions(session, user_id)
    missing = sorted(FAMILY_CONSENT_PURPOSES.difference(decisions))
    return {
        "transitioned": True,
        "transitioned_at": row["transitioned_at"],
        "consent_due_at": row["consent_due_at"],
        "consent_completed_at": row["consent_completed_at"],
        "bridge_expired_at": row["bridge_expired_at"],
        "requires_own_consent": row["consent_completed_at"] is None,
        "missing_purposes": missing,
        "notice_version": CURRENT_FAMILY_NOTICE_VERSION,
    }


__all__ = [
    "BRIDGE_DAYS", "eighteenth_birthday", "birthday_instant_utc",
    "reconcile_age18_for_user", "age18_status",
]
