# Device Telemetry Router
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.device import Device
from app.models.senior import Senior
from app.schemas.telemetry import TelemetryResponse
from app.services import telemetry_service

router = APIRouter(prefix="/devices", tags=["devices"])


async def verify_device_ownership(
    session: AsyncSession,
    device_id: UUID,
    guardian_id: UUID,
) -> Device:
    """
    Verify that a device belongs to a senior under the guardian.
    Returns the device if valid, raises ValueError otherwise.
    """
    stmt = (
        select(Device)
        .join(Senior, Device.senior_id == Senior.id)
        .where(Device.id == device_id)
        .where(Senior.guardian_id == guardian_id)
    )
    result = await session.execute(stmt)
    device = result.scalar_one_or_none()
    
    if not device:
        return None
    
    return device


@router.get("/{device_id}/telemetry", response_model=List[TelemetryResponse])
async def get_device_telemetry(
    device_id: UUID,
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get telemetry history for a device.
    
    Device must belong to a senior under the authenticated guardian.
    Returns records ordered by created_at desc.
    """
    # Verify device belongs to guardian's senior
    device = await verify_device_ownership(session, device_id, current_user.id)
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device with id {device_id} not found or not owned by guardian",
        )
    
    telemetries = await telemetry_service.get_telemetry_by_device(
        session, device_id, limit
    )
    return telemetries
