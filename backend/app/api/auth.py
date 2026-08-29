# Authentication Router â€” Dual-mode: Local JWT + AWS Cognito
import asyncio
import hashlib
import hmac
import logging
import random
import secrets
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.cognito import is_cognito_enabled
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.product_roles import normalize_roles, select_primary_role
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    decode_local_token_claims,
)
from app.models.user import User
from app.schemas.user import RegisterRequest
from app.services import user_service, user_cache
from app.services.auth_session_service import (
    bump_user_token_epoch,
    create_auth_session,
    list_auth_sessions,
    revoke_all_auth_sessions,
    revoke_auth_session,
    touch_auth_session,
    validate_auth_session,
    validate_legacy_token_epoch,
)
from app.services.auth_otp_service import (
    EMAIL_VERIFICATION_PURPOSE,
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN_SECONDS,
    OTP_TTL_SECONDS,
    consume_otp,
    is_email_verified,
    mark_email_verified,
    store_otp,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Product rule: a family scanner/code is intentionally short-lived. It is
# valid for 15 minutes at most and is consumed immediately by one successful
# join. The server expiry remains the source of truth for every client.
INVITE_CODE_TTL_MINUTES = 15

# Password recovery is intentionally separate from registration OTP.
# Reset codes are short-lived and one-time-use. Cognito owns delivery when
# enabled; local fallback accounts use SendGrid + durable PostgreSQL state.
PASSWORD_RESET_TTL_SECONDS = 15 * 60
PASSWORD_RESET_MAX_ATTEMPTS = 5


async def _claim_local_refresh_once(
    session: AsyncSession,
    refresh_token: str,
    claims: dict,
    user_id: uuid.UUID,
) -> bool:
    """Atomically consume one local refresh credential in PostgreSQL.

    New refresh tokens carry a unique ``jti``. Refresh tokens issued before
    AUTH-03 are migrated transparently by using the SHA-256 fingerprint of the
    exact signed token as their durable identifier.

    ``token_id`` is a primary key, so concurrent refresh attempts served by
    separate Cloud Run instances cannot both consume the same credential.
    """
    import time

    token_id = str(claims.get("jti") or "").strip()

    if not token_id:
        token_id = hashlib.sha256(
            str(refresh_token).encode("utf-8")
        ).hexdigest()

    try:
        expires_at_epoch = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        expires_at_epoch = 0

    if expires_at_epoch <= 0:
        expires_at_epoch = (
            int(time.time())
            + int(settings.jwt_refresh_expires_days) * 24 * 60 * 60
        )

    try:
        result = await session.execute(
            text(
                """
                INSERT INTO auth_refresh_consumptions (
                    token_id,
                    user_id,
                    expires_at,
                    consumed_at
                )
                VALUES (
                    :token_id,
                    CAST(:user_id AS UUID),
                    to_timestamp(:expires_at_epoch),
                    NOW()
                )
                ON CONFLICT (token_id) DO NOTHING
                RETURNING token_id
                """
            ),
            {
                "token_id": token_id,
                "user_id": str(user_id),
                "expires_at_epoch": expires_at_epoch,
            },
        )
    except Exception as exc:
        await session.rollback()
        logger.error(
            "AUTH_REFRESH_GUARD_DB_ERROR error=%s",
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Session refresh is temporarily unavailable. "
                "Please try again."
            ),
        )

    return result.scalar_one_or_none() is not None

def _normalize_email(email: str) -> str:
    return str(email or "").strip().casefold()


def _password_reset_cache_key(email: str) -> str:
    # Avoid placing raw email addresses in auth-state storage or logs.
    return hashlib.sha256(_normalize_email(email).encode("utf-8")).hexdigest()


def _password_reset_digest(email: str, code: str) -> str:
    payload = f"{_normalize_email(email)}:{str(code or '').strip()}".encode("utf-8")
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


async def _store_local_password_reset(
    session: AsyncSession,
    email: str,
    code: str,
) -> None:
    email_hash = _password_reset_cache_key(email)
    digest = _password_reset_digest(email, code)

    try:
        await session.execute(
            text(
                """
                INSERT INTO auth_password_resets (
                    email_hash,
                    code_digest,
                    attempts,
                    expires_at,
                    created_at
                )
                VALUES (
                    :email_hash,
                    :code_digest,
                    0,
                    NOW() + (:ttl_seconds * INTERVAL '1 second'),
                    NOW()
                )
                ON CONFLICT (email_hash)
                DO UPDATE SET
                    code_digest = EXCLUDED.code_digest,
                    attempts = 0,
                    expires_at = EXCLUDED.expires_at,
                    created_at = NOW()
                """
            ),
            {
                "email_hash": email_hash,
                "code_digest": digest,
                "ttl_seconds": PASSWORD_RESET_TTL_SECONDS,
            },
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "AUTH_PASSWORD_RESET_STORE_DB_ERROR error=%s",
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset service is temporarily unavailable.",
        )


