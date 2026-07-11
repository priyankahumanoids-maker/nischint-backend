# Devices Router
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.schemas.device import DeviceCreate, DeviceResponse
from app.services import device_service, senior_service

router = APIRouter(prefix="/seniors/{senior_id}/devices", tags=["devices"])


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    senior_id: UUID,
    device_create: DeviceCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Register a new device for a senior. Requires authentication."""
    # Verify senior exists
    senior = await senior_service.get_senior_by_id(session, senior_id)
    if not senior:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Senior with id {senior_id} not found",
        )

    try:
        device = await device_service.register_device(session, senior_id, device_create)
        return device
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[DeviceResponse])
async def get_devices(
    senior_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all devices for a senior. Requires authentication."""
    # Verify senior exists
    senior = await senior_service.get_senior_by_id(session, senior_id)
    if not senior:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Senior with id {senior_id} not found",
        )

    devices = await device_service.get_devices_by_senior(session, senior_id)
    return devices
