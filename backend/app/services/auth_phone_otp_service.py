"""7C-2 phone OTP boundary over AUTH-04 challenges and AUTH-05 phone locks.

No schema creation. Successful callers own their transaction. Failed attempts
are committed here BEFORE raising, so dependency rollback cannot erase a lock.
No SMS/network call is made while the phone row is locked.
"""
import math
import re
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, func, select

from app.core.auth_foundation_policy import (
    OTP_TTL_SECONDS, OTP_RESEND_COOLDOWN_SECONDS, normalize_phone,
)
from app.core.config import settings
from app.core.rate_limiter import enforce_otp_limit
from app.models.user import User
from app.services.auth_otp_service import consume_otp, store_otp
from app.services.auth_phone_security_service import locked_phone

PHONE_LOGIN = "phone_login"
SIGNUP_PHONE = "signup_phone"
SIGNUP_PROOF = "signup_phone_verified"
# SMS compatibility namespaces remain the existing service's values.


def security_key():
    key = settings.jwt_secret.encode("utf-8")
    if len(key) < 32:
        raise HTTPException(503, "Phone authentication security configuration unavailable")
    return key


def canonical_phone(value):
    raw = str(value or "").strip()
    # Preserve the established Indian national-number input convention, while
    # never truncating international numbers to their last ten digits.
    if not re.fullmatch(r"\+?[0-9 ()-]+", raw):
        raise HTTPException(422, "A valid mobile number is required")
    digits = re.sub(r"[^0-9]", "", raw)
    candidate = "+91" + digits if len(digits) == 10 and not raw.startswith("+") else "+" + digits
    try:
        return normalize_phone(candidate)
    except ValueError:
        raise HTTPException(422, "A valid mobile number is required") from None


def challenge_identity(phone, purpose):
    return f"signup-phone:{phone}" if purpose in {SIGNUP_PHONE, SIGNUP_PROOF} else f"phone:{phone}"


async def users_for_phone(session, phone):
    digits = func.regexp_replace(User.phone, r"\D", "", "g")
    # Legacy national numbers are Indian; explicit +international numbers must
    # not be reinterpreted as national numbers even when ten digits long.
    stored = case(
        ((func.length(digits) == 10) & (~User.phone.like("+%")), func.concat("91", digits)),
        else_=digits,
    )
    result = await session.execute(select(User).where(stored == phone[1:]).limit(2))
    return list(result.scalars().all())


async def require_unlocked(session, guard):
    guard.now = datetime.now(timezone.utc)  # after any row-lock wait
    if guard.locked:
        retry = max(1, math.ceil((guard.state.locked_until - guard.now).total_seconds()))
        await session.commit()
        raise HTTPException(429, "Phone verification temporarily locked", headers={"Retry-After": str(retry)})


async def issue_phone_code(session, request, *, phone, purpose, identity=None):
    phone = canonical_phone(phone)
    key = security_key()
    await enforce_otp_limit(request, identity="phone:" + phone, purpose=purpose, operation="issue", key=key)
    async with locked_phone(session, phone=phone, key=key, now=datetime.now(timezone.utc)) as guard:
        await require_unlocked(session, guard)
        code = f"{secrets.randbelow(1_000_000):06d}"
        retry = await store_otp(
            session, email=identity or challenge_identity(phone, purpose), purpose=purpose, code=code,
            ttl_seconds=OTP_TTL_SECONDS, cooldown_seconds=OTP_RESEND_COOLDOWN_SECONDS,
        )
        if retry:
            await session.commit()
            raise HTTPException(429, "Verification code requested recently", headers={"Retry-After": str(retry)})
        return code


async def verify_phone_code(session, request, *, phone, purpose, code, identity=None):
    phone = canonical_phone(phone)
    key = security_key()
    await enforce_otp_limit(request, identity="phone:" + phone, purpose=purpose, operation="verify", key=key)
    async with locked_phone(session, phone=phone, key=key, now=datetime.now(timezone.utc)) as guard:
        await require_unlocked(session, guard)
        valid = await consume_otp(
            session, email=identity or challenge_identity(phone, purpose), purpose=purpose, code=code,
            # Previously-issued ten-minute phone challenges cannot retain
            # their old validity after the five-minute policy is installed.
            max_age_seconds=None if purpose == SIGNUP_PROOF else OTP_TTL_SECONDS,
        )
        await guard.record(success=valid)
        if not valid:
            # Persist the fifth failure even when consume_otp deleted its
            # challenge. Raising first would let get_db_session roll it back.
            await session.commit()
            raise HTTPException(400, "The verification code is invalid or expired")
        return True


async def limit_account_otp(session, request, *, email, purpose, operation):
    """Shared quotas for existing email/provider recovery; no recovery rewrite.

    Always charge the email and IP equally, whether an account exists or not.
    Also charge the normalized phone when available. Durable phone lock policy
    applies to phone OTPs; email/provider challenge accounting remains existing.
    """
    normalized = str(email).strip().casefold()
    key = security_key()
    await enforce_otp_limit(request, identity="email:" + normalized, purpose=purpose, operation=operation, key=key)
    result = await session.execute(select(User.phone).where(func.lower(User.email) == normalized).limit(1))
    phone = result.scalar_one_or_none()
    if phone:
        try:
            phone = canonical_phone(phone)
        except HTTPException:
            return  # Existing accounts with incomplete historical data recover by email.
        await enforce_otp_limit(request, identity="phone:" + phone, purpose=purpose, operation=operation, key=key, include_peer=False)
