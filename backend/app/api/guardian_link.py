# Guardian Link API — link a child using a 6-digit code
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.models.relationship import Relationship
from app.services import redis_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardian", tags=["guardian-link"])


class LinkChildRequest(BaseModel):
    code: str


@router.post("/link-child")
async def link_child(
    req: LinkChildRequest,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Guardian submits a 6-digit code to link a child to their account."""
    if user.role not in ("guardian", "parent", "caregiver", "admin"):
        raise HTTPException(status_code=403, detail="Only guardian accounts can link children")

    # Validate code from Redis
    child_id_str = redis_service.get_json("link_code", req.code)
    if not child_id_str:
        raise HTTPException(status_code=400, detail="Invalid or expired link code")

    child_id = uuid.UUID(child_id_str)

    # Verify child exists and has child role
    child_result = await session.execute(select(User).where(User.id == child_id))
    child = child_result.scalar_one_or_none()
    if not child:
        raise HTTPException(status_code=404, detail="Child account not found")
    if child.role not in ("child", "kid"):
        raise HTTPException(status_code=400, detail="Cannot link a non-child account")

    # Check duplicate
    existing = await session.execute(
        select(Relationship).where(
            Relationship.guardian_id == user.id,
            Relationship.child_id == child_id,
        )
    )
    if existing.scalar_one_or_none():
        # Delete code even on duplicate
        redis_service.delete_key("link_code", req.code)
        raise HTTPException(status_code=409, detail="This child is already linked to your account")

    # Create relationship
    rel = Relationship(guardian_id=user.id, child_id=child_id, status="accepted")
    session.add(rel)
    await session.flush()

    # Delete code from Redis
    redis_service.delete_key("link_code", req.code)

    # SSE: notify guardian that a child was linked (dashboard should refresh)
    try:
        from app.services.event_broadcaster import broadcaster
        await broadcaster.broadcast_to_user(
            str(user.id),
            "child_linked",
            {
                "child_id": str(child_id),
                "child_name": child.full_name or child.email,
                "relationship_id": str(rel.id),
            },
        )
        logger.info(f"[LINK-SSE] Broadcast child_linked to guardian {user.id}")
    except Exception as e:
        logger.warning(f"[LINK-SSE] Broadcast failed (non-blocking): {e}")

    logger.info(f"[LINK] Guardian {user.email} linked child {child.email} (rel={rel.id})")
    return {
        "message": "Child linked successfully",
        "child_name": child.full_name or child.email,
        "relationship_id": str(rel.id),
    }
