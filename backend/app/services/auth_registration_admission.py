"""New-account admission only; existing-user authentication never calls this.

All new public provisioning holds the phone row through insert/commit. Existing
signup tickets, users, age policy and parental invitation authority are reused.
"""
import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.core.age_policy import ADULT_AGE_YEARS, calculate_age
from app.models.user import User
from app.services.auth_phone_security_service import locked_phone
from app.services.auth_phone_otp_service import (
    SIGNUP_PROOF, canonical_phone, require_unlocked, security_key,
    users_for_phone, verify_phone_code,
)


def require_adult(dob):
    if dob is None:
        raise HTTPException(422, "Date of birth is required")
    try:
        age = calculate_age(dob)
    except (ValueError, TypeError):
        raise HTTPException(422, "A valid date of birth is required") from None
    if age < ADULT_AGE_YEARS:
        raise HTTPException(403, "Ask a parent to add you to their circle.")


def require_registration_admission():
    raise HTTPException(403, "Complete phone verification and adult registration before signing in with this new identity")


async def consume_registration_proof(session, request, phone, *, email=None):
    """Also used by the existing parental invitation path (no adult override).

    The canonical invite service retains its own DOB/parental/minor checks.
    Duplicate identities are checked again under locks before ticket consumption.
    """
    phone = canonical_phone(phone)
    token = str(request.headers.get("X-Signup-Phone-Verification") or "").strip()
    if not 32 <= len(token) <= 160:
        raise HTTPException(403, "Mobile number verification is required before registration")
    async with locked_phone(session, phone=phone, key=security_key(), now=datetime.now(timezone.utc)) as guard:
        await require_unlocked(session, guard)
        if email:
            normalized = str(email).strip().casefold()
            # Transaction advisory lock serializes case-insensitive duplicate
            # email admission even if the historical DB unique key is case-sensitive.
            lock_id = int.from_bytes(hashlib.sha256(("admission-email:" + normalized).encode()).digest()[:8], "big", signed=True)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
            duplicate = await session.execute(select(User.id).where(func.lower(User.email) == normalized).limit(1))
            if duplicate.scalar_one_or_none() is not None:
                raise HTTPException(409, "An account already exists. Please sign in instead")
        if await users_for_phone(session, phone):
            raise HTTPException(409, "An account already exists. Please sign in instead")
        # The same transaction re-enters its phone row lock. Success does not
        # commit; the caller must persist the new user and consume proof together.
        await verify_phone_code(session, request, phone=phone, purpose=SIGNUP_PROOF, code=token)
    return phone


async def admit_independent_account(session, request, *, phone, email, date_of_birth):
    require_adult(date_of_birth)
    return await consume_registration_proof(session, request, phone, email=email)
