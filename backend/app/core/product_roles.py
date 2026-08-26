"""Canonical NISCHINT account-role vocabulary.

This module normalizes legacy/display aliases without changing the product's
permission boundaries. In particular, ``co_parent`` remains distinct from
``guardian`` so monitoring access can be granted deliberately without
accidentally granting primary-owner/billing powers.
"""
from __future__ import annotations

from collections.abc import Iterable

CANONICAL_ROLES = {
    "admin",
    "operator",
    "caregiver",
    "guardian",
    "co_parent",
    "child",
    "woman",
    "senior",
    "family",
    "user",
}

ROLE_ALIASES = {
    # Primary guardian / parent terminology
    "parent": "guardian",
    "parents": "guardian",
    "primary_guardian": "guardian",
    "primary-guardian": "guardian",
    "primary parent": "guardian",
    "primary_parent": "guardian",
    # Co-guardian / co-parent terminology
    "co-parent": "co_parent",
    "coparent": "co_parent",
    "co parent": "co_parent",
    "co_guardian": "co_parent",
    "co-guardian": "co_parent",
    "co guardian": "co_parent",
    # Protected child terminology
    "kid": "child",
    "kids": "child",
    "children": "child",
    "protected_child": "child",
    "dependent": "child",
    # Woman terminology
    "women": "woman",
    # Senior terminology
    "elder": "senior",
    "elderly": "senior",
    "senior_citizen": "senior",
    "senior-citizen": "senior",
    # Generic protected-family-member terminology
    "family_member": "family",
    "family-member": "family",
    "family member": "family",
    "member": "family",
    "protected_member": "family",
    "protected-member": "family",
}

PRIMARY_GUARDIAN_ROLES = {"guardian"}
CO_GUARDIAN_ROLES = {"co_parent"}
GUARDIAN_MONITOR_ROLES = PRIMARY_GUARDIAN_ROLES | CO_GUARDIAN_ROLES
PROTECTED_MEMBER_ROLES = {"child", "woman", "senior", "family"}
SYSTEM_ROLES = {"admin", "operator", "caregiver", "user"}

# Priority is used only to pick a single local role when Cognito provides
# multiple groups. It is not an authorization hierarchy.
ROLE_PRIORITY = {
    "admin": 100,
    "operator": 90,
    "caregiver": 80,
    "guardian": 70,
    "co_parent": 60,
    "child": 50,
    "woman": 50,
    "senior": 50,
    "family": 50,
    "user": 10,
}


def normalize_role(role: object) -> str:
    """Return a canonical lowercase role, preserving unknown values safely."""
    value = str(role or "").strip().lower()
    if not value:
        return ""
    return ROLE_ALIASES.get(value, value)


def normalize_roles(roles: Iterable[object] | object | None) -> set[str]:
    """Normalize one role or an iterable of roles into a non-empty set."""
    if roles is None:
        return set()
    if isinstance(roles, str):
        values = [roles]
    else:
        try:
            values = list(roles)  # type: ignore[arg-type]
        except TypeError:
            values = [roles]
    normalized = {normalize_role(role) for role in values}
    normalized.discard("")
    return normalized


def known_roles(roles: Iterable[object] | object | None) -> set[str]:
    """Return only normalized roles that belong to NISCHINT's known vocabulary."""
    return normalize_roles(roles) & CANONICAL_ROLES


def select_primary_role(roles: Iterable[object] | object | None) -> str | None:
    """Pick a deterministic canonical role from Cognito/local role candidates."""
    candidates = known_roles(roles)
    if not candidates:
        return None
    return max(candidates, key=lambda role: (ROLE_PRIORITY.get(role, 0), role))


def is_primary_guardian(role: object) -> bool:
    return normalize_role(role) in PRIMARY_GUARDIAN_ROLES


def is_co_guardian(role: object) -> bool:
    return normalize_role(role) in CO_GUARDIAN_ROLES


def is_guardian_monitor(role: object) -> bool:
    return normalize_role(role) in GUARDIAN_MONITOR_ROLES


def is_protected_member(role: object) -> bool:
    return normalize_role(role) in PROTECTED_MEMBER_ROLES
