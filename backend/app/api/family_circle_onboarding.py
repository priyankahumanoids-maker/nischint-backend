"""Family Circle Phase 4 onboarding and invite API."""
from __future__ import annotations

import asyncio
import uuid

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.core.family_consent_policy import (
    CURRENT_FAMILY_NOTICE_VERSION,
)
from app.models.family_circle import FamilyCircle, CircleMembership
from app.models.user import User
from app.services.family_circle_invite_service import (
    FamilyInviteError,
    create_invite,
    preview_invite,
    revoke_invite,
    seat_usage,
    list_pending_invites,
    revoke_pending_invite_by_id,
)
from app.services.family_circle_onboarding_service import (
    FamilyOnboardingError,
    create_creator_circle,
    onboarding_state,
)
from app.services.family_circle_service import get_active_membership

router = APIRouter(prefix="/family-circle", tags=["family-circle"])


class CreateCircleRequest(BaseModel):
    plan: Literal["trial", "individual", "family"] = "trial"
    seat: Literal["protected", "guardian", "member"] | None = None
    device_id: str | None = Field(default=None, min_length=8, max_length=512)
    circle_name: str | None = Field(default=None, max_length=120)
    legal_accepted: bool = False


class CreateInviteRequest(BaseModel):
    seat: Literal["protected", "guardian", "member"]
    invitee_kind: Literal["adult", "minor"] = "adult"
    parental_basis: Literal["parent", "lawful_guardian"] | None = None
    parental_verification_ref: str | None = Field(default=None, max_length=160)


class InviteCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class ConsentDecisionRequest(BaseModel):
    decisions: dict[str, bool]
    language: Literal["en", "hi"] = "en"
    device_id: str | None = Field(default=None, max_length=160)
    notice_version: str = CURRENT_FAMILY_NOTICE_VERSION


def _http_error(exc: Exception, *, default_status: int = 400) -> HTTPException:
    message = str(exc)
    lowered = message.lower()
    code = default_status
    if "only the owner or co-admin" in lowered:
        code = status.HTTP_403_FORBIDDEN
    elif "already belongs" in lowered or "seat type is full" in lowered:
        code = status.HTTP_409_CONFLICT
    elif "trial" in lowered and "already" in lowered:
        code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=message)


def _state_payload(state) -> dict:
    return {
        "has_circle": state.has_circle,
        "circle_id": str(state.circle_id) if state.circle_id else None,
        "circle_name": state.circle_name,
        "role": state.role,
        "plan": state.plan,
        "seat": state.seat,
        "tracked": state.tracked,
        "payment_required": state.payment_required,
        "trial_ends_at": state.trial_ends_at.isoformat() if state.trial_ends_at else None,
    }


@router.get("/plans/public")
async def public_family_circle_plans(session: AsyncSession = Depends(get_db_session)):
    from app.services.family_circle_plan_catalog_service import list_catalog_plans, public_plan_payload
    return {"plans": [public_plan_payload(plan) for plan in await list_catalog_plans(session)]}


@router.get("/onboarding/status")
async def get_onboarding_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return _state_payload(await onboarding_state(session, user.id))


