"""Provider-neutral Family Circle plan-transition primitives for Phase 6.

No public payment endpoint calls these directly. A future verified billing adapter
activates the stored transition only after the provider event is authenticated.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.family_circle_permissions import ACTION_MANAGE_BILLING
from app.models.family_circle import CircleMembership, FamilyCircle
from app.models.user import User
from app.services.family_circle_audit_service import append_family_audit


async def _owner_circle(session: AsyncSession, owner: User):
    from app.services.family_circle_runtime_authority import membership_snapshot, runtime_decision
    decision = await runtime_decision(session, actor_user_id=owner.id, action=ACTION_MANAGE_BILLING)
    if not decision.canonical or not decision.allowed:
        raise PermissionError(decision.code)
    snap = await membership_snapshot(session, owner.id)
    if snap is None or snap.membership.role != 'owner':
        raise PermissionError('owner_only_billing')
    return snap


async def prepare_upgrade_to_family(session: AsyncSession, *, owner: User) -> dict:
    """Record Owner intent without activating a paid Family entitlement.

    No provider call occurs here.  The existing verified billing-event boundary
    remains the only route that applies the actual plan change.
    """
    snap = await _owner_circle(session, owner)
    source = str(snap.circle.plan or '')
    if source not in {'trial', 'individual'}:
        raise ValueError('Only Trial or Individual can be upgraded to Family.')
    result = await session.execute(text("""
        UPDATE family_circle_entitlements
           SET pending_plan='family', pending_plan_effective_at=NULL,
               pending_seat_assignments=NULL, updated_at=NOW()
         WHERE circle_id=:circle_id
     RETURNING circle_id
    """), {'circle_id': str(snap.circle.id)})
    if result.scalar_one_or_none() is None:
        raise ValueError('Canonical entitlement row is missing.')
    await append_family_audit(
        session, circle_id=snap.circle.id, actor_user_id=owner.id, subject_user_id=None,
        event_type='plan_upgrade_prepared', details={'from': source, 'to': 'family', 'provider_verified': False},
    )
    return {'target_plan': 'family', 'state': 'provider_action_required', 'plan_changed': False}


async def stage_family_to_individual_downgrade(
    session: AsyncSession,
    *,
    owner: User,
    protected_user_id,
    guardian_user_ids: list,
    effective_at: datetime,
) -> dict:
    """Store the Owner's seat choice before a Family -> Individual downgrade.

    This does not change the active plan. The future verified provider event at
    period end applies the stored selection atomically.
    """
    snap = await _owner_circle(session, owner)
    if str(snap.circle.plan) != 'family':
        raise ValueError('Only a Family plan can be downgraded to Individual.')
    guardians = [str(x) for x in guardian_user_ids]
    protected = str(protected_user_id)
    if not protected or len(guardians) > 2 or protected in guardians or len(set(guardians)) != len(guardians):
        raise ValueError('Individual requires one Protected person and up to two distinct Guardians.')
    if effective_at.tzinfo is None:
        raise ValueError('Downgrade effective time must be timezone-aware.')

    members = list((await session.execute(
        select(CircleMembership).where(
            CircleMembership.circle_id == snap.circle.id,
            CircleMembership.status == 'active',
        )
    )).scalars().all())
    by_user = {str(m.user_id): m for m in members}
    if protected not in by_user or any(uid not in by_user for uid in guardians):
        raise ValueError('Every retained seat must belong to an active member of this circle.')
    for uid in guardians:
        if by_user[uid].role == 'minor':
            raise ValueError('A Minor cannot hold an Individual Guardian seat.')

    retained = {protected, *guardians}
    if str(owner.id) not in retained:
        raise ValueError('The Owner must remain in the circle during Family to Individual downgrade or transfer ownership first.')

    assignments = {'protected': protected, 'guardians': guardians}
    await session.execute(
        text(
            """
            UPDATE family_circle_entitlements
               SET pending_plan='individual',
                   pending_plan_effective_at=:effective_at,
                   pending_seat_assignments=CAST(:assignments AS JSONB),
                   updated_at=NOW()
             WHERE circle_id=:circle_id
            """
        ),
        {'circle_id': str(snap.circle.id), 'effective_at': effective_at, 'assignments': json.dumps(assignments, sort_keys=True)},
    )
    await append_family_audit(
        session,
        circle_id=snap.circle.id,
        actor_user_id=owner.id,
        subject_user_id=None,
        event_type='plan_downgrade_scheduled',
        details={'target_plan': 'individual', 'effective_at': effective_at.isoformat(), 'retained_count': 1 + len(guardians)},
    )
    return {'target_plan': 'individual', 'effective_at': effective_at, 'assignments': assignments}


async def apply_upgrade_to_family(session: AsyncSession, *, circle: FamilyCircle, effective_at: datetime) -> None:
    """Convert every current Trial/Individual seat into a mutual Family member seat."""
    previous = str(circle.plan or '')
    if previous not in {'trial', 'individual', 'family'}:
        raise ValueError('Unsupported source plan for Family upgrade.')
    if previous != 'family':
        await session.execute(
            text("UPDATE circle_memberships SET seat='member' WHERE circle_id=:circle_id AND status='active'"),
            {'circle_id': str(circle.id)},
        )
        circle.plan = 'family'
        await append_family_audit(
            session,
            circle_id=circle.id,
            actor_user_id=circle.owner_user_id,
            subject_user_id=None,
            event_type='plan_changed',
            details={'from': previous, 'to': 'family', 'effective_at': effective_at.isoformat()},
        )


async def apply_staged_family_to_individual_downgrade(
    session: AsyncSession,
    *,
    circle: FamilyCircle,
    effective_at: datetime,
) -> list[str]:
    """Apply the preselected Individual seats; return removed user ids."""
    row = (await session.execute(
        text("SELECT pending_plan, pending_seat_assignments FROM family_circle_entitlements WHERE circle_id=:circle_id FOR UPDATE"),
        {'circle_id': str(circle.id)},
    )).mappings().first()
    if not row or str(row['pending_plan'] or '') != 'individual' or not row['pending_seat_assignments']:
        raise ValueError('Family downgrade seat selection is missing.')
    raw = row['pending_seat_assignments']
    assignments = raw if isinstance(raw, dict) else json.loads(raw)
    protected = str(assignments.get('protected') or '')
    guardians = [str(x) for x in assignments.get('guardians') or []]
    if not protected or len(guardians) > 2 or protected in guardians or len(set(guardians)) != len(guardians):
        raise ValueError('Stored downgrade seat selection is invalid.')
    keep = {protected, *guardians}
    if str(circle.owner_user_id) not in keep:
        raise ValueError('Stored downgrade selection would remove the Owner; transfer ownership first.')

    members = list((await session.execute(
        select(CircleMembership).where(CircleMembership.circle_id == circle.id, CircleMembership.status == 'active')
    )).scalars().all())
    by_user = {str(m.user_id): m for m in members}
    if protected not in by_user or any(uid not in by_user for uid in guardians):
        raise ValueError('Stored downgrade members are no longer active.')
    if any(by_user[uid].role == 'minor' for uid in guardians):
        raise ValueError('A Minor cannot hold an Individual Guardian seat.')

    removed: list[str] = []
    for uid, membership in by_user.items():
        if uid == protected:
            membership.seat = 'protected'
        elif uid in guardians:
            membership.seat = 'guardian'
        else:
            membership.status = 'removed'
            membership.ended_at = effective_at
            removed.append(uid)
            await session.execute(
                text("""
                    INSERT INTO family_sharing_states (user_id, paused, pause_mode, paused_until, updated_at)
                    VALUES (:uid, TRUE, 'manual', NULL, :at)
                    ON CONFLICT (user_id) DO UPDATE SET paused=TRUE, pause_mode='manual', paused_until=NULL, updated_at=EXCLUDED.updated_at
                """),
                {'uid': uid, 'at': effective_at},
            )
            await append_family_audit(
                session, circle_id=circle.id, actor_user_id=circle.owner_user_id, subject_user_id=membership.user_id,
                event_type='member_removed', details={'reason': 'family_to_individual_downgrade'},
            )
            from app.services.family_circle_notification_outbox import enqueue_family_notifications
            await enqueue_family_notifications(
                session,
                circle_id=circle.id,
                recipient_user_ids=[membership.user_id],
                event_type='family_member_removed',
                title='NISCHINT Family Circle',
                body='Your Family plan changed and your seat was removed from this circle.',
                payload={'reason': 'family_to_individual_downgrade'},
                event_key_prefix=f'downgrade-removed:{circle.id}:{effective_at.isoformat()}',
            )
    circle.plan = 'individual'
    await append_family_audit(
        session, circle_id=circle.id, actor_user_id=circle.owner_user_id, subject_user_id=None,
        event_type='plan_changed', details={'from': 'family', 'to': 'individual', 'effective_at': effective_at.isoformat()},
    )
    return removed


__all__ = [
    'prepare_upgrade_to_family',
    'stage_family_to_individual_downgrade',
    'apply_upgrade_to_family',
    'apply_staged_family_to_individual_downgrade',
]
