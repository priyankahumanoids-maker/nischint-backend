# API Dependencies
import logging
import time
from typing import Annotated, AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_token, decode_token_claims
from app.db.session import async_session
from app.models.user import User
from app.services import auth_metrics, user_cache, user_service

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database session.
    Handles commit on success, rollback on exception.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    Supports both local JWT (sub = user UUID) and Cognito JWT (sub = cognito_sub).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Verify token and extract sub
    user_id_or_sub = verify_token(token)
    if user_id_or_sub is None:
        raise credentials_exception

    # Fast path: short-window user cache (30s TTL).
    # Cuts the ~2s Mumbai pooler round-trip every authed endpoint pays.
    t0 = time.perf_counter()
    cached = user_cache.get_cached_user(user_id_or_sub)
    if cached is not None:
        auth_metrics.record((time.perf_counter() - t0) * 1000, cache_hit=True)
        return cached

    # Try loading by local UUID first
    user = None
    try:
        user = await user_service.get_user_by_id(session, UUID(user_id_or_sub))
    except ValueError:
        # Not a valid UUID — might be a Cognito sub
        pass

    # If not found by UUID, try Cognito sub
    if user is None:
        user = await user_service.get_user_by_cognito_sub(session, user_id_or_sub)

    # If still not found but we have a valid Cognito token, auto-provision
    if user is None:
        from app.core.cognito import is_cognito_enabled
        if is_cognito_enabled():
            claims = decode_token_claims(token)
            if claims:
                email = claims.get("email", "")
                name = claims.get("name", "")
                cognito_sub = claims.get("sub", user_id_or_sub)
                if email:
                    user = await user_service.auto_provision_cognito_user(
                        session, cognito_sub, email, name,
                    )
                    await session.commit()
                    logger.info(f"Auto-provisioned user {email} from Cognito sub {cognito_sub}")

    if user is None:
        raise credentials_exception

    # Warm the cache for subsequent requests in the same TTL window.
    user_cache.cache_user(user_id_or_sub, user)
    auth_metrics.record((time.perf_counter() - t0) * 1000, cache_hit=False)
    return user



def require_role(role: str | list[str]):
    """Dependency factory: require the current user to have a specific role
    (or be a member of any role in a list).

    Backwards-compatible: pass a string for single-role checks (existing
    callers), or a list of strings to allow any of several roles
    (OCE-01 needed `guardian | operator | admin`).
    """
    allowed = {role} if isinstance(role, str) else set(role)

    async def _check(user: User = Depends(get_current_user)) -> User:
        user_roles = []
        if hasattr(user, 'roles') and user.roles:
            user_roles = user.roles if isinstance(user.roles, list) else [user.roles]
        if hasattr(user, 'role') and user.role:
            user_roles.append(user.role)
        if not (allowed & set(user_roles)):
            detail = (
                f"Role '{role}' required"
                if isinstance(role, str)
                else f"One of roles {sorted(allowed)} required"
            )
            raise HTTPException(status_code=403, detail=detail)
        return user
    return _check


async def get_current_user_active(
    user: User = Depends(get_current_user),
) -> User:
    """Variant of `get_current_user` that REJECTS frozen accounts.

    Returns the user only if `users.deleted_at IS NULL` (DPDP-01 erasure
    not pending). Otherwise raises HTTP 451 Unavailable For Legal Reasons
    — semantically precise here: the account is being processed under
    a DPDP §17 right-to-erasure request, and write access is suspended
    pending the grace window.

    Use this in place of `get_current_user` for any endpoint that
    mutates user-owned state. The cancel endpoint MUST keep using the
    base `get_current_user` so frozen users can rescue themselves.
    """
    if getattr(user, "deleted_at", None) is not None:
        raise HTTPException(
            status_code=451,
            detail={
                "error": "account_frozen_pending_erasure",
                "message": (
                    "Your account is marked for erasure. Writes are "
                    "suspended until the request is cancelled or "
                    "executed. Visit /api/privacy/erasure-requests/me "
                    "to manage the request."
                ),
            },
        )
    return user
