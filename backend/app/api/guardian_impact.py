"""NISCH-009.1 — Guardian Impact API.

`GET /api/guardian/impact/me`         — caller's own count.
`GET /api/guardian/impact/{user_id}`  — admin/operator only.

Surface decisions (per spec — "earned, not gamified spam"):
  * Self endpoint requires no role gate (guardian/admin/operator/user
    all eligible — anyone CAN have voted on an incident, even
    auto-self-link cases).
  * Cross-user endpoint requires admin/operator.
  * `confidence_low: true` is returned but the UI is responsible for
    hiding the badge — the API never lies about the count.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services.guardian_impact_service import get_impact

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian/impact", tags=["Guardian Feedback"])


@router.get("/me")
async def get_my_impact(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Caller's own impact stats — eligible for the badge surface."""
    return await get_impact(session, user.id)


@router.get("/{user_id}")
async def get_user_impact(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Cross-user impact — admin/operator only."""
    role = (user.role or "").lower()
    if role not in ("admin", "operator") and user.id != user_id:
        raise HTTPException(403, "not authorized")
    return await get_impact(session, user_id)


__all__ = ["router"]
