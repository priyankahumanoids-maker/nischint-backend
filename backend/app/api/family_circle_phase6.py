"""Phase 6 Family Circle entitlement/privacy/audit API.

No live payment-provider endpoint is exposed in this build. High-risk lifecycle
operations that require fresh step-up OTP remain internal until that security
boundary is available.
"""
from __future__ import annotations

from functools import partial
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.core.family_circle_permissions import (
    ACTION_INVITE_MEMBER,
    ACTION_LEAVE_CIRCLE,
    ACTION_PAUSE_OWN_SHARING,
    ACTION_VIEW_WHO_VIEWED,
)
from app.core.family_consent_policy import CURRENT_FAMILY_NOTICE_VERSION
from app.services.family_circle_age_transition import age18_status, reconcile_age18_for_user
from app.services.family_circle_audit_service import count_location_views, who_viewed_my_location
from app.services.family_circle_consent_service import current_self_consent_decisions, record_self_consent
from app.services.family_circle_entitlement_service import resolve_entitlement
from app.services.family_circle_lifecycle_service import (
    deliver_circle_message,
    deliver_pause_notification,
    leave_circle,
    pause_own_sharing,
    resume_own_sharing,
)
from app.services.family_circle_runtime_authority import (
    membership_snapshot,
    runtime_decision,
    runtime_snapshot,
    bounded_runtime_read,
    sharing_paused,
)

router = APIRouter(prefix='/family-circle', tags=['family-circle-phase6'])


class PauseRequest(BaseModel):
    mode: str


class ConsentRequest(BaseModel):
    decisions: dict[str, bool] = Field(default_factory=dict)
    notice_version: str = CURRENT_FAMILY_NOTICE_VERSION
    language: str = 'en'
    device_id: str | None = None


class StageDowngradeRequest(BaseModel):
    protected_user_id: str
    guardian_user_ids: list[str] = Field(default_factory=list, max_length=2)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get('/plan-catalog')
async def plan_catalog(session: AsyncSession = Depends(get_db_session)):
    from app.services.family_circle_plan_catalog_service import list_catalog_plans, public_plan_payload
    return {'plans': [public_plan_payload(plan) for plan in await list_catalog_plans(session)]}


