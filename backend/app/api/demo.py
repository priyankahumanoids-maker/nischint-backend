# Demo Mode API — Start/stop/status for investor demos
from fastapi import APIRouter, Depends
from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/demo", tags=["Demo Mode"])

# Demo mode is an operational tool (training, onboarding, pitching).
# Both admins and operators legitimately run demo sessions.
_demo_role = require_role(["admin", "operator"])


@router.post("/start")
async def start_demo_mode(
    user: User = Depends(_demo_role),
):
    """Start demo scenario — simulates a 30-second safety event."""
    from app.services.demo_engine import start_demo
    from app.db.session import async_session
    result = await start_demo(async_session, guardian_user_id=user.id)
    return result


@router.post("/stop")
async def stop_demo_mode(
    user: User = Depends(_demo_role),
):
    """Stop demo scenario and clean up."""
    from app.services.demo_engine import stop_demo
    from app.db.session import async_session
    result = await stop_demo(async_session)
    return result


@router.get("/status")
async def demo_status(
    user: User = Depends(get_current_user),
):
    """Get current demo mode status."""
    from app.services.demo_engine import get_demo_status
    return get_demo_status()
