"""DPDP-01: Erasure-rights HTTP API.

User-facing endpoints (gated by JWT):
  - DELETE /api/privacy/me                          → submit erasure
  - GET    /api/privacy/erasure-requests/me         → list own requests
  - POST   /api/privacy/erasure-requests/{id}/cancel → cancel during grace

Admin-only endpoints (gated by role=admin):
  - GET    /api/admin/erasure-requests              → list all
  - POST   /api/admin/erasure-requests/{id}/approve → instant hard-delete
  - POST   /api/admin/erasure-requests/{id}/cancel  → admin cancel

The user endpoints use `get_current_user` (NOT `get_current_user_active`)
because a frozen user must still be able to cancel their request. The
admin endpoints use `require_role("admin")`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, require_role
from app.models.erasure_request import (
    ErasureRequest,
    STATUS_PENDING,
)
from app.models.user import User
from app.services import erasure_service

logger = logging.getLogger(__name__)

# ── Schemas ──────────────────────────────────────────────────────────


class ErasureSubmitBody(BaseModel):
    """Optional body when submitting an erasure request."""

    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional user-provided reason for erasure (audit trail)",
    )


class ErasureRequestOut(BaseModel):
    """Sanitised view of an erasure_requests row safe to return to the user."""

    id: uuid.UUID
    user_id: uuid.UUID | None
    user_email: str
    status: str
    requested_at: datetime
    grace_expires_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_source: str | None = None
    completion_source: str | None = None
    request_reason: str | None = None

    @classmethod
    def from_orm_row(cls, row: ErasureRequest) -> "ErasureRequestOut":
        return cls(
            id=row.id,
            user_id=row.user_id,
            user_email=row.user_email,
            status=row.status,
            requested_at=row.requested_at,
            grace_expires_at=row.grace_expires_at,
            completed_at=row.completed_at,
            cancelled_at=row.cancelled_at,
            cancellation_source=row.cancellation_source,
            completion_source=row.completion_source,
            request_reason=row.request_reason,
        )


class ErasureSubmitResponse(BaseModel):
    """202 Accepted body."""

    erasure_request_id: uuid.UUID
    grace_expires_at: datetime
    cancel_url: str
    message: str


# ── Routers ──────────────────────────────────────────────────────────

# User-facing — mounted under /api/privacy by api/main.py.
router = APIRouter(prefix="/privacy", tags=["privacy", "dpdp"])

# Admin-facing — mounted under /api/admin by api/main.py.
admin_router = APIRouter(
    prefix="/admin/erasure-requests",
    tags=["admin", "privacy", "dpdp"],
)


# ── User endpoints ───────────────────────────────────────────────────


@router.delete(
    "/me",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ErasureSubmitResponse,
)
async def submit_self_erasure(
    request: Request,
    body: ErasureSubmitBody | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Submit a DPDP §17 erasure request for the authenticated user.

    Returns **202 Accepted** with the request id and grace deadline.
    The account is immediately marked frozen — subsequent write
    requests will be refused until the user cancels.
    """
    # Anti-double-submit: if the user already has a pending request,
    # return the existing one (idempotent from the client's perspective).
    existing = await session.execute(
        select(ErasureRequest)
        .where(ErasureRequest.user_id == user.id)
        .where(ErasureRequest.status == STATUS_PENDING)
    )
    pending = existing.scalar_one_or_none()
    if pending is not None:
        return ErasureSubmitResponse(
            erasure_request_id=pending.id,
            grace_expires_at=pending.grace_expires_at,
            cancel_url=f"/api/privacy/erasure-requests/{pending.id}/cancel",
            message=(
                "An erasure request is already pending. "
                "Cancel it before submitting a new one."
            ),
        )

    try:
        req = await erasure_service.submit_request(
            session,
            user,
            request_ip=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:1000],
            reason=(body.reason if body else None),
        )
    except erasure_service.ErasureAlreadyPending as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return ErasureSubmitResponse(
        erasure_request_id=req.id,
        grace_expires_at=req.grace_expires_at,
        cancel_url=f"/api/privacy/erasure-requests/{req.id}/cancel",
        message=(
            f"Erasure request accepted. Your data will be permanently "
            f"deleted on {req.grace_expires_at.date().isoformat()} unless "
            f"you cancel before then."
        ),
    )


@router.get("/erasure-requests/me", response_model=list[ErasureRequestOut])
async def list_my_erasure_requests(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List the authenticated user's erasure requests (all statuses)."""
    q = await session.execute(
        select(ErasureRequest)
        .where(ErasureRequest.user_id == user.id)
        .order_by(ErasureRequest.requested_at.desc())
    )
    return [ErasureRequestOut.from_orm_row(r) for r in q.scalars().all()]


@router.post(
    "/erasure-requests/{request_id}/cancel",
    response_model=ErasureRequestOut,
)
async def cancel_my_erasure_request(
    request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Cancel the user's own pending erasure request during the grace
    window. Un-freezes the account."""
    try:
        req = await erasure_service.cancel_request(
            session,
            request_id=request_id,
            actor_user=user,
            actor_source=erasure_service.CANCELLATION_USER,
        )
    except erasure_service.ErasureNotFound:
        raise HTTPException(status_code=404, detail="erasure request not found")
    except erasure_service.ErasureNotCancellable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ErasureRequestOut.from_orm_row(req)


# ── Admin endpoints ──────────────────────────────────────────────────


@admin_router.get("", response_model=list[ErasureRequestOut])
async def admin_list_erasure_requests(
    status_filter: str | None = None,
    admin: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
):
    """List all erasure requests across all users. Optional `?status_filter=pending`."""
    q = select(ErasureRequest).order_by(ErasureRequest.requested_at.desc())
    if status_filter:
        q = q.where(ErasureRequest.status == status_filter)
    rows = await session.execute(q)
    return [ErasureRequestOut.from_orm_row(r) for r in rows.scalars().all()]


@admin_router.post(
    "/{request_id}/approve",
    response_model=ErasureRequestOut,
)
async def admin_approve_erasure(
    request_id: uuid.UUID,
    admin: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin override — execute the erasure immediately, skipping the
    30-day grace window. Used when a user has confirmed via email /
    phone and wants their data gone now."""
    try:
        req = await erasure_service.execute_hard_delete(
            session,
            request_id=request_id,
            completion_source=erasure_service.COMPLETION_ADMIN_APPROVE,
            actor_id=admin.id,
        )
    except erasure_service.ErasureNotFound:
        raise HTTPException(status_code=404, detail="erasure request not found")
    return ErasureRequestOut.from_orm_row(req)


@admin_router.post(
    "/{request_id}/cancel",
    response_model=ErasureRequestOut,
)
async def admin_cancel_erasure(
    request_id: uuid.UUID,
    admin: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin cancel — useful for fraud/abuse mitigation (someone
    maliciously submitted an erasure request on the user's behalf)."""
    try:
        req = await erasure_service.cancel_request(
            session,
            request_id=request_id,
            actor_user=admin,
            actor_source=erasure_service.CANCELLATION_ADMIN,
        )
    except erasure_service.ErasureNotFound:
        raise HTTPException(status_code=404, detail="erasure request not found")
    except erasure_service.ErasureNotCancellable as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ErasureRequestOut.from_orm_row(req)


# ── Helpers ──────────────────────────────────────────────────────────


def _client_ip(request: Request) -> str | None:
    """Extract the client IP, preferring X-Forwarded-For (Cloudflare/nginx)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    if request.client and request.client.host:
        return request.client.host[:45]
    return None
