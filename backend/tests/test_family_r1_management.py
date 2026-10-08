"""Offline R1 behavior/source tests. No claims of PostgreSQL concurrency proof."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def setup(monkeypatch):
    from app.services import family_circle_management_service as m
    actor = S(id=uuid4(), date_of_birth=date(1980, 1, 1))
    target = S(id=uuid4(), date_of_birth=date(1985, 1, 1))
    circle = S(id=uuid4(), plan='family')
    snap = S(circle=circle, membership=S(id=uuid4(), role='owner', seat='member'))
    db = S(execute=AsyncMock(), get=AsyncMock(), flush=AsyncMock())
    monkeypatch.setattr(m, 'locked_membership', AsyncMock(return_value=snap))
    monkeypatch.setattr(m, 'authorize', AsyncMock())
    monkeypatch.setattr(m, 'append_family_audit', AsyncMock())
    monkeypatch.setattr(m, 'notify', AsyncMock())
    return m, actor, target, circle, snap, db


@pytest.mark.parametrize('dob,allowed', [(date(1980,1,1), True), (None,False), (date.today(),False)])
def test_coadmin_uses_canonical_age_validator(monkeypatch,dob,allowed):
    from app.services import family_circle_lifecycle_service as l
    from app.services import family_circle_runtime_authority as r
    actor,target,circle=uuid4(),uuid4(),uuid4()
    snaps={actor:S(circle=S(id=circle),membership=S(role='owner')),
           target:S(circle=S(id=circle),membership=S(role='adult_member'))}
    monkeypatch.setattr(r,'runtime_decision',AsyncMock(return_value=S(canonical=True,allowed=True)))
    monkeypatch.setattr(r,'membership_snapshot',AsyncMock(side_effect=lambda db,uid:snaps[uid]))
    monkeypatch.setattr(l,'append_family_audit',AsyncMock())
    db=S(get=AsyncMock(return_value=S(date_of_birth=dob)),execute=AsyncMock(return_value=S(scalar_one_or_none=lambda:None)))
    if allowed:
        run(l.appoint_co_admin(db,owner=S(id=actor),target_user_id=target))
        assert snaps[target].membership.role=='co_admin'
    else:
        with pytest.raises(ValueError):run(l.appoint_co_admin(db,owner=S(id=actor),target_user_id=target))
        assert snaps[target].membership.role=='adult_member'


@pytest.mark.parametrize('canonical,allowed', [(False,True),(True,False),(False,False)])
def test_authority_denies_noncanonical_or_disallowed(monkeypatch,canonical,allowed):
    from app.services import family_circle_management_service as m
    monkeypatch.setattr(m,'runtime_decision',AsyncMock(return_value=S(canonical=canonical,allowed=allowed,code='denied')))
    with pytest.raises(PermissionError):run(m.authorize(None,uuid4(),'manage_co_admin'))


@pytest.mark.parametrize('variant', ['wrong_recipient','expired','consumed','former_owner','changed_membership'])
def test_transfer_accept_revalidates(monkeypatch,variant):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    row=dict(target_user_id=actor.id,state='pending',expires_at=datetime.now(timezone.utc)+timedelta(hours=1),
             actor_user_id=target.id,membership_id=snap.membership.id)
    if variant=='wrong_recipient':row['target_user_id']=uuid4()
    if variant=='expired':row['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
    if variant=='consumed':row['state']='completed'
    if variant=='changed_membership':row['membership_id']=uuid4()
    monkeypatch.setattr(m,'load_operation',AsyncMock(return_value=row))
    monkeypatch.setattr(m,'membership_snapshot',AsyncMock(return_value=None if variant=='former_owner' else snap))
    db.get.return_value=target
    primitive=AsyncMock();monkeypatch.setattr(m.lifecycle,'transfer_ownership',primitive)
    with pytest.raises(PermissionError):run(m.accept_transfer(db,actor=actor,circle_id=circle.id,operation_id=uuid4()))
    primitive.assert_not_awaited()


def test_paid_transfer_preserves_pending_mandate(monkeypatch):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    from app.services import family_circle_entitlement_service as e
    row=dict(target_user_id=actor.id,state='pending',expires_at=datetime.now(timezone.utc)+timedelta(hours=1),
             actor_user_id=target.id,membership_id=snap.membership.id)
    monkeypatch.setattr(m,'load_operation',AsyncMock(return_value=row))
    monkeypatch.setattr(m,'membership_snapshot',AsyncMock(return_value=snap))
    monkeypatch.setattr(e,'resolve_entitlement',AsyncMock(return_value=S(access_until=None)))
    primitive=AsyncMock(return_value={'owner_user_id':str(actor.id)})
    monkeypatch.setattr(m.lifecycle,'transfer_ownership',primitive);db.get.return_value=target
    result=run(m.accept_transfer(db,actor=actor,circle_id=circle.id,operation_id=uuid4()))
    assert result['payment_transition_pending'] is True
    assert primitive.await_args.kwargs['defer_mandate_transition'] is True
    assert 'billing_mandate_ready' not in primitive.await_args.kwargs
    params=db.execute.await_args.args[1]
    assert params['state']=='provider_pending' and '"mandate_verified": false' in params['details']
    assert str(target.id) in params['details']


def test_removal_happens_before_undo_record(monkeypatch):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    snap.membership.role='adult_member'
    monkeypatch.setattr(m,'membership_snapshot',AsyncMock(return_value=snap))
    order=[]
    async def remove(*a,**k):order.append('removed');return {'removed':True}
    async def op(*a,**k):
        order.append('undo'); assert k['details']['role']=='adult_member'
        seconds=(k['expires_at']-datetime.now(timezone.utc)).total_seconds();assert 8<seconds<=10
        return uuid4()
    monkeypatch.setattr(m.lifecycle,'remove_member',remove);monkeypatch.setattr(m,'operation',op)
    result=run(m.remove_member(db,actor=actor,circle_id=circle.id,target_id=target.id))
    assert order==['removed','undo'] and result['removed'] and result['undo_until']


@pytest.mark.parametrize('variant',['wrong_actor','expired','consumed','member_actor','owner_target','already_joined'])
def test_undo_fails_closed(monkeypatch,variant):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    row=dict(actor_user_id=actor.id,state='pending',expires_at=datetime.now(timezone.utc)+timedelta(seconds=10),
             membership_id=uuid4(),target_user_id=target.id)
    if variant=='wrong_actor':row['actor_user_id']=uuid4()
    if variant=='expired':row['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
    if variant=='consumed':row['state']='undone'
    if variant=='member_actor':snap.membership.role='adult_member'
    db.get.return_value=S(status='removed',role='owner' if variant=='owner_target' else 'adult_member')
    db.execute.return_value=S(first=lambda:object())
    monkeypatch.setattr(m,'load_operation',AsyncMock(return_value=row))
    with pytest.raises(PermissionError):run(m.undo_removal(db,actor=actor,circle_id=circle.id,operation_id=uuid4()))
    m.append_family_audit.assert_not_awaited()


def test_parental_declaration_never_activates(monkeypatch):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    op=AsyncMock(return_value=uuid4());monkeypatch.setattr(m,'operation',op)
    result=run(m.request_minor(db,actor=actor,circle_id=circle.id,evidence_id=uuid4(),
                              child_name='Synthetic Child',birth_date=date.today(),relationship='parent'))
    assert result['activated'] is False and result['state']=='awaiting_verification'
    details=op.await_args.kwargs['details']
    assert details['verified'] is False and 'subject_binding' in details
    assert 'child_name' not in details and 'date_of_birth' not in details


@pytest.mark.parametrize('relationship,dob',[('friend',date.today()),('parent',date(1980,1,1)),('parent',date(2999,1,1))])
def test_minor_request_rejects_invalid_admission(monkeypatch,relationship,dob):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    with pytest.raises(ValueError):run(m.request_minor(db,actor=actor,circle_id=circle.id,evidence_id=uuid4(),
        child_name='Synthetic',birth_date=dob,relationship=relationship))


@pytest.mark.parametrize('delete',[True,False])
def test_paid_cancellation_not_faked(monkeypatch,delete):
    m,actor,target,circle,snap,db=setup(monkeypatch)
    from app.services import family_circle_entitlement_service as e
    monkeypatch.setattr(e,'resolve_entitlement',AsyncMock(return_value=S()))
    monkeypatch.setattr(m,'operation',AsyncMock(return_value=uuid4()))
    result=run(m.cancel_or_delete(db,actor=actor,circle_id=circle.id,delete=delete))
    assert result['completed'] is False and result['state']=='provider_pending'
    db.execute.assert_not_awaited()


def test_source_transaction_and_schema_contracts():
    router=(ROOT/'app/api/family_circle_management.py').read_text(encoding='utf-8')
    for action in ('ownership_transfer','circle_delete','member_remove','plan_cancel','minor_add'):
        assert action in router
    assert router.index('await consume_stepup_for_action')<router.index('result = await management.co_admin')
    assert 'await session.commit()' in router and 'await session.rollback()' in router
    migration=(ROOT/'migrations/versions/fc08_r1_lifecycle.py').read_text(encoding='utf-8')
    assert 'down_revision = "auth05_security_foundation"' in migration
    assert 'DROP TABLE' not in migration and 'DELETE FROM' not in migration
    assert 'uq_family_pending_transfer' in migration
    plan=(ROOT/'app/services/family_circle_plan_service.py').read_text(encoding='utf-8')
    assert "expires_at > clock_timestamp()" in plan and "details->>'seat'=:seat" in plan


def test_erasure_guard_precedes_freeze():
    source=(ROOT/'app/services/erasure_service.py').read_text(encoding='utf-8')
    assert source.index('await depart_for_erasure(session, user)')<source.index('deleted_at=now')
    route=(ROOT/'app/api/erasure.py').read_text(encoding='utf-8')
    assert 'except erasure_service.ErasureMembershipBlocked' in route


def test_undo_capacity_reserves_one_restored_seat():
    source=(ROOT/'app/services/family_circle_management_service.py').read_text(encoding='utf-8')
    assert 'if occupied + invites >= capacity:' in source
    assert 'if occupied + invites > capacity:' not in source
