# Device Service
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.schemas.device import DeviceCreate


async def register_device(
    session: AsyncSession,
    senior_id: UUID,
    device_create: DeviceCreate,
) -> Device:
    """
    Register a new device for a senior.
    Raises ValueError if device_identifier already exists.
    """
    device = Device(
        senior_id=senior_id,
        device_identifier=device_create.device_identifier,
        device_type=device_create.device_type,
    )

    session.add(device)
    try:
        await session.commit()
        await session.refresh(device)
    except IntegrityError:
        await session.rollback()
        raise ValueError(
            f"Device with identifier {device_create.device_identifier} already exists"
        )

    return device


async def get_devices_by_senior(
    session: AsyncSession,
    senior_id: UUID,
) -> Sequence[Device]:
    """Get all devices for a given senior."""
    stmt = select(Device).where(Device.senior_id == senior_id)
    result = await session.execute(stmt)
    return result.scalars().all()
