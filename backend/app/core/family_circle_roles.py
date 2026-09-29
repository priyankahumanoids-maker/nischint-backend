"""Canonical administrative roles for NISCHINT Family Circle v1.0.

These roles are intentionally separate from ``User.role`` / product-role aliases.
Product roles describe the legacy account persona; Circle roles describe what a
member may administer inside one Family Circle. Authorization itself is added in
Phase 1C.
"""
from __future__ import annotations

from datetime import date

from app.core.age_policy import is_minor

CIRCLE_ROLE_OWNER = "owner"
CIRCLE_ROLE_CO_ADMIN = "co_admin"
CIRCLE_ROLE_ADULT_MEMBER = "adult_member"
CIRCLE_ROLE_MINOR = "minor"

CIRCLE_ROLES = frozenset(
    {
        CIRCLE_ROLE_OWNER,
        CIRCLE_ROLE_CO_ADMIN,
        CIRCLE_ROLE_ADULT_MEMBER,
        CIRCLE_ROLE_MINOR,
    }
)

ADULT_CIRCLE_ROLES = frozenset(
    {
        CIRCLE_ROLE_OWNER,
        CIRCLE_ROLE_CO_ADMIN,
        CIRCLE_ROLE_ADULT_MEMBER,
    }
)


class CircleRoleError(ValueError):
    """Raised when a Circle role conflicts with age or the canonical vocabulary."""


def normalize_circle_role(role: object) -> str:
    value = str(role or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value not in CIRCLE_ROLES:
        raise CircleRoleError(f"Unsupported Family Circle role: {role!r}")
    return value


def role_for_date_of_birth(date_of_birth: date | None, requested_role: object) -> str:
    """Validate and return the Circle role allowed by the member's DOB.

    DOB remains the identity source of truth. An under-18 person can only hold
    the ``minor`` role. An adult cannot be stored as ``minor``. Missing DOB is
    intentionally rejected for new Circle membership; existing legacy users are
    not auto-enrolled by Phase 1B.
    """
    if date_of_birth is None:
        raise CircleRoleError("Date of birth is required for Family Circle membership.")

    role = normalize_circle_role(requested_role)
    minor = is_minor(date_of_birth)

    if minor and role != CIRCLE_ROLE_MINOR:
        raise CircleRoleError("A person under 18 must have the Minor circle role.")
    if not minor and role == CIRCLE_ROLE_MINOR:
        raise CircleRoleError("An adult cannot have the Minor circle role.")

    return role
