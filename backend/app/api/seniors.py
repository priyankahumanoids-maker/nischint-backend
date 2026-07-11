# Seniors Router
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.schemas.senior import SeniorCreate, SeniorResponse
from app.services import senior_service, user_service

router = APIRouter(prefix="/users/{guardian_id}/seniors", tags=["seniors"])


@router.post("", response_model=SeniorResponse, status_code=status.HTTP_201_CREATED)
async def create_senior(
    guardian_id: UUID,
    senior_create: SeniorCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new senior under a guardian. Requires authentication."""
    # Verify guardian exists
    guardian = await user_service.get_user_by_id(session, guardian_id)
    if not guardian:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardian with id {guardian_id} not found",
        )

    senior = await senior_service.create_senior(session, guardian_id, senior_create)
    return senior


@router.get("", response_model=List[SeniorResponse])
async def get_seniors(
    guardian_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all seniors for a guardian. Requires authentication."""
    # Verify guardian exists
    guardian = await user_service.get_user_by_id(session, guardian_id)
    if not guardian:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardian with id {guardian_id} not found",
        )

    seniors = await senior_service.get_seniors_by_guardian(session, guardian_id)
    return seniors
