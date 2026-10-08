"""Public canonical membership management; no legacy relationship mutations."""
from datetime import date
from uuid import UUID
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.api.stepup_auth import consume_stepup_for_action
from app.models.user import User
from app.models.family_circle import CircleMembership
from app.services.family_circle_runtime_authority import membership_snapshot
from app.services import family_circle_management_service as management

router = APIRouter()


class ManagementRequest(BaseModel):
    circle_id: UUID
    target_id: UUID | None = None
    operation_id: UUID | None = None
    child_name: str | None = Field(default=None, min_length=1, max_length=120)
    date_of_birth: date | None = None
    relationship: str | None = None


@router.get('/management')
async def management_status(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    snap = await membership_snapshot(session, user.id)
    if snap is None:
        raise HTTPException(404, 'Current Family Circle required')
    # No member location/history or contact identifiers are disclosed here.
    members = []
    if snap.membership.role in {'owner', 'co_admin'}:
        rows = (await session.execute(select(CircleMembership, User).join(User, User.id == CircleMembership.user_id).where(
            CircleMembership.circle_id == snap.circle.id, CircleMembership.status == 'active'))).all()
        for membership, person in rows:
            members.append({'user_id': str(person.id), 'name': person.full_name,
                            'role': membership.role, 'seat': membership.seat})
    pending = (await session.execute(text("""SELECT id,kind,state,expires_at,
            actor_user_id,target_user_id FROM family_lifecycle_operations
        WHERE circle_id=:circle AND (actor_user_id=:user OR target_user_id=:user)
          AND state IN ('pending','provider_pending','awaiting_verification')
          AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY created_at DESC LIMIT 30"""),
        {'circle': snap.circle.id, 'user': user.id})).mappings().all()
    result = {'circle_id': str(snap.circle.id), 'role': snap.membership.role,
              'minor_request_target_id': str(uuid.uuid4()),
              'members': members, 'operations': [dict(row) for row in pending]}
    await session.commit()  # Preserve idempotent age-18 reconciliation.
    return result


PROOFS = {'transfer_request': 'ownership_transfer', 'remove_member': 'member_remove',
          'child_request': 'minor_add', 'cancel_plan': 'plan_cancel', 'delete_circle': 'circle_delete'}
TARGET_ACTIONS = {'appoint_co_admin', 'remove_co_admin', 'transfer_request', 'remove_member', 'child_request'}
OPERATION_ACTIONS = {'transfer_accept', 'removal_undo'}


@router.post('/management/{action}')
async def manage(action: str, body: ManagementRequest, request: Request,
                 session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    if action not in TARGET_ACTIONS | OPERATION_ACTIONS | {'cancel_plan', 'delete_circle'}:
        raise HTTPException(404, 'Unknown Family Circle action')
    if action in TARGET_ACTIONS and body.target_id is None:
        raise HTTPException(422, 'Target binding required')
    if action in OPERATION_ACTIONS and body.operation_id is None:
        raise HTTPException(422, 'Operation required')
    try:
        if action in PROOFS:
            await consume_stepup_for_action(request, session=session, user=user,
                action=PROOFS[action], circle_id=body.circle_id,
                target_id=body.target_id if action in TARGET_ACTIONS else None)
        common = dict(actor=user, circle_id=body.circle_id)
        if action in {'appoint_co_admin', 'remove_co_admin'}:
            result = await management.co_admin(session, **common, target_id=body.target_id, appoint=action == 'appoint_co_admin')
        elif action == 'transfer_request':
            result = await management.request_transfer(session, **common, target_id=body.target_id)
        elif action == 'transfer_accept':
            result = await management.accept_transfer(session, **common, operation_id=body.operation_id)
        elif action == 'remove_member':
            result = await management.remove_member(session, **common, target_id=body.target_id)
        elif action == 'removal_undo':
            result = await management.undo_removal(session, **common, operation_id=body.operation_id)
        elif action == 'child_request':
            if not body.child_name or not body.date_of_birth or not body.relationship:
                raise ValueError('Child name, DOB and parental relationship required')
            result = await management.request_minor(session, **common, evidence_id=body.target_id,
                child_name=body.child_name, birth_date=body.date_of_birth, relationship=body.relationship)
        else:
            result = await management.cancel_or_delete(session, **common, delete=action == 'delete_circle')
        await session.commit()
        # Existing outbox worker owns retries. Queued is not delivered.
        return {**result, 'notification_delivery': 'queued_where_required'}
    except HTTPException:
        await session.rollback()
        raise
    except (PermissionError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(403 if isinstance(exc, PermissionError) else 422, str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