async def _consume_local_password_reset(
    session: AsyncSession,
    email: str,
    code: str,
) -> bool:
    """Validate and consume one local password-reset code.

    ``FOR UPDATE`` serializes concurrent attempts for the same account so a
    valid code cannot be successfully consumed twice.
    """
    email_hash = _password_reset_cache_key(email)

    try:
        # Remove an expired record for this account before attempting use.
        await session.execute(
            text(
                """
                DELETE FROM auth_password_resets
                WHERE email_hash = :email_hash
                  AND expires_at <= NOW()
                """
            ),
            {"email_hash": email_hash},
        )

        result = await session.execute(
            text(
                """
                SELECT code_digest, attempts
                FROM auth_password_resets
                WHERE email_hash = :email_hash
                  AND expires_at > NOW()
                FOR UPDATE
                """
            ),
            {"email_hash": email_hash},
        )

        row = result.mappings().first()

        if not row:
            await session.commit()
            return False

        attempts = int(row["attempts"] or 0)

        if attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
            await session.execute(
                text(
                    """
                    DELETE FROM auth_password_resets
                    WHERE email_hash = :email_hash
                    """
                ),
                {"email_hash": email_hash},
            )
            await session.commit()
            return False

        expected = str(row["code_digest"] or "")
        supplied = _password_reset_digest(email, code)

        if not expected or not hmac.compare_digest(expected, supplied):
            attempts += 1

            if attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
                await session.execute(
                    text(
                        """
                        DELETE FROM auth_password_resets
                        WHERE email_hash = :email_hash
                        """
                    ),
                    {"email_hash": email_hash},
                )
            else:
                await session.execute(
                    text(
                        """
                        UPDATE auth_password_resets
                        SET attempts = :attempts
                        WHERE email_hash = :email_hash
                        """
                    ),
                    {
                        "attempts": attempts,
                        "email_hash": email_hash,
                    },
                )

            await session.commit()
            return False

        # Keep successful code consumption in the caller's transaction.
        # reset_password() will update password_hash and commit both changes
        # atomically, so a failed password update does not burn a valid code.
        await session.execute(
            text(
                """
                DELETE FROM auth_password_resets
                WHERE email_hash = :email_hash
                """
            ),
            {"email_hash": email_hash},
        )

        return True

    except HTTPException:
        raise
    except Exception as exc:
        await session.rollback()
        logger.error(
            "AUTH_PASSWORD_RESET_CONSUME_DB_ERROR error=%s",
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset service is temporarily unavailable.",
        )


async def _send_local_password_reset_email(email: str, code: str) -> bool:
    from app.services.email_service import send_email

    subject = "Reset your Nischint password"
    text_body = (
        f"Your Nischint password reset code is {code}. "
        "It expires in 15 minutes. If you did not request this, ignore this email."
    )
    html_body = (
        "<p>Your Nischint password reset code is:</p>"
        f"<p style='font-size:24px;font-weight:700;letter-spacing:4px'>{code}</p>"
        "<p>This code expires in 15 minutes.</p>"
        "<p>If you did not request this reset, you can safely ignore this email.</p>"
    )
    return await asyncio.to_thread(
        send_email,
        email,
        subject,
        html_body,
        text_body,
    )