@router.post('/plan-change/prepare-family')
async def prepare_family_upgrade(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        from app.services.family_circle_plan_change_service import prepare_upgrade_to_family
        result = await prepare_upgrade_to_family(session, owner=user)
        await session.commit()
        return result
    except Exception as exc:
        await session.rollback()
        raise _http_error(exc)


@router.post('/plan-change/stage-individual')
async def stage_individual_downgrade(req: StageDowngradeRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        from app.services.family_circle_runtime_authority import membership_snapshot
        from app.services.family_circle_entitlement_service import resolve_entitlement
        from app.services.family_circle_plan_change_service import stage_family_to_individual_downgrade
        snap = await membership_snapshot(session, user.id)
        if snap is None or snap.membership.role != 'owner':
            raise PermissionError('owner_only_billing')
        ent = await resolve_entitlement(session, snap.circle)
        if snap.circle.plan != 'family':
            raise ValueError('Only a Family plan can be downgraded to Individual.')
        if ent.state != 'paid_active' or ent.access_until is None:
            raise ValueError('A verified active paid period is required before scheduling a downgrade.')
        result = await stage_family_to_individual_downgrade(
            session, owner=user, protected_user_id=req.protected_user_id,
            guardian_user_ids=req.guardian_user_ids, effective_at=ent.access_until,
        )
        await session.commit()
        return {**result, 'plan_changed': False, 'provider_action_required': True}
    except Exception as exc:
        await session.rollback()
        raise _http_error(exc)


@router.get('/entitlement')
@partial(bounded_runtime_read, timeout_seconds=20.0)
async def my_entitlement(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    snap = await membership_snapshot(session, user.id)
    if snap is None:
        raise HTTPException(status_code=404, detail='Family Circle membership not found.')
    ent = await resolve_entitlement(session, snap.circle)
    runtime = await runtime_snapshot(session, user.id)
    owner = await session.get(User, snap.circle.owner_user_id)
    invite_decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_INVITE_MEMBER)
    pause_decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_PAUSE_OWN_SHARING)
    leave_decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_LEAVE_CIRCLE)
    viewed_decision = await runtime_decision(session, actor_user_id=user.id, action=ACTION_VIEW_WHO_VIEWED)
    paused = await sharing_paused(session, user.id)
    await session.commit()  # persists idempotent age/timed-resume reconciliation

    from app.services.family_circle_plan_catalog_service import get_catalog_plan, public_plan_payload
    plan_config = public_plan_payload(await get_catalog_plan(session, snap.circle.plan))
    tracked = bool(snap.circle.plan == 'family' or snap.membership.seat == 'protected')
    if ent.lifeline:
        protection_state = 'protection_off'
    elif paused:
        protection_state = 'sharing_paused'
    elif not tracked:
        protection_state = 'guardian_alerts'
    elif not bool(runtime.get('can_produce_location')):
        protection_state = 'setup_required'
    else:
        protection_state = 'protected'

    from datetime import datetime, timezone
    point = datetime.now(timezone.utc)
    trial_remaining_seconds = None
    trial_day = None
    if snap.circle.plan == 'trial' and snap.circle.trial_started_at and snap.circle.trial_ends_at:
        trial_remaining_seconds = max(0, int((snap.circle.trial_ends_at - point).total_seconds()))
        elapsed = max(0, int((point - snap.circle.trial_started_at).total_seconds()))
        trial_day = min(7, elapsed // 86400 + 1) if trial_remaining_seconds > 0 else 7

    return {
        'plan': snap.circle.plan,
        'plan_config': plan_config,
        'trial_remaining_seconds': trial_remaining_seconds,
        'trial_day': trial_day,
        'role': snap.membership.role,
        'seat': snap.membership.seat,
        'owner_name': (owner.full_name if owner else None) or 'the Owner',
        'sharing_paused': paused,
        'tracked': tracked,
        'protection_state': protection_state,
        'can_invite': bool(invite_decision.allowed),
        'can_pause': bool(pause_decision.allowed),
        'can_leave': bool(leave_decision.allowed),
        'can_view_who_viewed': bool(viewed_decision.allowed),
        'can_produce_location': bool(runtime.get('can_produce_location')),
        'can_produce_background_location': bool(runtime.get('can_produce_background_location')),
        'can_produce_ai': bool(runtime.get('can_produce_ai')),
        'can_produce_voice': bool(runtime.get('can_produce_voice')),
        'can_produce_wearable': bool(runtime.get('can_produce_wearable')),
        'state': ent.state,
        'entitlement': ent.permission_entitlement,
        'lifeline': ent.lifeline,
        'reason': ent.reason,
        'access_until': ent.access_until,
        'grace_until': ent.grace_until,
        'payment_required': ent.payment_required,
        'cancel_at_period_end': ent.cancel_at_period_end,
        'pending_plan': ent.pending_plan,
        'pending_plan_effective_at': ent.pending_plan_effective_at,
        'can_manage_plan': snap.membership.role == 'owner',
        'gateway_enabled': False,
    }


@router.post('/sharing/pause')
async def pause_sharing(req: PauseRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        result = await pause_own_sharing(session, user=user, mode=req.mode)
        outbox_ids = list(result.pop('notification_outbox_ids', []) or [])
        await session.commit()
        # Delivery is intentionally post-commit; state never rolls back because
        # push transport is temporarily unavailable.
        await deliver_pause_notification(session, outbox_ids=outbox_ids)
        await session.commit()
        return result
    except Exception as exc:
        await session.rollback()
        raise _http_error(exc)


@router.post('/sharing/resume')
async def resume_sharing(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        result = await resume_own_sharing(session, user=user)
        await session.commit()
        return result
    except Exception as exc:
        await session.rollback()
        raise _http_error(exc)


@router.post('/leave')
async def leave_my_circle(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        result = await leave_circle(session, user=user)
        outbox_ids = list(result.pop('notification_outbox_ids', []) or [])
        message = str(result.get('message') or 'A member left the circle')
        await session.commit()
        await deliver_circle_message(session, outbox_ids=outbox_ids)
        await session.commit()
        return result
    except Exception as exc:
        await session.rollback()
        raise _http_error(exc)


@router.get('/consent')
async def my_family_consent(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    return {
        'notice_version': CURRENT_FAMILY_NOTICE_VERSION,
        'decisions': await current_self_consent_decisions(session, user_id=user.id),
    }


@router.post('/consent')
async def save_family_consent(req: ConsentRequest, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        decisions = await record_self_consent(
            session,
            user=user,
            decisions=req.decisions,
            notice_version=req.notice_version,
            language=req.language,
            device_id=req.device_id,
        )
        await reconcile_age18_for_user(session, user.id)
        status = await age18_status(session, user.id)
        await session.commit()
        return {
            'notice_version': CURRENT_FAMILY_NOTICE_VERSION,
            'decisions': decisions,
            'age18_status': status,
        }
    except Exception as exc:
        await session.rollback()
        raise _http_error(exc)


@router.get('/who-viewed-me')
async def who_viewed_me(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    views = await who_viewed_my_location(session, user_id=user.id, days=30, limit=limit, offset=offset)
    total = await count_location_views(session, user_id=user.id, days=30)
    return {
        'days': 30,
        'total': total,
        'limit': limit,
        'offset': offset,
        'has_more': offset + len(views) < total,
        'views': views,
    }


@router.get('/age18-status')
async def my_age18_status(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    await reconcile_age18_for_user(session, user.id)
    status = await age18_status(session, user.id)
    await session.commit()
    return status


# R1 canonical application actions; shares existing identity/session boundary.
from app.api.family_circle_management import router as management_router
router.include_router(management_router)
