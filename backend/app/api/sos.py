# SOS Silent Mode API — Covert emergency trigger system
import logging
import os
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.core.product_roles import PROTECTED_MEMBER_ROLES
from app.core.rate_limiter import limiter
from app.models.user import User
from app.services import sos_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sos", tags=["sos"])

_ESCAPE_ROLES = {"guardian", "operator", "admin"}
_escape_role = require_role(sorted(_ESCAPE_ROLES))
# Trigger/Cancel allow the actual at-risk user roles too. Family members are
# protected members as well, so use the canonical product-role set rather than
# maintaining another partial hard-coded list here.
_trigger_role = require_role(sorted(_ESCAPE_ROLES | PROTECTED_MEMBER_ROLES))


# ── Schemas ──

class SOSConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    voice_keywords: Optional[List[str]] = None
    chain_notification: Optional[bool] = None
    chain_notification_delay: Optional[int] = Field(None, ge=0, le=300)
    chain_call: Optional[bool] = None
    chain_call_delay: Optional[int] = Field(None, ge=0, le=300)
    chain_call_preset_name: Optional[str] = Field(None, max_length=120)
    chain_notification_title: Optional[str] = Field(None, max_length=200)
    chain_notification_message: Optional[str] = Field(None, max_length=500)
    trusted_contacts: Optional[List[dict]] = None
    auto_share_location: Optional[bool] = None
    silent_mode: Optional[bool] = None


class SOSTrigger(BaseModel):
    trigger_type: str = Field("manual", max_length=30)
    lat: Optional[float] = None
    lng: Optional[float] = None


class SOSCancel(BaseModel):
    resolved_by: str = Field("user", max_length=50)


# ── Config ──

@router.get("/config")
async def get_config(
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    config = await svc.get_or_create_config(session, user.id)
    await session.commit()
    return config


@router.put("/config")
async def update_config(
    body: SOSConfigUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    return await svc.update_config(session, user.id, body.model_dump(exclude_unset=True))


# ── Trigger ──

# Loadtest short-circuit guard (LT-01). Two-key gate:
#   1. Env `LOADTEST_MODE=true` MUST be set on the deployment
#   2. Request MUST carry `X-Loadtest-Token` header matching env `LOADTEST_TOKEN`
# Production deployments leave LOADTEST_MODE unset → header has zero effect.
# When BOTH are satisfied the endpoint returns a synthetic success WITHOUT:
#   * writing an SOS row to Postgres
#   * fanning out push/SMS/SACHET notifications
#   * burning external API quota
# This lets us load-test the auth/role/validation path on preview without
# touching the real safety pipeline. See /app/memory/CHANGELOG.md SEC-LT-01.

def _loadtest_short_circuit_allowed(token_header: Optional[str]) -> bool:
    if os.environ.get("LOADTEST_MODE", "").lower() != "true":
        return False
    expected = os.environ.get("LOADTEST_TOKEN", "")
    if not expected or not token_header:
        return False
    # Constant-time compare so the token isn't oracle-discoverable.
    import hmac
    return hmac.compare_digest(token_header, expected)


@router.post("/trigger")
@limiter.limit("10/minute")
async def trigger_sos(
    request: Request,
    body: SOSTrigger,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_trigger_role),
    x_loadtest_token: Optional[str] = Header(default=None, alias="X-Loadtest-Token"),
):
    if _loadtest_short_circuit_allowed(x_loadtest_token):
        # Exercises everything up to the service-layer side effects:
        # request parse, auth, role gate, rate-limit accounting. Matches
        # the production response shape closely enough that locust tasks
        # don't need conditional assertions.
        logger.info(
            "[LT-01] SOS trigger short-circuited for loadtest user_id=%s",
            user.id,
        )
        return {
            "id":            f"loadtest-{uuid.uuid4()}",
            "user_id":       str(user.id),
            "trigger_type":  body.trigger_type,
            "lat":           body.lat,
            "lng":           body.lng,
            "status":        "loadtest_acknowledged",
            "mode":          "loadtest",
            "side_effects":  "suppressed",
        }
    return await svc.trigger_sos(
        session, user.id,
        trigger_type=body.trigger_type,
        lat=body.lat, lng=body.lng,
    )


# ── Cancel ──

@router.post("/cancel/{sos_id}")
async def cancel_sos(
    sos_id: str,
    body: SOSCancel,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_trigger_role),
):
    result = await svc.cancel_sos(session, user.id, uuid.UUID(sos_id), resolved_by=body.resolved_by)
    if not result:
        raise HTTPException(status_code=404, detail="SOS event not found")
    return result


# ── History ──

@router.get("/history")
async def sos_history(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(_escape_role),
):
    logs = await svc.get_history(session, user.id, limit)
    return {"history": logs, "count": len(logs)}
