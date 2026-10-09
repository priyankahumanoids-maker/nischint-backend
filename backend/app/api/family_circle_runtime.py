"""Canonical runtime authority surface for the signed-in device."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services.family_circle_runtime_authority import runtime_snapshot, bounded_runtime_read

router = APIRouter(prefix="/family-circle/runtime", tags=["family-circle-runtime"])


@router.get("/me")
@bounded_runtime_read
async def get_my_runtime_authority(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    # Snapshot reconciliation may perform the automatic 18th-birthday role
    # transition and timed sharing resume. Persist those idempotent transitions
    # before returning the authority used by native runtime producers.
    snapshot = await runtime_snapshot(session, user.id)
    await session.commit()
    return snapshot
