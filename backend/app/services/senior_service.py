# Senior Service
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.senior import Senior
from app.schemas.senior import SeniorCreate


async def create_senior(
    session: AsyncSession,
    guardian_id: UUID,
    senior_create: SeniorCreate,
) -> Senior:
    """Create a new senior under a guardian."""
    senior = Senior(
        guardian_id=guardian_id,
        full_name=senior_create.full_name,
        age=senior_create.age,
        medical_notes=senior_create.medical_notes,
    )

    session.add(senior)
    await session.commit()
    await session.refresh(senior)

    return senior


async def get_seniors_by_guardian(
    session: AsyncSession,
    guardian_id: UUID,
) -> Sequence[Senior]:
    """Get all seniors for a given guardian."""
    stmt = select(Senior).where(Senior.guardian_id == guardian_id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_senior_by_id(
    session: AsyncSession,
    senior_id: UUID,
) -> Senior | None:
    """Get a senior by ID."""
    stmt = select(Senior).where(Senior.id == senior_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
