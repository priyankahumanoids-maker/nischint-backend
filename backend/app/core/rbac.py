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
from sqlalchemy import select
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
STAFF_ROLES = frozenset({"admin", "operator"})


def get_user_roles(user: User, token: str = None) -> set:
    """
    Extract compatibility roles for a user.

    The local DB role is always included. Cognito groups may still contribute
    non-staff legacy/display roles, but provider `admin`/`operator` groups are
    deliberately ignored. Current staff authority must come from users.role so
    a stale provider token cannot survive a DB demotion.
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
                    provider_roles = normalize_roles(cognito_groups) & VALID_ROLES
                    roles.update(provider_roles - STAFF_ROLES)
        except Exception:
            pass

    return roles


async def _current_db_role(session: AsyncSession, user: User) -> tuple[str | None, bool]:
    """Load live role/active state for privilege-sensitive authorization.

    This intentionally bypasses the short user-cache window used by ordinary
    authenticated traffic. Staff demotion/deactivation must take effect on the
    next privileged request.
    """
    result = await session.execute(
        select(User.role, User.is_active).where(User.id == user.id)
    )
    row = result.first()
    if row is None:
        return None, False
    role = normalize_role(row[0]) if row[0] else None
    return role, bool(row[1])


def require_staff_role(allowed_roles: List[str], *, require_totp: bool = True):
    """Require a live DB staff role and, by default, authenticator TOTP proof.

    Provider groups never grant staff privilege. The optional `require_totp=False`
    mode is reserved for the enrollment/status/proof bootstrap endpoints so an
    already-authenticated current staff member can enroll without being locked out.
    """
    from app.api.deps import get_db_session

    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
    allowed = normalize_roles(allowed_roles) & STAFF_ROLES
    if not allowed:
        raise ValueError("require_staff_role requires admin/operator roles")

    async def _check_staff(
        request: Request,
        token: Annotated[str, Depends(oauth2_scheme)],
        session: AsyncSession = Depends(get_db_session),
    ) -> User:
        from app.api.deps import get_current_user as _get_user

        user = await _get_user(token, session)
        current_role, is_active = await _current_db_role(session, user)
        if not is_active or current_role not in allowed:
            logger.debug(
                "Staff RBAC denied: user_id=%s db_role=%s required=%s path=%s method=%s",
                getattr(user, "id", None), current_role, sorted(allowed),
                request.url.path, request.method,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Current staff role does not permit this action",
            )

        if require_totp:
            from app.services.auth_staff_totp_service import (
                get_staff_totp_state,
                verify_staff_proof,
            )

            totp_state = await get_staff_totp_state(session, user_id=user.id)
            if not totp_state["enabled"]:
                raise HTTPException(
                    status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                    detail={
                        "error": "staff_totp_enrollment_required",
                        "message": "Authenticator TOTP enrollment is required for staff access",
                    },
                )

            proof = str(request.headers.get("X-Nischint-Staff-Proof") or "").strip()
            if not proof or not verify_staff_proof(
                proof, user_id=user.id, access_token=token
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "staff_totp_proof_required",
                        "message": "A fresh authenticator TOTP proof is required",
                    },
                )

        return user

    return _check_staff


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

        # Staff authority is always refreshed from the DB. Provider staff
        # groups are compatibility metadata only and never grant privilege.
        allowed = normalize_roles(allowed_roles)
        if allowed & STAFF_ROLES:
            current_role, is_active = await _current_db_role(session, user)
            if not is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is inactive",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            user_roles = get_user_roles(user, token) - STAFF_ROLES
            if current_role:
                user_roles.add(current_role)
        else:
            user_roles = get_user_roles(user, token)

        # Check if user has any of the required roles
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
