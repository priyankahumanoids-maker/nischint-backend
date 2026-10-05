"""Phase 7C-5 verified phone-number change and delayed recovery API."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.stepup_auth import _binding_for, _session_id_from_request
from app.core.auth_foundation_policy import OTP_TTL_SECONDS
from app.core.rate_limiter import limiter
from app.models.user import User
from app.services import auth_two_factor_service, sms_service, user_cache
from app.services.auth_phone_change_service import (
    cancel_phone_change,
    create_phone_change,
    get_phone_change,
    mark_completed,
    mark_phone_verified,
    operation_ready,
    pending_phone_change_exists,
    phone_matches_operation,
    queue_recovery_owner_notice,
    recovery_is_eligible,
)
from app.services.auth_phone_otp_service import (
    canonical_phone,
    issue_phone_code,
    security_key,
    users_for_phone,
    verify_phone_code,
)
from app.services.auth_session_service import (
    bump_user_token_epoch,
    lock_user_auth_boundary,
    revoke_all_auth_sessions,
)
from app.services.auth_stepup_service import consume_bound_proof, issue_after_verified_otp

router = APIRouter()

OLD_PURPOSE = "phone_change_old"
NEW_PURPOSE = "phone_change_new"


class PhoneChangeStart(BaseModel):
    new_phone: str = Field(min_length=8, max_length=24)
    recovery: bool = False


class PhoneChangeOperation(BaseModel):
    operation_id: uuid.UUID


class PhoneChangeVerifyOld(PhoneChangeOperation):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class PhoneChangeNew(PhoneChangeOperation):
    new_phone: str = Field(min_length=8, max_length=24)


class PhoneChangeVerifyNew(PhoneChangeNew):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class PhoneChangeComplete(PhoneChangeNew):
    proof_token: str = Field(min_length=20, max_length=160)


def _otp_identity(operation_id: uuid.UUID, side: str, phone: str) -> str:
    return f"phone-change:{operation_id}:{side}:{phone}"


async def _ensure_phone_available(session: AsyncSession, phone: str, user_id) -> None:
    matches = await users_for_phone(session, phone)
    if any(str(candidate.id) != str(user_id) for candidate in matches):
        raise HTTPException(status.HTTP_409_CONFLICT, "This mobile number is already registered")


async def _send_code(session, request, *, phone: str, purpose: str, identity: str, label: str) -> None:
    if not sms_service.is_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SMS verification is temporarily unavailable")
    code = await issue_phone_code(
        session,
        request,
        phone=phone,
        purpose=purpose,
        identity=identity,
    )
    await session.commit()
    sent = await asyncio.to_thread(
        sms_service.send_sms,
        phone,
        f"NISCHINT verification code: {code}. Use it to {label}. It expires in 5 minutes. Do not share this code.",
    )
    if not sent:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SMS verification could not be delivered")


def _require_pending(row):
    if not row or row["status"] != "pending":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pending phone-change operation not found")
    return row


@router.post("/phone-change/start", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def start_phone_change(
    request: Request,
    body: PhoneChangeStart,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _session_id_from_request(request)  # require current durable session now, not only at completion
    if not await lock_user_auth_boundary(session, user.id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is no longer available")
    old_phone = canonical_phone(user.phone)
    new_phone = canonical_phone(body.new_phone)
    if old_phone == new_phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New mobile number must be different")
    await _ensure_phone_available(session, new_phone, user.id)
    if await pending_phone_change_exists(session, user_id=user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A phone change is already pending")

    now = datetime.now(timezone.utc)
    try:
        op_id = await create_phone_change(
            session,
            user_id=user.id,
            old_phone=old_phone,
            new_phone=new_phone,
            key=security_key(),
            recovery=body.recovery,
            now=now,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None

    notice_state = "not_required"
    if body.recovery:
        notice_state = await queue_recovery_owner_notice(
            session,
            operation_id=op_id,
            user_id=user.id,
            now=now,
        )
        await session.commit()
        row = _require_pending(await get_phone_change(session, operation_id=op_id, user_id=user.id))
        return {
            "operation_id": str(op_id),
            "recovery": True,
            "eligible_after": row["eligible_after"].isoformat(),
            "owner_notice_state": notice_state,
            "next": "request_new_after_eligible",
        }

    # Normal path starts by proving possession of the currently registered number.
    await _send_code(
        session,
        request,
        phone=old_phone,
        purpose=OLD_PURPOSE,
        identity=_otp_identity(op_id, "old", old_phone),
        label="confirm your current mobile number",
    )
    return {
        "operation_id": str(op_id),
        "recovery": False,
        "expires_in_seconds": OTP_TTL_SECONDS,
        "next": "verify_old",
    }


@router.post("/phone-change/cancel")
async def cancel_pending_phone_change(
    request: Request,
    body: PhoneChangeOperation,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _session_id_from_request(request)
    now = datetime.now(timezone.utc)
    if not await cancel_phone_change(
        session, operation_id=body.operation_id, user_id=user.id, now=now
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pending phone-change operation not found")
    await session.commit()
    return {"cancelled": True, "operation_id": str(body.operation_id)}


@router.post("/phone-change/request-old", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def request_old_phone_code(
    request: Request,
    body: PhoneChangeOperation,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _session_id_from_request(request)
    row = _require_pending(await get_phone_change(session, operation_id=body.operation_id, user_id=user.id))
    if row["recovery"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Old-number verification is unavailable in recovery mode")
    old_phone = canonical_phone(user.phone)
    if not phone_matches_operation(operation=row, phone=old_phone, key=security_key(), which="old"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Registered mobile identity changed; restart phone change")
    await _send_code(
        session, request, phone=old_phone, purpose=OLD_PURPOSE,
        identity=_otp_identity(body.operation_id, "old", old_phone),
        label="confirm your current mobile number",
    )
    return {"accepted": True, "expires_in_seconds": OTP_TTL_SECONDS}


@router.post("/phone-change/verify-old")
@limiter.limit("10/minute")
async def verify_old_phone(
    request: Request,
    body: PhoneChangeVerifyOld,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _session_id_from_request(request)
    row = _require_pending(await get_phone_change(session, operation_id=body.operation_id, user_id=user.id))
    if row["recovery"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Old-number verification is unavailable in recovery mode")
    old_phone = canonical_phone(user.phone)
    if not phone_matches_operation(operation=row, phone=old_phone, key=security_key(), which="old"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Registered mobile identity changed; restart phone change")
    await verify_phone_code(
        session, request, phone=old_phone, purpose=OLD_PURPOSE, code=body.code,
        identity=_otp_identity(body.operation_id, "old", old_phone),
    )
    verified_at = datetime.now(timezone.utc)
    if not await mark_phone_verified(
        session, operation_id=body.operation_id, user_id=user.id, which="old", verified_at=verified_at
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Phone-change operation is no longer pending")
    await session.commit()
    return {"verified": True, "next": "request_new"}


@router.post("/phone-change/request-new", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def request_new_phone_code(
    request: Request,
    body: PhoneChangeNew,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    _session_id_from_request(request)
    row = _require_pending(await get_phone_change(session, operation_id=body.operation_id, user_id=user.id))
    new_phone = canonical_phone(body.new_phone)
    if not phone_matches_operation(operation=row, phone=new_phone, key=security_key(), which="new"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New mobile number does not match this operation")
    await _ensure_phone_available(session, new_phone, user.id)

    if row["recovery"]:
        if not await recovery_is_eligible(
            session, operation_id=body.operation_id, user_id=user.id, now=datetime.now(timezone.utc)
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "Phone recovery is not yet eligible")
    elif row["old_verified_at"] is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verify the current mobile number first")

    await _send_code(
        session, request, phone=new_phone, purpose=NEW_PURPOSE,
        identity=_otp_identity(body.operation_id, "new", new_phone),
        label="confirm your new mobile number",
    )
    return {"accepted": True, "expires_in_seconds": OTP_TTL_SECONDS}


@router.post("/phone-change/verify-new")
@limiter.limit("10/minute")
async def verify_new_phone(
    request: Request,
    body: PhoneChangeVerifyNew,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    sid = _session_id_from_request(request)
    row = _require_pending(await get_phone_change(session, operation_id=body.operation_id, user_id=user.id))
    new_phone = canonical_phone(body.new_phone)
    if not phone_matches_operation(operation=row, phone=new_phone, key=security_key(), which="new"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New mobile number does not match this operation")
    await _ensure_phone_available(session, new_phone, user.id)

    now = datetime.now(timezone.utc)
    if row["recovery"]:
        if not await recovery_is_eligible(session, operation_id=body.operation_id, user_id=user.id, now=now):
            raise HTTPException(status.HTTP_409_CONFLICT, "Phone recovery is not yet eligible")
    elif row["old_verified_at"] is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verify the current mobile number first")

    await verify_phone_code(
        session, request, phone=new_phone, purpose=NEW_PURPOSE, code=body.code,
        identity=_otp_identity(body.operation_id, "new", new_phone),
    )
    verified_at = datetime.now(timezone.utc)
    if not await mark_phone_verified(
        session, operation_id=body.operation_id, user_id=user.id, which="new", verified_at=verified_at
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Phone-change operation is no longer pending")

    binding = _binding_for(
        user_id=user.id,
        session_id=sid,
        action="phone_change",
        target_id=body.operation_id,
    )
    proof = await issue_after_verified_otp(
        session, binding=binding, verified_at=verified_at, now=verified_at
    )
    await session.commit()
    return {
        "verified": True,
        "proof_token": proof,
        "expires_in_seconds": OTP_TTL_SECONDS,
        "next": "complete",
    }


@router.post("/phone-change/complete")
@limiter.limit("10/minute")
async def complete_phone_change(
    request: Request,
    body: PhoneChangeComplete,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    sid = _session_id_from_request(request)
    now = datetime.now(timezone.utc)

    # Serialize against refresh/logout/password reset and all other phone-change
    # completion for this account on the existing users row.
    if not await lock_user_auth_boundary(session, user.id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is no longer available")

    row = _require_pending(await get_phone_change(
        session, operation_id=body.operation_id, user_id=user.id, for_update=True
    ))
    new_phone = canonical_phone(body.new_phone)
    key = security_key()
    if not phone_matches_operation(operation=row, phone=new_phone, key=key, which="new"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New mobile number does not match this operation")
    if not operation_ready(row, now=now):
        raise HTTPException(status.HTTP_409_CONFLICT, "Phone-change verification is incomplete or recovery is not yet eligible")

    # Cross-user same-number completions serialize on a keyed digest advisory lock.
    digest = row["new_phone_digest"]
    advisory = int(str(digest)[:16], 16)
    if advisory >= 2**63:
        advisory -= 2**64
    await session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": advisory})
    await _ensure_phone_available(session, new_phone, user.id)

    binding = _binding_for(
        user_id=user.id,
        session_id=sid,
        action="phone_change",
        target_id=body.operation_id,
    )
    if not await consume_bound_proof(session, token=body.proof_token, binding=binding, now=now):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Fresh phone-change proof is invalid, expired, or already used")

    db_user = (await session.execute(select(User).where(User.id == user.id).with_for_update())).scalar_one_or_none()
    if not db_user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User account not found")
    db_user.phone = new_phone

    # Preserve optional SMS 2FA instead of forcing users to disable security
    # before a verified dual-number change.
    new_hash = auth_two_factor_service.phone_hash(new_phone)
    await session.execute(text("""
        UPDATE auth_two_factor_settings
        SET phone_hash=:phone_hash, updated_at=:now
        WHERE user_id=:uid AND sms_enabled=TRUE
    """), {"phone_hash": new_hash, "now": now, "uid": user.id})

    if not await mark_completed(session, operation_id=body.operation_id, user_id=user.id, now=now):
        raise HTTPException(status.HTTP_409_CONFLICT, "Phone-change operation is no longer pending")

    # Identity change invalidates every pre-change session/credential. The user
    # ID, Circle membership, history, subscriptions and safety data are preserved.
    revoked = await revoke_all_auth_sessions(session, user.id, reason="phone_change")
    await bump_user_token_epoch(session, user.id)
    await session.execute(text("""
        UPDATE auth_sos_credentials
        SET revoked_at=COALESCE(revoked_at,:now)
        WHERE user_id=:uid AND revoked_at IS NULL
    """), {"now": now, "uid": user.id})
    await session.execute(text("DELETE FROM push_tokens WHERE user_id=:uid"), {"uid": user.id})

    await session.commit()
    user_cache.invalidate_user_keys(str(user.id), str(getattr(user, "cognito_sub", "") or ""))
    return {
        "updated": True,
        "phone": new_phone,
        "sessions_revoked": revoked,
        "reauthentication_required": True,
    }
