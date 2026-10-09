"""Family Circle v1.0 plan, seat and trial authority (Phase 2).

This module is the canonical server-side authority for plan shape and seat
capacity.  It is additive and deliberately does not expose HTTP endpoints or
activate paid billing.  Later onboarding/invite APIs must call these helpers
rather than duplicating seat/trial rules.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_circle_permissions import (
    PLAN_FAMILY,
    PLAN_INDIVIDUAL,
    PLAN_TRIAL,
    PLANS,
    SEAT_GUARDIAN,
    SEAT_MEMBER,
    SEAT_PROTECTED,
)
from app.core.family_circle_roles import CIRCLE_ROLE_MINOR
from app.models.family_circle import CircleMembership, FamilyCircle, FamilyTrialClaim
from app.models.user import User
from app.services.family_circle_service import CircleIdentity, add_membership

TRIAL_DURATION_DAYS = 7


class CirclePlanError(ValueError):
    """Stable domain error for plan/seat/trial invariant violations."""


class TrialAlreadyUsedError(CirclePlanError):
    """Raised when either the phone or device has already received a trial."""


@dataclass(frozen=True)
class PlanShape:
    plan: str
    capacities: dict[str, int]


# Compatibility snapshot for legacy tests only. Runtime allocation uses family_plan_catalog.
PLAN_SHAPES = {
    PLAN_TRIAL: PlanShape(PLAN_TRIAL, {SEAT_PROTECTED: 1, SEAT_GUARDIAN: 2}),
    PLAN_INDIVIDUAL: PlanShape(PLAN_INDIVIDUAL, {SEAT_PROTECTED: 1, SEAT_GUARDIAN: 2}),
    PLAN_FAMILY: PlanShape(PLAN_FAMILY, {SEAT_MEMBER: 4}),
}


def get_plan_shape(plan: str) -> PlanShape:
    canonical = str(plan or "").strip().lower()
    if canonical not in PLANS:
        raise CirclePlanError("Unknown Family Circle plan.")
    return PLAN_SHAPES[canonical]


def seat_capacity(plan: str, seat: str) -> int:
    shape = get_plan_shape(plan)
    canonical_seat = str(seat or "").strip().lower()
    capacity = shape.capacities.get(canonical_seat)
    if capacity is None:
        raise CirclePlanError("Seat type is not valid for this plan.")
    return capacity


def validate_seat_for_membership(plan: str, seat: str, role: str) -> str:
    canonical_seat = str(seat or "").strip().lower()
    seat_capacity(plan, canonical_seat)
    if role == CIRCLE_ROLE_MINOR and canonical_seat == SEAT_GUARDIAN:
        raise CirclePlanError("A Minor cannot occupy a Guardian seat.")
    return canonical_seat




async def get_runtime_plan_shape(session: AsyncSession, plan: str) -> PlanShape:
    from app.services.family_circle_plan_catalog_service import get_catalog_plan
    configured = await get_catalog_plan(session, plan)
    return PlanShape(configured.plan, dict(configured.capacities))


async def runtime_seat_capacity(session: AsyncSession, plan: str, seat: str) -> int:
    shape = await get_runtime_plan_shape(session, plan)
    canonical_seat = str(seat or "").strip().lower()
    capacity = shape.capacities.get(canonical_seat)
    if capacity is None:
        raise CirclePlanError("Seat type is not valid for this plan.")
    return int(capacity)


async def validate_runtime_seat(session: AsyncSession, plan: str, seat: str, role: str) -> str:
    canonical_seat = str(seat or "").strip().lower()
    await runtime_seat_capacity(session, plan, canonical_seat)
    if role == CIRCLE_ROLE_MINOR and canonical_seat == SEAT_GUARDIAN:
        raise CirclePlanError("A Minor cannot occupy a Guardian seat.")
    return canonical_seat


def _canonical_trial_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) == 10:
        digits = f"91{digits}"
    if len(digits) < 10 or len(digits) > 15:
        raise CirclePlanError("A valid phone number is required for trial eligibility.")
    return digits


def _canonical_device_id(device_id: str) -> str:
    value = str(device_id or "").strip()
    if len(value) < 8 or len(value) > 512:
        raise CirclePlanError("A stable device identifier is required for trial eligibility.")
    return value


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def trial_fingerprints(phone: str, device_id: str) -> tuple[str, str]:
    """Return irreversible identifiers; raw phone/device values are never stored."""
    return (
        _fingerprint(f"phone:{_canonical_trial_phone(phone)}"),
        _fingerprint(f"device:{_canonical_device_id(device_id)}"),
    )


async def _lock_circle(session: AsyncSession, circle_id: uuid.UUID) -> None:
    # Serialises concurrent seat allocation / plan initialisation on one circle.
    await session.execute(
        select(FamilyCircle.id)
        .where(FamilyCircle.id == circle_id)
        .with_for_update()
    )


async def _active_seat_count(
    session: AsyncSession,
    circle_id: uuid.UUID,
    seat: str,
    *,
    exclude_removal_id: uuid.UUID | None = None,
) -> int:
    value = (
        await session.execute(
            select(func.count())
            .select_from(CircleMembership)
            .where(
                CircleMembership.circle_id == circle_id,
                CircleMembership.status == "active",
                CircleMembership.seat == seat,
            )
        )
    ).scalar_one()
    # Removed membership never authorizes reads/producers. Its seat alone is
    # reserved for the server's ten-second Undo window (FC08 prerequisite).
    reserved = (await session.execute(text("""
        SELECT COUNT(*) FROM family_lifecycle_operations
        WHERE circle_id=:circle AND kind='member_remove' AND state='pending'
          AND expires_at > clock_timestamp() AND details->>'seat'=:seat
          AND id IS DISTINCT FROM CAST(:exclude_removal_id AS UUID)
    """), {"circle": circle_id, "seat": seat,
            "exclude_removal_id": exclude_removal_id})).scalar_one()
    return int(value or 0) + int(reserved or 0)


async def assert_seat_available(
    session: AsyncSession,
    *,
    circle: FamilyCircle,
    seat: str,
    role: str,
) -> str:
    if circle.status != "active":
        raise CirclePlanError("Cannot allocate seats in a closed Family Circle.")
    if not circle.plan:
        raise CirclePlanError("Circle plan must be selected before seats are allocated.")

    canonical_seat = await validate_runtime_seat(session, circle.plan, seat, role)
    capacity = await runtime_seat_capacity(session, circle.plan, canonical_seat)
    current = await _active_seat_count(session, circle.id, canonical_seat)
    if current >= capacity:
        raise CirclePlanError(f"{canonical_seat} seat capacity is full for this plan.")
    return canonical_seat


async def initialize_circle_plan(
    session: AsyncSession,
    *,
    circle: FamilyCircle,
    owner_membership: CircleMembership,
    plan: str,
    owner_seat: str,
    phone: str | None = None,
    device_id: str | None = None,
    now: datetime | None = None,
    creator_fields_initialized: bool = False,
) -> None:
    """Select the initial plan and assign the creator's seat.

    Trial activation claims both phone and device for exactly seven days.  Paid
    plan selection stores only the plan shape; payment activation remains Phase 6
    and cannot be faked through this function.
    """
    if circle.status != "active":
        raise CirclePlanError("Cannot initialize a closed Family Circle.")
    if owner_membership.circle_id != circle.id or owner_membership.user_id != circle.owner_user_id:
        raise CirclePlanError("Owner membership does not belong to this Family Circle.")
    if not creator_fields_initialized and (circle.plan is not None or owner_membership.seat is not None):
        raise CirclePlanError("Family Circle plan/seat has already been initialized.")

    canonical_plan = str(plan or "").strip().lower()
    shape = await get_runtime_plan_shape(session, canonical_plan)
    canonical_seat = await validate_runtime_seat(session, canonical_plan, owner_seat, owner_membership.role)

    if creator_fields_initialized and (
        circle.plan != canonical_plan or owner_membership.seat != canonical_seat
        or owner_membership.role != "owner" or owner_membership.status != "active"
        or circle.trial_started_at is not None or circle.trial_ends_at is not None
    ):
        raise CirclePlanError("Creator plan/seat does not match initial onboarding state.")

    await _lock_circle(session, circle.id)

    # Creator is the first active member, so assigning their valid seat cannot
    # exceed capacity.  Any pre-existing seated member means onboarding order is
    # inconsistent and must fail closed.
    existing_seated = (
        await session.execute(
            select(func.count())
            .select_from(CircleMembership)
            .where(
                CircleMembership.circle_id == circle.id,
                CircleMembership.status == "active",
                CircleMembership.seat.is_not(None),
                # Only the exact pre-seated creator is exempt, never another member.
                *([CircleMembership.id != owner_membership.id] if creator_fields_initialized else []),
            )
        )
    ).scalar_one()
    if int(existing_seated or 0) != 0:
        raise CirclePlanError("Circle already has seat assignments before plan initialization.")

    trial_claim = None
    started_at = None
    ends_at = None

    if canonical_plan == PLAN_TRIAL:
        if phone is None or device_id is None:
            raise CirclePlanError("Phone and device are required to activate the 7-day trial.")
        phone_fp, device_fp = trial_fingerprints(phone, device_id)

        existing_claim = (
            await session.execute(
                select(FamilyTrialClaim).where(
                    or_(
                        FamilyTrialClaim.phone_fingerprint == phone_fp,
                        FamilyTrialClaim.device_fingerprint == device_fp,
                    )
                )
            )
        ).scalars().first()
        if existing_claim is not None:
            raise TrialAlreadyUsedError("This phone number or device has already used the Family Circle trial.")

        started_at = now or datetime.now(timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        ends_at = started_at + timedelta(days=TRIAL_DURATION_DAYS)
        trial_claim = FamilyTrialClaim(
            id=uuid.uuid4(),
            circle_id=circle.id,
            phone_fingerprint=phone_fp,
            device_fingerprint=device_fp,
            claimed_at=started_at,
        )
        session.add(trial_claim)

    # Family and Individual selection does not activate/verify payment here.
    circle.plan = shape.plan
    circle.trial_started_at = started_at
    circle.trial_ends_at = ends_at
    owner_membership.seat = canonical_seat

    try:
        await session.flush()
    except IntegrityError as exc:
        # Unique phone/device fingerprints are the concurrency backstop.
        if canonical_plan == PLAN_TRIAL:
            raise TrialAlreadyUsedError(
                "This phone number or device has already used the Family Circle trial."
            ) from exc
        raise CirclePlanError("Family Circle plan initialization conflict.") from exc


async def add_membership_with_seat(
    session: AsyncSession,
    *,
    circle: FamilyCircle,
    user: User,
    role: str,
    seat: str,
    created_by_user_id: uuid.UUID | None,
) -> CircleIdentity:
    """Add one member through the canonical server-side seat-capacity path."""
    await _lock_circle(session, circle.id)
    canonical_seat = await assert_seat_available(
        session,
        circle=circle,
        seat=seat,
        role=role,
    )

    identity = await add_membership(
        session,
        circle_id=circle.id,
        user=user,
        role=role,
        created_by_user_id=created_by_user_id,
    )
    membership = await session.get(CircleMembership, identity.membership_id)
    if membership is None:
        raise CirclePlanError("New Circle membership could not be loaded for seat assignment.")
    membership.seat = canonical_seat
    await session.flush()
    return identity


def trial_window_is_active(circle: FamilyCircle, *, now: datetime | None = None) -> bool:
    if circle.plan != PLAN_TRIAL or circle.trial_started_at is None or circle.trial_ends_at is None:
        return False
    point = now or datetime.now(timezone.utc)
    if point.tzinfo is None:
        point = point.replace(tzinfo=timezone.utc)
    return circle.trial_started_at <= point < circle.trial_ends_at


__all__ = [
    "TRIAL_DURATION_DAYS",
    "CirclePlanError",
    "TrialAlreadyUsedError",
    "PlanShape",
    "PLAN_SHAPES",
    "get_plan_shape",
    "seat_capacity",
    "get_runtime_plan_shape",
    "runtime_seat_capacity",
    "validate_runtime_seat",
    "validate_seat_for_membership",
    "trial_fingerprints",
    "assert_seat_available",
    "initialize_circle_plan",
    "add_membership_with_seat",
    "trial_window_is_active",
]
