"""Phase 7C-5 fresh-OTP step-up boundary.

This module verifies identity freshness only. It never grants Family authority;
protected lifecycle endpoints must still re-check current role/plan/seat/consent
at execution time (7C-6). Proofs are single-use, session/action/target-bound and
expire no later than five minutes after OTP verification.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.core.auth_foundation_policy import ActionBinding, OTP_TTL_SECONDS, STEP_UP_ACTIONS
from app.core.rate_limiter import limiter
from app.core.security import decode_local_token_claims
from app.models.user import User
from app.services import sms_service
from app.services.auth_phone_otp_service import canonical_phone, issue_phone_code, verify_phone_code
from app.services.auth_stepup_service import consume_bound_proof, issue_after_verified_otp

router = APIRouter()

# Phone change has its own dual-number / delayed-recovery flow. The generic
# current-phone step-up endpoint must never become a shortcut around it.
_GENERIC_ACTIONS = STEP_UP_ACTIONS - {"phone_change"}


class StepUpRequest(BaseModel):
    action: str = Field(min_length=3, max_length=64)
    circle_id: Optional[uuid.UUID] = None
    target_id: Optional[uuid.UUID] = None
    legacy_member_namespace: bool = False


class StepUpVerifyRequest(StepUpRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _session_id_from_request(request: Request) -> uuid.UUID:
    header = str(request.headers.get("authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authenticated session required")
    claims = decode_local_token_claims(header.split(" ", 1)[1].strip())
    sid = str((claims or {}).get("sid") or "").strip()
    try:
        return uuid.UUID(sid)
    except (TypeError, ValueError):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This sensitive action requires a current server session. Refresh or sign in again.",
        ) from None


def _binding_for(
    *,
    user_id,
    session_id,
    action: str,
    circle_id=None,
    target_id=None,
    legacy_member_namespace: bool = False,
) -> ActionBinding:
    action = str(action or "").strip()
    if action not in STEP_UP_ACTIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported step-up action")

    # Legacy GuardianRelationship removal is not a canonical CircleMembership.
    # AUTH-05 proof_circle_id has no FK; use the subject user UUID only as a
    # compatibility namespace so the proof cannot be replayed against a
    # canonical member-removal route. This does NOT assert Family membership.
    if action == "member_remove" and legacy_member_namespace:
        if circle_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Legacy removal cannot supply a circle id")
        circle_id = user_id

    try:
        return ActionBinding(
            user_id=user_id,
            session_id=session_id,
            action=action,
            circle_id=circle_id,
            target_id=target_id,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


def _challenge_identity(binding: ActionBinding) -> str:
    return (
        f"stepup-challenge:{binding.user_id}:{binding.session_id}:"
        f"{binding.action}:{binding.circle_id or '-'}:{binding.target_id or '-'}"
    )


def _challenge_purpose(action: str) -> str:
    return f"fresh_stepup:{action}"


async def consume_stepup_for_action(
    request: Request,
    *,
    session: AsyncSession,
    user: User,
    action: str,
    circle_id=None,
    target_id=None,
    legacy_member_namespace: bool = False,
) -> bool:
    """Consume X-Nischint-Step-Up atomically inside the caller transaction."""
    token = str(request.headers.get("x-nischint-step-up") or "").strip()
    if not token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Fresh verification is required for this action")
    binding = _binding_for(
        user_id=user.id,
        session_id=_session_id_from_request(request),
        action=action,
        circle_id=circle_id,
        target_id=target_id,
        legacy_member_namespace=legacy_member_namespace,
    )
    ok = await consume_bound_proof(
        session,
        token=token,
        binding=binding,
        now=datetime.now(timezone.utc),
    )
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Fresh verification proof is invalid, expired, or already used")
    return True


@router.post("/step-up/request", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def request_step_up(
    request: Request,
    body: StepUpRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    if body.action == "phone_change":
        raise HTTPException(status.HTTP_409_CONFLICT, "Use the verified phone-change workflow for this action")
    if body.action not in _GENERIC_ACTIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported step-up action")

    sid = _session_id_from_request(request)
    binding = _binding_for(
        user_id=user.id,
        session_id=sid,
        action=body.action,
        circle_id=body.circle_id,
        target_id=body.target_id,
        legacy_member_namespace=body.legacy_member_namespace,
    )
    phone = canonical_phone(user.phone)
    if not sms_service.is_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SMS verification is temporarily unavailable")

    code = await issue_phone_code(
        session,
        request,
        phone=phone,
        purpose=_challenge_purpose(binding.action),
        identity=_challenge_identity(binding),
    )
    await session.commit()
    sent = await asyncio.to_thread(
        sms_service.send_sms,
        phone,
        f"NISCHINT verification code: {code}. It expires in 5 minutes. Do not share this code.",
    )
    if not sent:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SMS verification could not be delivered")
    return {"accepted": True, "expires_in_seconds": OTP_TTL_SECONDS}


@router.post("/step-up/verify")
@limiter.limit("10/minute")
async def verify_step_up(
    request: Request,
    body: StepUpVerifyRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    if body.action == "phone_change":
        raise HTTPException(status.HTTP_409_CONFLICT, "Use the verified phone-change workflow for this action")
    if body.action not in _GENERIC_ACTIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported step-up action")

    sid = _session_id_from_request(request)
    binding = _binding_for(
        user_id=user.id,
        session_id=sid,
        action=body.action,
        circle_id=body.circle_id,
        target_id=body.target_id,
        legacy_member_namespace=body.legacy_member_namespace,
    )
    phone = canonical_phone(user.phone)
    await verify_phone_code(
        session,
        request,
        phone=phone,
        purpose=_challenge_purpose(binding.action),
        code=body.code,
        identity=_challenge_identity(binding),
    )
    verified_at = datetime.now(timezone.utc)
    token = await issue_after_verified_otp(
        session,
        binding=binding,
        verified_at=verified_at,
        now=verified_at,
    )
    await session.commit()
    return {
        "proof_token": token,
        "action": binding.action,
        "expires_in_seconds": OTP_TTL_SECONDS,
    }
