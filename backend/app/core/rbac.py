# Role-Based Access Control (RBAC) Dependencies
#
# Provides require_role() — a FastAPI dependency that checks
# user roles from both Cognito groups (JWT) and local DB role column.
#
# Usage:
#   @router.get("/admin-only")
#   async def admin_only(user: User = Depends(require_role(["admin"]))):
#       ...

import logging
from typing import List, Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token_claims
from app.core.product_roles import (
    CANONICAL_ROLES,
    ROLE_PRIORITY,
    normalize_role,
    normalize_roles,
)
from app.models.user import User

logger = logging.getLogger(__name__)

# Valid roles in the product. Legacy/display aliases are normalized before
# authorization, but co_parent remains distinct from guardian.
VALID_ROLES = set(CANONICAL_ROLES)

# Retained for compatibility with existing imports. Authorization checks below
# are set-membership based; this mapping is not used to grant inherited access.
ROLE_HIERARCHY = dict(ROLE_PRIORITY)


def get_user_roles(user: User, token: str = None) -> set:
    """
    Extract all roles for a user from:
    1. Cognito JWT `cognito:groups` claim (primary when Cognito is enabled)
    2. Local DB `role` column (fallback / always included)

    Returns a set of role strings.
    """
    roles = set()

    # Always include local DB role
    if user.role:
        normalized = normalize_role(user.role)
        if normalized:
            roles.add(normalized)

    # Extract Cognito groups from token if available
    if token:
        try:
            claims = decode_token_claims(token)
            if claims:
                cognito_groups = claims.get("cognito:groups", [])
                if isinstance(cognito_groups, list):
                    roles.update(normalize_roles(cognito_groups) & VALID_ROLES)
        except Exception:
            pass

    return roles


def require_role(allowed_roles: List[str]):
    """
    FastAPI dependency factory for role-based access control.

    Usage:
        @router.get("/protected")
        async def endpoint(user: User = Depends(require_role(["admin", "guardian"]))):
            ...

    Checks:
    1. Cognito `cognito:groups` JWT claim
    2. Local DB `role` column
    If user has ANY of the allowed_roles, access is granted.
    """
    from app.api.deps import get_current_user, get_db_session

    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

    async def _check_role(
        request: Request,
        token: Annotated[str, Depends(oauth2_scheme)],
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        # First get the authenticated user
        from app.api.deps import get_current_user as _get_user
        user = await _get_user(token, session)

        # Get all roles
        user_roles = get_user_roles(user, token)

        # Check if user has any of the required roles
        allowed = normalize_roles(allowed_roles)
        if not user_roles.intersection(allowed):
            # DEBUG level: a 403 is a correct response, not an error condition.
            # Includes the request path so ops can triage misconfigured
            # frontends without log-level flags.
            logger.debug(
                f"RBAC denied: user={user.email} roles={user_roles} "
                f"required={allowed_roles} path={request.url.path} "
                f"method={request.method}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}",
            )

        return user

    return _check_role


def require_same_facility(user: User, target_facility_id: str = None):
    """
    Check that a user belongs to the same facility as the target.
    Admins bypass this check.
    """
    if not target_facility_id:
        return True

    if user.role == "admin":
        return True

    if user.facility_id != target_facility_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You don't belong to this facility.",
        )

    return True
