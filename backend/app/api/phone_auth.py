"""Existing-account phone login only. Session issuance stays in auth.py."""
import asyncio

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.auth_foundation_policy import OTP_TTL_SECONDS, OTP_RESEND_COOLDOWN_SECONDS
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.services import sms_service, user_cache, auth_two_factor_service
from app.services.auth_phone_otp_service import (
    PHONE_LOGIN, canonical_phone, issue_phone_code, verify_phone_code, users_for_phone,
)

router = APIRouter()


class PhoneLoginRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=24)


class PhoneLoginVerify(PhoneLoginRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
    installation_id: UUID | None = None


@router.post("/phone-login/request", status_code=202)
@limiter.limit("5/minute")
async def request_phone_login(
    request: Request, req: PhoneLoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    # Same operation and response for known and unknown numbers. No user query.
    phone = canonical_phone(req.phone)
    if not sms_service.is_available():
        raise HTTPException(503, "SMS verification is temporarily unavailable.")
    code = await issue_phone_code(session, request, phone=phone, purpose=PHONE_LOGIN)
    await session.commit()
    sent = await asyncio.to_thread(
        sms_service.send_sms, phone,
        f"NISCHINT sign-in code: {code}. It expires in 5 minutes. Do not share this code.",
    )
    if not sent:
        raise HTTPException(503, "SMS verification could not be delivered. Please try again later.")
    return {"accepted": True, "expires_in_seconds": OTP_TTL_SECONDS,
            "resend_cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS}


@router.post("/phone-login/verify")
@limiter.limit("10/minute")
async def verify_phone_login(
    request: Request, req: PhoneLoginVerify,
    session: AsyncSession = Depends(get_db_session),
):
    from app.api.auth import _issue_local_session_response

    phone = canonical_phone(req.phone)
    await verify_phone_code(session, request, phone=phone, purpose=PHONE_LOGIN, code=req.code)
    matches = await users_for_phone(session, phone)
    if len(matches) != 1 or not matches[0].is_active:
        await session.commit()
        raise HTTPException(401, "Unable to complete sign-in. Use registration or account recovery.")
    user = matches[0]
    state = await auth_two_factor_service.get_sms_two_factor_state(session, user_id=user.id, phone=user.phone)
    if state["configured"] and not state["phone_matches"]:
        await session.commit()
        raise HTTPException(401, "Unable to complete sign-in. Use account recovery.")
    # Verified possession satisfies the existing same-phone SMS compatibility
    # check. This does not assert an independent authenticator-app factor.
    response = await _issue_local_session_response(
        session, user, request, provider="local", extra_claims={"two_factor_verified": True},
    )
    if req.installation_id is not None and response.session_id:
        from app.services.auth_installation_service import associate_installation
        await associate_installation(
            session, user_id=user.id, session_id=UUID(str(response.session_id)),
            installation_id=req.installation_id, key=settings.jwt_secret.encode("utf-8"),
            now=datetime.now(timezone.utc),
        )
    await session.commit()
    user_cache.cache_user(str(user.id), user)
    return response