@router.post("/onboarding/create", status_code=status.HTTP_201_CREATED)
async def create_circle_onboarding(
    req: CreateCircleRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        state = await create_creator_circle(
            session,
            user=user,
            plan=req.plan,
            seat=req.seat,
            device_id=req.device_id,
            circle_name=req.circle_name,
            legal_accepted=req.legal_accepted,
        )
        await session.commit()
        return _state_payload(state)
    except FamilyOnboardingError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_family_circle_invite(
    req: CreateInviteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        if str(req.invitee_kind or "adult").strip().lower() == "minor":
            # Counsel has not yet approved the verifiable-parental-consent
            # mechanism. A caller-supplied reference is not proof, and the
            # spec also requires fresh step-up OTP for adding a Minor. Keep
            # this public path fail-closed until both server-verified artifacts
            # exist.
            raise FamilyInviteError(
                "Adding a Minor is temporarily unavailable until verified parental consent and step-up verification are enabled."
            )
        code, expires_at, circle, seat, kind = await create_invite(
            session,
            actor=user,
            requested_seat=req.seat,
            invitee_kind=req.invitee_kind,
            parental_basis=req.parental_basis,
            parental_verification_ref=req.parental_verification_ref,
        )

        # Invite creation is the authoritative mutation. Commit it first so
        # optional seat-usage display work cannot cause the client to report
        # a false invite-creation failure.
        await session.commit()

        usage = None
        try:
            usage = await asyncio.wait_for(
                seat_usage(session, circle),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            # The invite has already been committed successfully.
            # Abort only the slow post-commit read transaction.
            await session.rollback()

        return {
            "code": code,
            "join_url": f"nischint://join?code={code}",
            "expires_at": expires_at.isoformat(),
            "expires_in_hours": 48,
            "seat": seat,
            "invitee_kind": kind,
            "single_use": True,
            "seat_usage": usage,
        }
    except FamilyInviteError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/invites/preview")
async def preview_family_circle_invite(
    req: InviteCodeRequest,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        preview = await preview_invite(session, req.code)
        await session.commit()
        return {
            "valid": True,
            "circle_name": preview.circle_name,
            "owner_name": preview.owner_name,
            "plan": preview.plan,
            "seat": preview.seat,
            "invitee_kind": preview.invitee_kind,
            "tracked": preview.tracked,
            "who_can_see": preview.who_can_see,
            "data_shared": list(preview.data_shared),
            "expires_at": preview.expires_at.isoformat(),
        }
    except FamilyInviteError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/members")
async def family_circle_visible_members(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Membership-only roster, not paid tracking/AI permission."""
    membership = await get_active_membership(session, user.id)
    if membership is None:
        raise HTTPException(status_code=404, detail="No active Family Circle membership")
    circle = await session.get(FamilyCircle, membership.circle_id)
    if circle is None or circle.plan != "family":
        raise HTTPException(status_code=403, detail="Family plan membership required")
    rows = (await session.execute(
        select(CircleMembership, User)
        .join(User, User.id == CircleMembership.user_id)
        .where(CircleMembership.circle_id == membership.circle_id, CircleMembership.status == "active")
    )).all()
    return {"members": [
        {"user_id": str(person.id), "name": person.full_name or "Member",
         "role": item.role, "seat": item.seat}
        for item, person in rows
    ]}


class InviteIdRequest(BaseModel):
    invite_id: str = Field(min_length=36, max_length=36)


@router.get("/invites/pending")
async def pending_family_invites(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        rows = await list_pending_invites(session, actor=user)
        await session.commit()
        return {"invites": rows}
    except FamilyInviteError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.post("/invites/revoke-by-id")
async def revoke_family_pending_invite_by_id(
    req: InviteIdRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        invite_id = uuid.UUID(req.invite_id)
        revoked = await revoke_pending_invite_by_id(session, actor=user, invite_id=invite_id)
        await session.commit()
        return {"revoked": revoked}
    except FamilyInviteError as exc:
        await session.rollback()
        raise _http_error(exc) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail="Invalid invitation ID") from exc


@router.post("/invites/revoke")
async def revoke_family_circle_invite(
    req: InviteCodeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        revoked = await revoke_invite(session, actor=user, code=req.code)
        await session.commit()
        return {"revoked": revoked}
    except FamilyInviteError as exc:
        await session.rollback()
        raise _http_error(exc) from exc


@router.get("/seat-usage")
async def get_family_circle_seat_usage(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    membership = await get_active_membership(session, user.id)
    if membership is None:
        raise HTTPException(status_code=404, detail="No active Family Circle membership")
    circle = await session.get(FamilyCircle, membership.circle_id)
    if circle is None or circle.plan is None:
        raise HTTPException(status_code=409, detail="Family Circle plan is not initialized")
    usage = await seat_usage(session, circle)
    await session.commit()
    return {"plan": circle.plan, "seat_usage": usage}


@router.post("/onboarding/consent")
async def record_onboarding_consent(
    req: ConsentDecisionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    state = await onboarding_state(session, user.id)
    if not state.has_circle or not state.tracked:
        raise HTTPException(status_code=403, detail="This Family Circle seat is not tracked.")
    try:
        from app.services.family_circle_consent_service import record_self_consent
        normalized = await record_self_consent(
            session,
            user=user,
            decisions=req.decisions,
            notice_version=req.notice_version,
            language=req.language,
            device_id=req.device_id,
        )
        await session.commit()
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        status_code = 409 if "notice" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"saved": True, "notice_version": req.notice_version, "decisions": normalized}