def _generate_invite_code() -> str:
    """Generate a random 6-character alphanumeric invite code (uppercase, no ambiguous chars)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O,0,I,1
    return "".join(random.choices(alphabet, k=6))


# â”€â”€ Family Circle Invite schemas â”€â”€

class GenerateInviteResponse(BaseModel):
    code: str
    expires_at: str   # ISO-8601


class VerifyInviteRequest(BaseModel):
    invite_code: str
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=10, max_length=20)
    role: str = Field("child", pattern="^(child|woman|senior|family|co_parent)$")


class ValidateInviteRequest(BaseModel):
    invite_code: str = Field(min_length=6, max_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    refresh_token: Optional[str] = None
    session_id: Optional[str] = None
    cognito_id_token: Optional[str] = None
    cognito_username: Optional[str] = None
    auth_provider: str = "local"


class RefreshRequest(BaseModel):
    refresh_token: str
    session_id: Optional[str] = None
    email: Optional[str] = None
    cognito_username: Optional[str] = None


class ConfirmRequest(BaseModel):
    email: EmailStr
    code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=12)
    password: str = Field(min_length=8, max_length=128)


class CheckPhoneRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


class EmailVerificationConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class CognitoStatusResponse(BaseModel):
    enabled: bool
    region: str = ""
    user_pool_id: str = ""


def _current_local_session_id(request: Request) -> Optional[str]:
    auth_header = str(request.headers.get("authorization") or "").strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    claims = decode_local_token_claims(token)
    if not claims or claims.get("type") == "refresh":
        return None
    sid = str(claims.get("sid") or "").strip()
    return sid or None


async def _issue_local_session_response(
    session: AsyncSession,
    user: User,
    request: Request,
    *,
    provider: str = "local",
    extra_claims: Optional[dict] = None,
) -> TokenResponse:
    sid = await create_auth_session(
        session,
        user.id,
        provider=provider,
        request=request,
    )
    claims = {
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
        "sid": sid,
        "auth_provider": provider,
    }
    if extra_claims:
        claims.update(extra_claims)
    access_token = create_access_token(data=claims)
    refresh_token = create_refresh_token(
        data={"sub": str(user.id), "sid": sid, "provider": provider}
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        session_id=sid,
        role=user.role,
        auth_provider=provider,
    )


async def _send_email_verification_email(email: str, code: str) -> bool:
    from app.services.email_service import send_email

    subject = "Verify your Nischint email"
    text_body = (
        f"Your Nischint email verification code is {code}. "
        "It expires in 10 minutes. If you did not request this, ignore this email."
    )
    html_body = (
        "<p>Your Nischint email verification code is:</p>"
        f"<p style='font-size:24px;font-weight:700;letter-spacing:4px'>{code}</p>"
        "<p>This code expires in 10 minutes.</p>"
    )
    return await asyncio.to_thread(
        send_email,
        email,
        subject,
        html_body,
        text_body,
    )


# â”€â”€ Registration â”€â”€

def _normalize_phone(phone: Optional[str]) -> str:
    """Store Indian mobile numbers in the E.164 form Cognito expects."""
    digits = "".join(character for character in str(phone or "") if character.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return f"+{digits}" if digits else ""


def _require_normalized_phone(phone: Optional[str]) -> str:
    """Return a usable E.164-style phone or reject registration explicitly.

    Registration must never silently create a user with ``phone = NULL`` when
    the UI step is expected to collect a mobile number.
    """
    normalized = _normalize_phone(phone)
    digits = normalized.lstrip("+")

    if not normalized or len(digits) < 10 or len(digits) > 15:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid mobile number is required.",
        )

    return normalized


async def _phone_exists(
    session: AsyncSession,
    phone: Optional[str],
    exclude_user_id: Optional[uuid.UUID] = None,
) -> bool:
    from sqlalchemy import func, select

    normalized = _normalize_phone(phone)
    digits = normalized.lstrip("+")[-10:]
    if not digits:
        return False
    query = select(User.id).where(
        func.right(func.regexp_replace(User.phone, r"\D", "", "g"), 10) == digits
    )
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)

    result = await session.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


@router.post("/check-phone")
async def check_phone(
    req: CheckPhoneRequest,
    session: AsyncSession = Depends(get_db_session),
):
    return {"exists": await _phone_exists(session, req.phone)}

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
        return await _cognito_register(req, session, request)
    return await _local_register(req, session, request)


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
        return await _cognito_login(login_request, session, request)
    return await _local_login(login_request, session, request)


@router.get("/me")
async def get_me(
    user: User = Depends(get_current_user),
):
    """Get current user info including roles."""
    roles = [user.role] if user.role else []
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "roles": roles,
        "facility_id": user.facility_id,
        "cognito_sub": user.cognito_sub,
    }


class UpdateMyPhoneRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


@router.patch("/me/phone")
async def update_my_phone(
    req: UpdateMyPhoneRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Update the signed-in user's registered mobile number.

    This also provides a safe repair path for legacy accounts that were
    created by older clients which accidentally dropped the phone field.
    """
    from sqlalchemy import select
    normalized_phone = _require_normalized_phone(req.phone)

    if await _phone_exists(
        session,
        normalized_phone,
        exclude_user_id=user.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mobile number is already registered. Please use another number.",
        )

    result = await session.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User account not found")

    db_user.phone = normalized_phone
    await session.commit()

    user_cache.invalidate_user_keys(
        str(db_user.id),
        str(db_user.cognito_sub or ""),
    )

    return {
        "updated": True,
        "phone": normalized_phone,
    }


