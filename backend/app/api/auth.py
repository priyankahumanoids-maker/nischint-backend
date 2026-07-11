# Authentication Router — Dual-mode: Local JWT + AWS Cognito
import logging
import random
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.cognito import is_cognito_enabled
from app.core.rate_limiter import limiter
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.user import RegisterRequest
from app.services import user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

INVITE_CODE_TTL_MINUTES = 15


def _generate_invite_code() -> str:
    """Generate a random 6-character alphanumeric invite code (uppercase, no ambiguous chars)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O,0,I,1
    return "".join(random.choices(alphabet, k=6))


# ── Family Circle Invite schemas ──

class GenerateInviteResponse(BaseModel):
    code: str
    expires_at: str   # ISO-8601


class VerifyInviteRequest(BaseModel):
    invite_code: str
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=100)
    phone: Optional[str] = None
    role: str = Field("child", pattern="^(child|woman|senior|family)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    refresh_token: Optional[str] = None
    cognito_id_token: Optional[str] = None
    cognito_username: Optional[str] = None
    auth_provider: str = "local"


class RefreshRequest(BaseModel):
    refresh_token: str
    email: Optional[str] = None
    cognito_username: Optional[str] = None


class ConfirmRequest(BaseModel):
    email: EmailStr
    code: str


class CognitoStatusResponse(BaseModel):
    enabled: bool
    region: str = ""
    user_pool_id: str = ""


# ── Registration ──

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    req: RegisterRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Register a new guardian account.
    Uses Cognito when enabled, falls back to local auth.
    """
    if is_cognito_enabled():
        return await _cognito_register(req, session)
    return await _local_register(req, session)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_request: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Authenticate user and return tokens.
    Uses Cognito when enabled, falls back to local auth.
    """
    if is_cognito_enabled():
        return await _cognito_login(login_request, session)
    return await _local_login(login_request, session)


@router.get("/me")
async def get_me(
    user: User = Depends(get_current_user),
):
    """Get current user info including roles."""
    from app.core.rbac import VALID_ROLES
    roles = [user.role] if user.role else []
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "roles": roles,
        "facility_id": user.facility_id,
        "cognito_sub": user.cognito_sub,
    }


@router.post("/refresh")
async def refresh(
    req: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Refresh tokens (Cognito only — local JWTs use re-login)."""
    if not is_cognito_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token refresh requires Cognito auth",
        )
    from app.core.cognito import refresh_tokens
    try:
        result = refresh_tokens(req.refresh_token, cognito_username=req.cognito_username or "", email=req.email or "")
        return {
            "access_token": result["access_token"],
            "id_token": result.get("id_token"),
            "expires_in": result["expires_in"],
            "auth_provider": "cognito",
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/confirm")
async def confirm(req: ConfirmRequest):
    """Confirm sign-up with verification code (Cognito only)."""
    if not is_cognito_enabled():
        raise HTTPException(status_code=400, detail="Cognito not enabled")
    from app.core.cognito import confirm_sign_up
    try:
        confirm_sign_up(req.email, req.code)
        return {"confirmed": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/login-health")
async def login_health():
    """Lightweight health check for the auth subsystem."""
    return {"status": "ok", "auth": "operational"}


@router.get("/cognito-status")
async def cognito_status():
    """Check if Cognito auth is enabled."""
    from app.core.config import settings
    return CognitoStatusResponse(
        enabled=is_cognito_enabled(),
        region=settings.aws_region if is_cognito_enabled() else "",
        user_pool_id=settings.cognito_user_pool_id if is_cognito_enabled() else "",
    )


# ── Family Circle Invite Endpoints ──

@router.post("/family/generate-invite-code", response_model=GenerateInviteResponse)
async def generate_invite_code(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Guardian generates a 6-character invite code.
    Stores it in users.invite_code + users.invite_code_expires_at (15-minute TTL).
    Calling again overwrites the previous code.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select

    if user.role not in ("guardian", "parent", "admin"):
        raise HTTPException(status_code=403, detail="Only guardian accounts can generate invite codes")

    code = _generate_invite_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=INVITE_CODE_TTL_MINUTES)

    # Re-fetch inside this session so we can mutate it
    result = await session.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    db_user.invite_code = code
    db_user.invite_code_expires_at = expires_at
    await session.commit()

    logger.info(f"[INVITE] Guardian {user.email} generated invite code (expires {expires_at.isoformat()})")
    return GenerateInviteResponse(code=code, expires_at=expires_at.isoformat())


@router.post("/family/verify-invite-code", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def verify_invite_code(
    request: Request,
    req: VerifyInviteRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """
    New family member submits the guardian's 6-character invite code.
    Looks up the guardian by users.invite_code, checks expiry,
    creates the new user account with guardian_id set, then clears the code.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select

    # 1. Validate the code — look up guardian by invite_code
    result = await session.execute(
        select(User).where(User.invite_code == req.invite_code)
    )
    guardian = result.scalar_one_or_none()

    if not guardian:
        raise HTTPException(status_code=400, detail="Invalid invite code")

    # 2. Check expiry
    now = datetime.now(timezone.utc)
    if not guardian.invite_code_expires_at or guardian.invite_code_expires_at < now:
        raise HTTPException(status_code=400, detail="Invite code has expired")

    # 3. Prevent duplicate email
    existing = await user_service.get_user_by_email(session, req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # 4. Create the new family member account linked to the guardian
    new_user = User(
        email=req.email,
        password_hash=await user_service.hash_password_async(req.password),
        role=req.role,
        full_name=req.full_name,
        phone=req.phone,
        guardian_id=guardian.id,
    )
    session.add(new_user)

    # 5. Clear the used invite code so it cannot be reused
    guardian.invite_code = None
    guardian.invite_code_expires_at = None

    await session.commit()
    await session.refresh(new_user)

    logger.info(
        f"[INVITE] New user {new_user.email} (role={new_user.role}) "
        f"joined family of guardian {guardian.email} (id={guardian.id})"
    )

    access_token = create_access_token(data={
        "sub": str(new_user.id),
        "role": new_user.role,
        "email": new_user.email,
        "full_name": new_user.full_name,
    })
    return TokenResponse(access_token=access_token, role=new_user.role, auth_provider="local")


# ── My Guardian ──

class GuardianInfoResponse(BaseModel):
    id: str
    full_name: str | None
    email: str
    phone: str | None


@router.get("/my-guardian", response_model=GuardianInfoResponse)
async def get_my_guardian(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Returns the guardian linked to the current user via users.guardian_id.
    Intended for child/woman/senior/family accounts to display their
    guardian's name in their Settings screen.
    """
    from sqlalchemy import select

    if not user.guardian_id:
        raise HTTPException(status_code=404, detail="No guardian linked to your account")

    result = await session.execute(select(User).where(User.id == user.guardian_id))
    guardian = result.scalar_one_or_none()

    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian account not found")

    return GuardianInfoResponse(
        id=str(guardian.id),
        full_name=guardian.full_name,
        email=guardian.email,
        phone=guardian.phone,
    )


# ── Local Auth Flows ──

async def _local_register(req: RegisterRequest, session: AsyncSession) -> TokenResponse:
    existing = await user_service.get_user_by_email(session, req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=req.email,
        password_hash=await user_service.hash_password_async(req.password),
        role="guardian",
        phone=req.phone,
        full_name=req.full_name,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
    })
    return TokenResponse(access_token=access_token, role=user.role, auth_provider="local")


async def _local_login(login_request: LoginRequest, session: AsyncSession) -> TokenResponse:
    # Per-account login backoff (defense-in-depth on top of slowapi
    # IP limiter). Stops credential-stuffing without locking out
    # legitimate users behind shared NATs / mobile carriers.
    from app.core.login_backoff import check_lock, record_failure, reset
    lock = check_lock(login_request.email)
    if lock.locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many failed attempts on this account. "
                f"Try again in {lock.retry_after}s."
            ),
            headers={
                "Retry-After": str(lock.retry_after),
                "WWW-Authenticate": "Bearer",
            },
        )

    user = await user_service.get_user_by_email(session, login_request.email)

    if not user:
        record_failure(login_request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not await user_service.verify_password_async(login_request.password, user.password_hash):
        record_failure(login_request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Successful auth — clear the failure counter so a forgetful user
    # who finally types the right password isn't penalised.
    reset(login_request.email)

    # Warm the auth user cache so the next call to /api/auth/me (and any
    # other authenticated endpoint within the 30s TTL window) skips the
    # ~2s Mumbai pooler round-trip in `get_current_user`.
    from app.services import user_cache
    user_cache.cache_user(str(user.id), user)

    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
    })

    return TokenResponse(access_token=access_token, role=user.role, auth_provider="local")


# ── Cognito Auth Flows ──

async def _cognito_register(req: RegisterRequest, session: AsyncSession) -> TokenResponse:
    from app.core.cognito import sign_up, admin_confirm_user, sign_in

    # Check local DB
    existing = await user_service.get_user_by_email(session, req.email)
    if existing and existing.cognito_sub:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # Register in Cognito
    try:
        result = sign_up(
            email=req.email,
            password=req.password,
            full_name=req.full_name or "",
            phone=req.phone or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cognito_sub = result["user_sub"]

    # Auto-confirm for development (skip email verification)
    try:
        admin_confirm_user(req.email)
    except Exception as e:
        logger.warning(f"Could not auto-confirm user {req.email}: {e}")

    # Sign in to get tokens
    try:
        auth_result = sign_in(req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Registration successful but login failed: {e}")

    # Auto-provision local DB user
    if existing:
        existing.cognito_sub = cognito_sub
        if req.full_name and not existing.full_name:
            existing.full_name = req.full_name
        user = existing
    else:
        user = User(
            email=req.email,
            password_hash=await user_service.hash_password_async(req.password),
            cognito_sub=cognito_sub,
            role="guardian",
            phone=req.phone,
            full_name=req.full_name,
        )
        session.add(user)

    await session.commit()
    if not existing:
        await session.refresh(user)

    # Also create a local JWT for backward compatibility
    local_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
    })

    return TokenResponse(
        access_token=local_token,
        role=user.role,
        refresh_token=auth_result.get("refresh_token"),
        cognito_id_token=auth_result.get("id_token"),
        cognito_username=auth_result.get("cognito_username"),
        auth_provider="cognito",
    )


async def _cognito_login(login_request: LoginRequest, session: AsyncSession) -> TokenResponse:
    from app.core.cognito import sign_in

    # Authenticate with Cognito
    try:
        auth_result = sign_in(login_request.email, login_request.password)
    except ValueError as e:
        error_str = str(e)
        # User-action-required states — do NOT fall back (user needs to act)
        if "UserNotConfirmedException" in error_str:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Account not confirmed. Please verify your email.")
        if "PasswordResetRequiredException" in error_str:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Password reset required. Please reset your password.")
        # All other Cognito errors — infrastructure failure OR invalid credentials → fall back to local auth.
        # Covers: NotAuthorizedException, UserNotFoundException (user-level),
        # ResourceNotFoundException, InternalErrorException, InvalidParameterException,
        # network errors, boto3 ClientError, etc. (infra-level)
        logger.warning(
            f"LOGIN_COGNITO_FALLBACK email={login_request.email} cognito_error='{error_str[:200]}' "
            f"→ attempting local Postgres auth"
        )
        return await _local_login(login_request, session)

    # Handle challenges
    if "challenge" in auth_result:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Auth challenge required: {auth_result['challenge']}",
        )

    # Auto-provision local user
    from app.core.cognito import verify_cognito_token
    id_token = auth_result.get("id_token", "")
    claims = verify_cognito_token(id_token) if id_token else None

    cognito_sub = claims.get("sub") if claims else None
    email = claims.get("email", login_request.email) if claims else login_request.email
    name = claims.get("name", "") if claims else ""

    user = None
    if cognito_sub:
        user = await user_service.get_user_by_cognito_sub(session, cognito_sub)

    if not user:
        user = await user_service.get_user_by_email(session, email)
        if user and cognito_sub:
            user.cognito_sub = cognito_sub
            await session.flush()

    if not user and cognito_sub:
        user = await user_service.auto_provision_cognito_user(
            session, cognito_sub, email, name,
        )
        await session.commit()

    if not user:
        # Last resort: create local user
        user = await user_service.get_user_by_email(session, email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to provision user account",
            )

    # Extract Cognito groups from claims
    cognito_groups = claims.get("cognito:groups", []) if claims else []

    # Sync role from Cognito groups to local DB (pick highest KNOWN priority)
    if cognito_groups:
        role_priority = {"admin": 5, "operator": 4, "caregiver": 3, "guardian": 2, "child": 1}
        known_roles = [r for r in cognito_groups if r in role_priority]
        if known_roles:
            best_role = max(known_roles, key=lambda r: role_priority[r])
            if user.role != best_role:
                user.role = best_role
                await session.flush()

    # Create local JWT for API calls (includes cognito:groups for RBAC)
    local_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
        "cognito:groups": cognito_groups,
    })

    return TokenResponse(
        access_token=local_token,
        role=user.role,
        refresh_token=auth_result.get("refresh_token"),
        cognito_id_token=auth_result.get("id_token"),
        cognito_username=auth_result.get("cognito_username"),
        auth_provider="cognito",
    )
