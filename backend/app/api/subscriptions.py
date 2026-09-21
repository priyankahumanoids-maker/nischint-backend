"""Day 6/7 subscription endpoints. Payment gateway intentionally deferred."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services import subscription_service

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class ActivateTestSubscriptionRequest(BaseModel):
    plan: str = Field(pattern="^(standard|premium)$")


@router.get("/summary")
async def get_subscription_summary(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    return await subscription_service.summary_for_guardian(session, user)


@router.post("/test-activate")
async def activate_test_subscription(
    req: ActivateTestSubscriptionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Temporary Day-6/7 activation only. No money is charged."""
    return await subscription_service.activate_test_subscription(session, user, req.plan)


@router.get("/member/{member_id}")
async def get_member_subscription(
    member_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    # Authorization stays aligned with the existing guardian family resolver.
    from app.services.member_monitoring_policy import require_policy_read_access
    target_id = await require_policy_read_access(session, user, member_id)
    data = await subscription_service.member_subscription(session, target_id)
    if data is None:
        return {
            "protected_member_user_id": target_id,
            "plan": None,
            "status": "missing",
            "price_monthly": None,
            "entitlements": {},
        }
    return data