@router.post("/session", response_model=TokenResponse)
@limiter.limit("10/minute")
async def upgrade_local_session(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Upgrade a valid legacy access-token session into AUTH-04."""
    response = await _issue_local_session_response(
        session,
        user,
        request,
        provider="local",
    )
    await session.commit()
    return response


@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    req: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Rotate a refresh credential inside one durable AUTH-04 session."""
    local_claims = decode_refresh_token(req.refresh_token)
    if local_claims:
        from sqlalchemy import select

        try:
            refresh_user_id = uuid.UUID(str(local_claims["sub"]))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh session is invalid or expired",
            )

        result = await session.execute(
            select(User).where(User.id == refresh_user_id)
        )
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh session is no longer valid",
            )

        sid = str(local_claims.get("sid") or "").strip()
        if sid:
            session_valid = await validate_auth_session(
                session,
                sid,
                refresh_user_id,
                token_iat=local_claims.get("iat"),
            )
        else:
            session_valid = await validate_legacy_token_epoch(
                session,
                refresh_user_id,
                token_iat=local_claims.get("iat"),
            )
        if not session_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh session is no longer valid",
            )

        if not await _claim_local_refresh_once(
            session,
            req.refresh_token,
            local_claims,
            refresh_user_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh session has already been used",
            )

        # Legacy refresh credentials are migrated into one durable session on
        # first successful rotation.  New tokens keep the same session id.
        if not sid:
            sid = await create_auth_session(
                session,
                user.id,
                provider="local",
                request=request,
            )
        else:
            if not await touch_auth_session(
                session,
                sid,
                user.id,
                extend_expiry=True,
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh session is no longer valid",
                )

        session_provider = str(local_claims.get("provider") or "local")
        token_claims = {
            "sub": str(user.id),
            "role": user.role,
            "email": user.email,
            "full_name": user.full_name,
            "sid": sid,
            "auth_provider": session_provider,
        }
        next_access_token = create_access_token(data=token_claims)
        next_refresh_token = create_refresh_token(
            data={
                "sub": str(user.id),
                "sid": sid,
                "provider": session_provider,
            }
        )

        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.error(
                "AUTH_REFRESH_ROTATION_COMMIT_ERROR error=%s",
                str(exc)[:200],
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Session refresh is temporarily unavailable. "
                    "Please try again."
                ),
            )

        return TokenResponse(
            access_token=next_access_token,
            refresh_token=next_refresh_token,
            session_id=sid,
            role=user.role,
            auth_provider=session_provider,
        )

    if not is_cognito_enabled():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is invalid or expired",
        )

    from app.core.cognito import refresh_tokens
    try:
        provider_result = refresh_tokens(
            req.refresh_token,
            cognito_username=req.cognito_username or "",
            email=req.email or "",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    # AUTH-04 session binding for Cognito-backed users.  Existing third-party
    # clients without email/session metadata retain the historical provider
    # response until they next perform a full login.
    user = None
    if req.email:
        user = await user_service.get_user_by_email(
            session,
            _normalize_email(req.email),
        )

    if not user:
        return {
            "access_token": provider_result["access_token"],
            "id_token": provider_result.get("id_token"),
            "expires_in": provider_result["expires_in"],
            "auth_provider": "cognito",
        }

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is no longer valid",
        )

    sid = str(req.session_id or "").strip()
    if sid:
        if not await validate_auth_session(session, sid, user.id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh session is no longer valid",
            )
        await touch_auth_session(session, sid, user.id, extend_expiry=True)
    else:
        sid = await create_auth_session(
            session,
            user.id,
            provider="cognito",
            request=request,
        )

    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
        "sid": sid,
    })
    await session.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=req.refresh_token,
        session_id=sid,
        role=user.role,
        cognito_id_token=provider_result.get("id_token"),
        cognito_username=req.cognito_username,
        auth_provider="cognito",
    )


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


@router.get("/email-verification/status")
async def email_verification_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    verified = await is_email_verified(
        session,
        user_id=user.id,
        email=user.email,
    )
    return {"verified": verified, "email": user.email}


