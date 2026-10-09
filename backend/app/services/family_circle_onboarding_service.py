"""Phase 4 creator onboarding authority for canonical Family Circles."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_circle_permissions import PLAN_FAMILY, PLAN_INDIVIDUAL, PLAN_TRIAL, SEAT_MEMBER
from app.models.family_circle import CircleMembership, FamilyCircle
from app.models.user import User
from app.services.family_circle_plan_service import (
    CirclePlanError,
    TrialAlreadyUsedError,
    initialize_circle_plan,
)
from app.services.family_circle_service import CircleAuthorityError, create_circle, get_active_membership

from app.services.family_circle_entitlement_service import seed_entitlement_state

TERMS_VERSION = "2026-09"
PRIVACY_VERSION = "2026-09"


class FamilyOnboardingError(ValueError):
    pass


@dataclass(frozen=True)
class OnboardingState:
    has_circle: bool
    circle_id: uuid.UUID | None = None
    circle_name: str | None = None
    role: str | None = None
    plan: str | None = None
    seat: str | None = None
    trial_ends_at: object | None = None
    payment_required: bool = False
    tracked: bool = False


def creator_seat_for_plan(plan: str, seat: str | None) -> str:
    plan_value = str(plan or "").strip().lower()
    if plan_value == PLAN_FAMILY:
        return SEAT_MEMBER
    if plan_value in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        seat_value = str(seat or "").strip().lower()
        if seat_value not in {"protected", "guardian"}:
            raise FamilyOnboardingError("Trial and Individual creators must choose Protected or Guardian.")
        return seat_value
    raise FamilyOnboardingError("Unknown Family Circle plan.")


def is_tracked_seat(plan: str, seat: str) -> bool:
    plan_value = str(plan or "").strip().lower()
    if plan_value in {PLAN_TRIAL, PLAN_INDIVIDUAL}:
        return seat == "protected"
    return plan_value == PLAN_FAMILY and seat == "member"


async def record_legal_acceptance(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    terms_version: str = TERMS_VERSION,
    privacy_version: str = PRIVACY_VERSION,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO family_legal_acceptances (
                id, user_id, terms_version, privacy_version, accepted_at
            ) VALUES (:id, :user_id, :terms_version, :privacy_version, NOW())
            """
        ),
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "terms_version": terms_version,
            "privacy_version": privacy_version,
        },
    )
    await session.flush()


async def onboarding_state(session: AsyncSession, user_id: uuid.UUID) -> OnboardingState:
    membership = await get_active_membership(session, user_id)
    if membership is None:
        return OnboardingState(False)
    circle = await session.get(FamilyCircle, membership.circle_id)
    if circle is None:
        return OnboardingState(False)
    seat = str(membership.seat or "") or None
    plan = str(circle.plan or "") or None
    tracked = bool(plan and seat and is_tracked_seat(plan, seat))
    return OnboardingState(
        True,
        circle_id=circle.id,
        circle_name=circle.name,
        role=membership.role,
        plan=plan,
        seat=seat,
        trial_ends_at=circle.trial_ends_at,
        payment_required=plan in {PLAN_INDIVIDUAL, PLAN_FAMILY},
        tracked=tracked,
    )


async def create_creator_circle(
    session: AsyncSession,
    *,
    user: User,
    plan: str,
    seat: str | None,
    device_id: str | None,
    circle_name: str | None,
    legal_accepted: bool,
) -> OnboardingState:
    if not legal_accepted:
        raise FamilyOnboardingError("Terms and Privacy Policy must be accepted separately before Circle creation.")

    existing = await get_active_membership(session, user.id)
    canonical_seat = creator_seat_for_plan(plan, seat)
    canonical_plan = str(plan or "").strip().lower()

    if existing is not None:
        circle = await session.get(FamilyCircle, existing.circle_id)
        if (
            circle is not None
            and existing.role == "owner"
            and str(circle.plan or "") == canonical_plan
            and str(existing.seat or "") == canonical_seat
        ):
            return await onboarding_state(session, user.id)
        raise FamilyOnboardingError("This person already belongs to a Family Circle.")

    try:
        identity = await create_circle(
            session, user, name=circle_name, plan=canonical_plan, owner_seat=canonical_seat
        )
        circle = await session.get(FamilyCircle, identity.circle_id)
        membership = await session.get(CircleMembership, identity.membership_id)
        if circle is None or membership is None:
            raise FamilyOnboardingError("Family Circle could not be initialized.")

        await initialize_circle_plan(
            session,
            circle=circle,
            owner_membership=membership,
            plan=canonical_plan,
            owner_seat=canonical_seat,
            phone=user.phone,
            device_id=device_id,
            creator_fields_initialized=True,
        )
        await seed_entitlement_state(session, circle)
        await record_legal_acceptance(session, user_id=user.id)
        await session.flush()
        return await onboarding_state(session, user.id)
    except (CircleAuthorityError, CirclePlanError, TrialAlreadyUsedError) as exc:
        raise FamilyOnboardingError(str(exc)) from exc


__all__ = [
    "TERMS_VERSION",
    "PRIVACY_VERSION",
    "FamilyOnboardingError",
    "OnboardingState",
    "creator_seat_for_plan",
    "is_tracked_seat",
    "record_legal_acceptance",
    "onboarding_state",
    "create_creator_circle",
]
