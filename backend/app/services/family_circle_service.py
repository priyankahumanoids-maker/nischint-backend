"""Structural Family Circle authority for v1.0 Phase 1B.

This service owns membership invariants only. It deliberately does *not* decide
whether a caller is allowed to invite/remove/manage another person; the shared
role + plan + seat + consent + entitlement authorization layer is Phase 1C.
"""
from __future__ import annotations

import uuid
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.age_policy import is_minor
from app.core.family_circle_roles import (
    CIRCLE_ROLE_ADULT_MEMBER,
    CIRCLE_ROLE_CO_ADMIN,
    CIRCLE_ROLE_MINOR,
    CIRCLE_ROLE_OWNER,
    CircleRoleError,
    role_for_date_of_birth,
)
from app.models.family_circle import CircleMembership, FamilyCircle
from app.models.user import User


logger = logging.getLogger(__name__)


class CircleAuthorityError(ValueError):
    """Stable domain error raised when a structural Circle invariant is violated."""


@dataclass(frozen=True)
class CircleIdentity:
    circle_id: uuid.UUID
    membership_id: uuid.UUID
    user_id: uuid.UUID
    role: str


def _require_dob(user: User) -> None:
    if getattr(user, "date_of_birth", None) is None:
        raise CircleAuthorityError(
            "Date of birth is required before Family Circle membership can be created."
        )


def _validated_role(user: User, requested_role: str) -> str:
    _require_dob(user)
    try:
        return role_for_date_of_birth(user.date_of_birth, requested_role)
    except CircleRoleError as exc:
        raise CircleAuthorityError(str(exc)) from exc


async def get_active_membership(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> CircleMembership | None:
    return (
        await session.execute(
            select(CircleMembership).where(
                CircleMembership.user_id == user_id,
                CircleMembership.status == "active",
            )
        )
    ).scalar_one_or_none()


async def create_circle(
    session: AsyncSession,
    owner: User,
    *,
    name: str | None = None,
    plan: str | None = None,
    owner_seat: str | None = None,
) -> CircleIdentity:
    """Create one Circle and its required adult Owner membership atomically.

    Phase 1B does not infer membership from legacy guardian links. The caller must
    explicitly invoke this authority. Existing user IDs remain the member IDs.
    """
    _require_dob(owner)
    if is_minor(owner.date_of_birth):
        raise CircleAuthorityError("A person under 18 cannot create a Family Circle.")

    if await get_active_membership(session, owner.id) is not None:
        raise CircleAuthorityError("This person already belongs to a Family Circle.")

    if (plan is None) != (owner_seat is None):
        raise CircleAuthorityError("Creator plan and seat must be supplied together.")
    if plan is not None:
        # Lazy import avoids the plan service's dependency on this primitive.
        from app.services.family_circle_plan_service import validate_runtime_seat
        plan = str(plan).strip().lower()
        owner_seat = await validate_runtime_seat(session, plan, owner_seat, CIRCLE_ROLE_OWNER)

    circle_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    cleaned_name = (name or "").strip() or None

    circle = FamilyCircle(
        id=circle_id,
        name=cleaned_name,
        plan=plan,
        owner_user_id=owner.id,
        status="active",
    )
    membership = CircleMembership(
        id=membership_id,
        circle_id=circle_id,
        user_id=owner.id,
        role=CIRCLE_ROLE_OWNER,
        seat=owner_seat,
        status="active",
        created_by_user_id=owner.id,
    )
    try:
        # Independent mappers have no ORM relationship to order these INSERTs.
        # Flush the parent first; neither flush commits the caller's transaction.
        session.add(circle)
        await session.flush()
        session.add(membership)
        await session.flush()
    except IntegrityError as exc:
        original = exc.orig
        constraint = (
            getattr(getattr(original, "__cause__", None), "constraint_name", None)
            or getattr(getattr(original, "diag", None), "constraint_name", None)
            or getattr(original, "constraint_name", None)
        )
        safe_constraint = constraint if isinstance(constraint, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", constraint) else "unknown"
        logger.warning("Family Circle create conflict: exception=%s constraint=%s", type(original).__name__, safe_constraint)
        raise CircleAuthorityError("Family Circle membership conflict.") from exc

    return CircleIdentity(circle_id, membership_id, owner.id, CIRCLE_ROLE_OWNER)


async def add_membership(
    session: AsyncSession,
    *,
    circle_id: uuid.UUID,
    user: User,
    role: str,
    created_by_user_id: uuid.UUID | None,
) -> CircleIdentity:
    """Add a structurally valid member without granting caller authorization.

    The Phase 1C permission layer must authorize the actor before calling this
    primitive. This method enforces age-derived role correctness and D6 only.
    """
    canonical_role = _validated_role(user, role)
    if canonical_role == CIRCLE_ROLE_OWNER:
        raise CircleAuthorityError(
            "Owner membership is created with the circle; ownership transfer is a later lifecycle operation."
        )

    if await get_active_membership(session, user.id) is not None:
        raise CircleAuthorityError("This person already belongs to a Family Circle.")

    membership_id = uuid.uuid4()
    membership = CircleMembership(
        id=membership_id,
        circle_id=circle_id,
        user_id=user.id,
        role=canonical_role,
        status="active",
        created_by_user_id=created_by_user_id,
    )
    session.add(membership)

    try:
        await session.flush()
    except IntegrityError as exc:
        raise CircleAuthorityError("Family Circle membership conflict.") from exc

    return CircleIdentity(circle_id, membership_id, user.id, canonical_role)


async def list_active_memberships(
    session: AsyncSession,
    circle_id: uuid.UUID,
) -> list[CircleMembership]:
    return list(
        (
            await session.execute(
                select(CircleMembership)
                .where(
                    CircleMembership.circle_id == circle_id,
                    CircleMembership.status == "active",
                )
                .order_by(CircleMembership.joined_at.asc())
            )
        ).scalars().all()
    )


# Export names intentionally used by tests/future Phase 1C without broadening
# legacy product roles.
__all__ = [
    "CircleAuthorityError",
    "CircleIdentity",
    "create_circle",
    "add_membership",
    "get_active_membership",
    "list_active_memberships",
    "CIRCLE_ROLE_OWNER",
    "CIRCLE_ROLE_CO_ADMIN",
    "CIRCLE_ROLE_ADULT_MEMBER",
    "CIRCLE_ROLE_MINOR",
]