@router.post("/email-verification/request", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def request_email_verification(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a hashed verification OTP without enforcing it on login yet."""
    if await is_email_verified(session, user_id=user.id, email=user.email):
        return {
            "accepted": True,
            "verified": True,
            "delivery_sent": False,
        }

    code = f"{secrets.randbelow(1_000_000):06d}"
    retry_after = await store_otp(
        session,
        email=user.email,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        code=code,
    )
    if retry_after > 0:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "A verification code was requested recently. "
                f"Try again in {retry_after} seconds."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    await session.commit()
    sent = await _send_email_verification_email(user.email, code)
    if not sent:
        logger.warning(
            "Email verification delivery unavailable for %s",
            user.email,
        )

    return {
        "accepted": True,
        "verified": False,
        "delivery_sent": bool(sent),
        "expires_in_seconds": OTP_TTL_SECONDS,
        "resend_cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS,
        "max_attempts": OTP_MAX_ATTEMPTS,
    }


@router.post("/email-verification/confirm")
@limiter.limit("10/minute")
async def confirm_email_verification(
    request: Request,
    req: EmailVerificationConfirmRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    if await is_email_verified(session, user_id=user.id, email=user.email):
        return {"verified": True}

    valid = await consume_otp(
        session,
        email=user.email,
        purpose=EMAIL_VERIFICATION_PURPOSE,
        code=req.code,
    )
    if not valid:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The verification code is invalid or expired.",
        )

    await mark_email_verified(
        session,
        user_id=user.id,
        email=user.email,
        source="otp",
    )
    await session.commit()
    return {"verified": True}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Start password recovery without exposing whether an email exists.

    Cognito is authoritative when enabled. Accounts that exist only in the
    local compatibility store use PostgreSQL + SendGrid fallback.
    """
    normalized_email = _normalize_email(req.email)
    generic_response = {
        "accepted": True,
        "message": (
            "If an eligible account exists, password-reset instructions "
            "will be sent to the registered email address."
        ),
    }

    if is_cognito_enabled():
        from app.core.cognito import forgot_password as cognito_forgot_password

        try:
            cognito_forgot_password(normalized_email)
            return generic_response
        except ValueError as exc:
            error_text = str(exc)
            if "UserNotFoundException" not in error_text:
                if "LimitExceededException" in error_text or "TooManyRequestsException" in error_text:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many password reset attempts. Please try again later.",
                    )
                logger.warning(
                    "Cognito forgot-password failed for %s: %s",
                    normalized_email,
                    error_text[:200],
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Password reset service is temporarily unavailable.",
                )

    # Local fallback. Unknown emails intentionally return the same response.
    user = await user_service.get_user_by_email(session, normalized_email)
    if not user:
        return generic_response

    code = f"{secrets.randbelow(1_000_000):06d}"
    await _store_local_password_reset(session, normalized_email, code)
    sent = await _send_local_password_reset_email(normalized_email, code)
    if not sent:
        logger.warning(
            "Local password-reset email could not be delivered for %s",
            normalized_email,
        )
    return generic_response


@router.post("/reset-password")
@limiter.limit("10/minute")
async def reset_password(
    request: Request,
    req: ResetPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Complete Cognito or local password recovery and keep local fallback
    credentials synchronized with the new password.
    """
    normalized_email = _normalize_email(req.email)
    cognito_reset = False

    if is_cognito_enabled():
        from app.core.cognito import confirm_forgot_password

        try:
            confirm_forgot_password(
                normalized_email,
                req.code.strip(),
                req.password,
            )
            cognito_reset = True
        except ValueError as exc:
            error_text = str(exc)
            if "UserNotFoundException" not in error_text:
                if "CodeMismatchException" in error_text:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="The password reset code is invalid.",
                    )
                if "ExpiredCodeException" in error_text:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="The password reset code has expired. Request a new code.",
                    )
                if "LimitExceededException" in error_text or "TooManyRequestsException" in error_text:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many password reset attempts. Please try again later.",
                    )
                logger.warning(
                    "Cognito reset-password failed for %s: %s",
                    normalized_email,
                    error_text[:200],
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Password reset service is temporarily unavailable.",
                )

    user = await user_service.get_user_by_email(session, normalized_email)

    if not cognito_reset:
        if not user or not await _consume_local_password_reset(session, normalized_email, req.code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The password reset code is invalid or expired.",
            )

    # Keep the local compatibility credential in sync.  AUTH-04 also revokes
    # every existing session and bumps the user token epoch so pre-AUTH-04
    # refresh/access credentials cannot resurrect a session after a password
    # reset.
    if user:
        user.password_hash = await user_service.hash_password_async(req.password)
        await revoke_all_auth_sessions(
            session,
            user.id,
            reason="password_reset",
        )
        await bump_user_token_epoch(session, user.id)
        await session.commit()
        user_cache.invalidate_user_keys(
            str(user.id),
            str(user.cognito_sub or ""),
        )

    return {"reset": True, "sessions_revoked": bool(user)}


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


@router.get("/sessions")
async def get_active_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    current_sid = _current_local_session_id(request)
    rows = await list_auth_sessions(session, user.id)
    return {
        "sessions": [
            {
                "session_id": str(row["id"]),
                "provider": row.get("provider"),
                "device_label": row.get("device_label"),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "last_seen_at": row["last_seen_at"].isoformat() if row.get("last_seen_at") else None,
                "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
                "current": str(row["id"]) == str(current_sid or ""),
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.delete("/sessions/{session_id}")
async def revoke_one_session(
    session_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    revoked = await revoke_auth_session(
        session,
        session_id,
        user.id,
        reason="user_remote_revoke",
    )
    await session.commit()
    return {"revoked": revoked, "session_id": session_id}


@router.post("/logout-all")
async def logout_all(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Revoke every server session and all older local token generations."""
    revoked_count = await revoke_all_auth_sessions(
        session,
        user.id,
        reason="logout_all",
    )
    await bump_user_token_epoch(session, user.id)

    provider_revoked = False
    if is_cognito_enabled() and getattr(user, "cognito_sub", None):
        from app.core.cognito import admin_global_sign_out
        try:
            admin_global_sign_out(str(user.cognito_sub or user.email))
            provider_revoked = True
        except Exception as exc:
            logger.warning(
                "Cognito logout-all failed for %s: %s",
                user.email,
                str(exc)[:200],
            )

    await session.commit()
    user_cache.invalidate_user_keys(str(user.id), str(user.cognito_sub or ""))
    return {
        "signed_out_all": True,
        "revoked_sessions": revoked_count,
        "provider_revoked": provider_revoked,
    }


@router.post("/logout")
async def logout(
    request: Request,
    req: LogoutRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Immediately revoke the current AUTH-04 session.

    Legacy clients may additionally provide their refresh token.  The mobile
    client clears local credentials even if provider sign-out is unavailable.
    """
    provider = "local"
    server_revoked = False
    current_sid = _current_local_session_id(request)

    if current_sid:
        server_revoked = await revoke_auth_session(
            session,
            current_sid,
            user.id,
            reason="logout",
        )

    if is_cognito_enabled() and getattr(user, "cognito_sub", None):
        from app.core.cognito import admin_global_sign_out

        provider = "cognito"
        try:
            admin_global_sign_out(str(user.cognito_sub or user.email))
            server_revoked = True
        except Exception as exc:
            logger.warning(
                "Cognito global sign-out failed for %s: %s",
                user.email,
                exc,
            )

    if req.refresh_token:
        local_claims = decode_refresh_token(req.refresh_token)
        if local_claims:
            try:
                refresh_user_id = uuid.UUID(str(local_claims["sub"]))
            except (KeyError, TypeError, ValueError):
                refresh_user_id = None

            if refresh_user_id == user.id:
                refresh_sid = str(local_claims.get("sid") or "").strip()
                if refresh_sid:
                    await revoke_auth_session(
                        session,
                        refresh_sid,
                        user.id,
                        reason="logout_refresh",
                    )
                # Keep the existing one-time credential guard for defence in
                # depth and for pre-AUTH-04 refresh tokens.
                await _claim_local_refresh_once(
                    session,
                    req.refresh_token,
                    local_claims,
                    user.id,
                )
                server_revoked = True

    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "Logout revocation commit failed for %s: %s",
            user.email,
            str(exc)[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server sign-out is temporarily unavailable.",
        )

    user_cache.invalidate_user_keys(str(user.id), str(user.cognito_sub or ""))
    return {
        "signed_out": True,
        "provider": provider,
        "server_revoked": server_revoked,
        "session_id": current_sid,
    }


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


# â”€â”€ Family Circle Invite Endpoints â”€â”€

@router.post("/family/generate-invite-code", response_model=GenerateInviteResponse)
async def generate_invite_code(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Guardian generates a 6-character invite code.
    Stores it in users.invite_code + users.invite_code_expires_at for the
    short server-controlled invite window. Calling again overwrites the
    previous code.
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


@router.post("/family/validate-invite-code")
@limiter.limit("20/minute")
async def validate_invite_code(
    request: Request,
    req: ValidateInviteRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Validate a QR/manual invite without consuming its single use."""
    from datetime import datetime, timezone
    from sqlalchemy import select

    normalized_code = req.invite_code.strip().upper()
    result = await session.execute(
        select(User).where(User.invite_code == normalized_code)
    )
    guardian = result.scalar_one_or_none()
    if not guardian:
        raise HTTPException(status_code=400, detail="Invalid invite code")

    now = datetime.now(timezone.utc)
    if not guardian.invite_code_expires_at or guardian.invite_code_expires_at < now:
        guardian.invite_code = None
        guardian.invite_code_expires_at = None
        await session.commit()
        raise HTTPException(status_code=400, detail="Invite code has expired")

    return {
        "valid": True,
        "expires_at": guardian.invite_code_expires_at.isoformat(),
    }


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

    # 1. Validate the code â€” look up guardian by invite_code
    normalized_invite_code = req.invite_code.strip().upper()
    # Lock the guardian row until commit. This makes the scanner truly
    # single-use even if two devices submit the same code at nearly once.
    result = await session.execute(
        select(User)
        .where(User.invite_code == normalized_invite_code)
        .with_for_update()
    )
    guardian = result.scalar_one_or_none()

    if not guardian:
        raise HTTPException(status_code=400, detail="Invalid invite code")

    # 2. Check expiry
    now = datetime.now(timezone.utc)
    if not guardian.invite_code_expires_at or guardian.invite_code_expires_at < now:
        guardian.invite_code = None
        guardian.invite_code_expires_at = None
        await session.commit()
        raise HTTPException(status_code=400, detail="Invite code has expired")

    # 3. Prevent duplicate email / phone and never create a family member
    # with a missing phone number.
    existing = await user_service.get_user_by_email(session, req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    normalized_phone = _require_normalized_phone(req.phone)
    if await _phone_exists(session, normalized_phone):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mobile number is already registered. Please sign in instead.",
        )

    # 4. Create the new family member account linked to the guardian
    new_user = User(
        email=req.email,
        password_hash=await user_service.hash_password_async(req.password),
        role=req.role,
        full_name=req.full_name,
        phone=normalized_phone,
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

    response = await _issue_local_session_response(
        session,
        new_user,
        request,
        provider="local",
    )
    await session.commit()
    return response


# â”€â”€ My Guardian â”€â”€

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
    Returns the guardian linked to the current user via users.guardian_id
    or guardian_relationships table.
    """
    from sqlalchemy import select, text
    import uuid

    guardian_id = getattr(user, "guardian_id", None)

    # 1. Direct DB lookup to bypass 30s user cache staleness
    if not guardian_id:
        try:
            r = await session.execute(text("SELECT guardian_id FROM users WHERE id = :uid"), {"uid": str(user.id)})
            row = r.first()
            if row and row.guardian_id:
                guardian_id = row.guardian_id
        except Exception as e:
            logger.warning(f"[MY_GUARDIAN] DB lookup error: {e}")

    # 2. Query guardian_relationships table (child -> guardian_user_id link)
    if not guardian_id:
        try:
            r = await session.execute(text("""
                SELECT guardian_user_id FROM guardian_relationships 
                WHERE user_id = :uid AND is_active = true 
                ORDER BY priority ASC LIMIT 1
            """), {"uid": str(user.id)})
            row = r.first()
            if row and row.guardian_user_id:
                guardian_id = row.guardian_user_id
        except Exception as e:
            logger.warning(f"[MY_GUARDIAN] Relationships lookup error: {e}")

    # 3. Clean 404 for Guardian accounts or unlinked members
    if not guardian_id:
        raise HTTPException(status_code=404, detail="No guardian linked to your account")

    result = await session.execute(select(User).where(User.id == uuid.UUID(str(guardian_id))))
    guardian = result.scalar_one_or_none()

    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian account not found")

    return GuardianInfoResponse(
        id=str(guardian.id),
        full_name=guardian.full_name,
        email=guardian.email,
        phone=guardian.phone,
    )




# â”€â”€ Local Auth Flows â”€â”€

async def _local_register(
    req: RegisterRequest,
    session: AsyncSession,
    request: Request,
) -> TokenResponse:
    existing = await user_service.get_user_by_email(session, req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    normalized_phone = _require_normalized_phone(req.phone)
    if await _phone_exists(session, normalized_phone):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mobile number is already registered. Please sign in instead.",
        )

    user = User(
        email=req.email,
        password_hash=await user_service.hash_password_async(req.password),
        role="guardian",
        phone=normalized_phone,
        full_name=req.full_name,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    response = await _issue_local_session_response(
        session,
        user,
        request,
        provider="local",
    )
    await session.commit()
    return response


async def _local_login(
    login_request: LoginRequest,
    session: AsyncSession,
    request: Request,
) -> TokenResponse:
    # Per-account login backoff (defense-in-depth on top of slowapi IP limiter).
    from app.core.login_backoff import check_lock, record_failure, reset

    normalized_email = str(login_request.email).strip().casefold()
    user = await user_service.get_user_by_email(session, normalized_email)
    password_valid = bool(
        user
        and await user_service.verify_password_async(
            login_request.password,
            user.password_hash,
        )
    )

    if not password_valid:
        lock = check_lock(normalized_email)
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
        record_failure(normalized_email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not bool(user.is_active):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive. Contact support if you believe this is an error.",
        )

    reset(normalized_email)

    response = await _issue_local_session_response(
        session,
        user,
        request,
        provider="local",
    )
    await session.commit()

    # Warm the user payload only after durable session creation succeeds.
    user_cache.cache_user(str(user.id), user)
    return response


# â”€â”€ Cognito Auth Flows â”€â”€

async def _cognito_register(
    req: RegisterRequest,
    session: AsyncSession,
    request: Request,
) -> TokenResponse:
    from app.core.cognito import sign_up, admin_confirm_user, sign_in

    existing = await user_service.get_user_by_email(session, req.email)
    if existing and existing.cognito_sub:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    normalized_phone = _require_normalized_phone(req.phone)
    if await _phone_exists(
        session,
        normalized_phone,
        exclude_user_id=existing.id if existing else None,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mobile number is already registered. Please sign in instead.",
        )

    try:
        result = sign_up(
            email=req.email,
            password=req.password,
            full_name=req.full_name or "",
            phone=normalized_phone,
        )
    except ValueError as exc:
        message = str(exc)
        if "UsernameExistsException" in message or "AliasExistsException" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email or mobile number is already registered. Please sign in instead.",
            )
        raise HTTPException(status_code=400, detail=message)

    cognito_sub = result["user_sub"]

    try:
        admin_confirm_user(req.email)
    except Exception as exc:
        logger.warning("Could not auto-confirm user %s: %s", req.email, exc)

    try:
        auth_result = sign_in(req.email, req.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Registration successful but login failed: {exc}",
        )

    if existing:
        existing.cognito_sub = cognito_sub
        if req.full_name and not existing.full_name:
            existing.full_name = req.full_name
        existing.phone = normalized_phone
        user = existing
    else:
        user = User(
            email=req.email,
            password_hash=await user_service.hash_password_async(req.password),
            cognito_sub=cognito_sub,
            role="guardian",
            phone=normalized_phone,
            full_name=req.full_name,
        )
        session.add(user)

    await session.commit()
    if not existing:
        await session.refresh(user)

    sid = await create_auth_session(
        session,
        user.id,
        provider="cognito",
        request=request,
    )
    local_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
        "sid": sid,
    })
    await session.commit()

    return TokenResponse(
        access_token=local_token,
        role=user.role,
        refresh_token=auth_result.get("refresh_token"),
        session_id=sid,
        cognito_id_token=auth_result.get("id_token"),
        cognito_username=auth_result.get("cognito_username"),
        auth_provider="cognito",
    )


async def _cognito_login(
    login_request: LoginRequest,
    session: AsyncSession,
    request: Request,
) -> TokenResponse:
    from app.core.cognito import sign_in

    try:
        auth_result = sign_in(login_request.email, login_request.password)
    except ValueError as exc:
        error_str = str(exc)
        if "UserNotConfirmedException" in error_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not confirmed. Please verify your email.",
            )
        if "PasswordResetRequiredException" in error_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password reset required. Please reset your password.",
            )
        logger.warning(
            "LOGIN_COGNITO_FALLBACK email=%s cognito_error='%s' -> local auth",
            login_request.email,
            error_str[:200],
        )
        return await _local_login(login_request, session, request)

    if "challenge" in auth_result:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Auth challenge required: {auth_result['challenge']}",
        )

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to provision user account",
        )

    if not bool(user.is_active):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive. Contact support if you believe this is an error.",
        )

    cognito_groups = claims.get("cognito:groups", []) if claims else []
    if cognito_groups:
        best_role = select_primary_role(cognito_groups)
        if best_role and user.role != best_role:
            user.role = best_role
            await session.flush()

    email_verified_claim = claims.get("email_verified") if claims else False
    email_verified = (
        email_verified_claim is True
        or str(email_verified_claim).strip().lower() in {"true", "1", "yes"}
    )
    if email_verified:
        await mark_email_verified(
            session,
            user_id=user.id,
            email=user.email,
            source="cognito",
        )

    sid = await create_auth_session(
        session,
        user.id,
        provider="cognito",
        request=request,
    )
    local_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
        "cognito:groups": sorted(normalize_roles(cognito_groups)),
        "sid": sid,
    })
    await session.commit()

    return TokenResponse(
        access_token=local_token,
        role=user.role,
        refresh_token=auth_result.get("refresh_token"),
        session_id=sid,
        cognito_id_token=auth_result.get("id_token"),
        cognito_username=auth_result.get("cognito_username"),
        auth_provider="cognito",
    )
