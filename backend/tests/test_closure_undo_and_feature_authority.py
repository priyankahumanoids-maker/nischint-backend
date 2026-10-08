"""Focused offline closure proofs; PostgreSQL locking/transactions remain deferred."""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.core import family_circle_permissions as p

ROOT = Path(__file__).resolve().parents[1]
def run(coro): return asyncio.run(coro)


def undo_fixture(monkeypatch):
    from app.services import family_circle_management_service as m
    from app.services import family_circle_invite_service as invites
    actor, target, circle, oid, mid = [uuid4() for _ in range(5)]
    membership = S(id=mid, user_id=target, circle_id=circle, status='removed', role='adult_member', seat='member', ended_at='removed')
    row = dict(id=oid, circle_id=circle, kind='member_remove', actor_user_id=actor, target_user_id=target,
               membership_id=mid, state='pending', expires_at=datetime.now(timezone.utc)+timedelta(seconds=10), details={'seat':'member'})
    # Full Family before removal; removal moves exactly one seat into reservation.
    state = S(active=4, reservations=[], invites=0, claim=True)
    state.active -= 1
    state.reservations.append(oid)
    async def execute(stmt, params=None):
        sql = str(stmt)
        if 'SELECT COUNT(*) FROM family_lifecycle_operations' in sql:
            assert 'id IS DISTINCT FROM CAST(:exclude_removal_id AS UUID)' in sql
            excluded = params['exclude_removal_id']
            return S(scalar_one=lambda:sum(r != excluded for r in state.reservations))
        if 'count(*)' in sql: return S(scalar_one=lambda:state.active)
        if "SET state='undone'" in sql:
            assert "state='pending'" in sql and 'expires_at > clock_timestamp()' in sql
            assert params['id'] == oid
            return S(scalar_one_or_none=lambda:oid if state.claim else None)
        return S(first=lambda:None)
    db = S(execute=AsyncMock(side_effect=execute), get=AsyncMock(return_value=membership), flush=AsyncMock())
    monkeypatch.setattr(m, 'locked_membership', AsyncMock(return_value=S(circle=S(id=circle,plan='family'),membership=S(role='owner'))))
    monkeypatch.setattr(m, 'load_operation', AsyncMock(return_value=row))
    monkeypatch.setattr(m, 'authorize', AsyncMock())
    monkeypatch.setattr(m, 'runtime_seat_capacity', AsyncMock(return_value=4))
    monkeypatch.setattr(m, 'append_family_audit', AsyncMock())
    monkeypatch.setattr(m, 'notify', AsyncMock())
    monkeypatch.setattr(invites, '_pending_invite_count', AsyncMock(side_effect=lambda *a:state.invites))
    return m, db, membership, row, state, dict(actor=S(id=actor),circle_id=circle,operation_id=oid)


def test_full_family_undo_reclaims_own_reserved_seat(monkeypatch):
    from app.services.family_circle_plan_service import _active_seat_count
    m,db,member,row,state,args = undo_fixture(monkeypatch)
    assert state.active == 3 and run(_active_seat_count(db,args['circle_id'],'member')) == 4
    result=run(m.undo_removal(db,**args))
    assert result['restored'] and member.status == 'active' and member.ended_at is None
    assert state.active + int(member.status == 'active') == 4
    m.append_family_audit.assert_awaited_once()
    m.notify.assert_awaited_once()


@pytest.mark.parametrize('conflict',['active','invite','other_reservation'])
def test_real_capacity_conflicts_still_block(monkeypatch,conflict):
    m,db,member,row,state,args = undo_fixture(monkeypatch)
    if conflict=='active': state.active += 1
    if conflict=='invite': state.invites += 1
    if conflict=='other_reservation': state.reservations.append(uuid4())
    with pytest.raises(PermissionError,match='seat_capacity_changed'): run(m.undo_removal(db,**args))
    assert member.status == 'removed'
    m.append_family_audit.assert_not_awaited()


@pytest.mark.parametrize('invalid',['expired','consumed','wrong_seat','wrong_subject','wrong_circle','expires_during_work'])
def test_invalid_reservation_never_restores(monkeypatch,invalid):
    m,db,member,row,state,args = undo_fixture(monkeypatch)
    if invalid=='expired': row['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
    if invalid=='consumed': row['state']='undone'
    if invalid=='wrong_seat': row['details']['seat']='guardian'
    if invalid=='wrong_subject': member.user_id=uuid4()
    if invalid=='wrong_circle': member.circle_id=uuid4()
    if invalid=='expires_during_work': state.claim=False
    with pytest.raises(PermissionError): run(m.undo_removal(db,**args))
    assert member.status=='removed'
    m.append_family_audit.assert_not_awaited()


def test_other_removal_reservation_is_not_subtracted(monkeypatch):
    from app.services.family_circle_plan_service import _active_seat_count
    m,db,member,row,state,args=undo_fixture(monkeypatch)
    other=uuid4();state.reservations.append(other)
    assert run(_active_seat_count(db,args['circle_id'],'member',exclude_removal_id=row['id']))==4
    assert run(_active_seat_count(db,args['circle_id'],'member',exclude_removal_id=uuid4()))==5


def context(plan, seat, role='adult_member', **kw):
    consent=p.ConsentState({k:True for k in p.CONSENT_PURPOSES})
    return p.PermissionContext(actor_user_id='actor',actor_role=role,actor_seat=seat,plan=plan,
        entitlement=kw.pop('entitlement','active'),actor_consent=kw.pop('actor_consent',consent),
        target_user_id='target',target_role='adult_member',target_seat=kw.pop('target_seat',seat),
        target_consent=consent,**kw)


@pytest.mark.parametrize('plan',['trial','individual','family'])
def test_seeded_catalog_features_match_canonical_policy(plan):
    # Read seed literals only; never import or execute a migration.
    source=(ROOT/'migrations/versions/fc09_r2_plan_catalog.py').read_text(encoding='utf-8')
    block=source.split("('"+plan+"',",1)[1].split('TRUE,',1)[0]
    capacities,features=[json.loads(s) for s in re.findall(r"'(\{[^']+\})'::jsonb",block)]
    mutual=plan=='family';seat='member' if mutual else 'protected'
    assert features['mutual_visibility'] is mutual
    assert p.permission_decision(context(plan,seat,target_seat='member' if mutual else 'guardian'),p.ACTION_VIEW_LOCATION).allowed is mutual
    guardian='member' if mutual else 'guardian'
    assert p.permission_decision(context(plan,guardian),p.ACTION_PRODUCE_LOCATION).allowed is features['guardian_tracked']
    assert p.permission_decision(context(plan,seat),p.ACTION_PRODUCE_AI_PROFILE).allowed
    assert not p.permission_decision(context(plan,seat,'minor'),p.ACTION_PRODUCE_AI_PROFILE).allowed
    assert not p.permission_decision(context(plan,seat,'minor'),p.ACTION_PRODUCE_VOICE_DISTRESS).allowed
    assert features['behavioral_ai']==('all_adults' if mutual else 'protected_adult_only')
    assert not p.permission_decision(context(plan,seat,actor_consent=p.ConsentState()),p.ACTION_PRODUCE_AI_PROFILE).allowed
    assert not p.permission_decision(context(plan,seat,entitlement='lifeline'),p.ACTION_PRODUCE_AI_PROFILE).allowed
    assert p.permission_decision(context(plan,seat,entitlement='lifeline'),p.ACTION_TRIGGER_SOS).allowed is features['lifeline_supported']


@pytest.mark.parametrize('entitlement,consent,expected',[('active',True,True),('lifeline',True,False),('active',False,False)])
def test_runtime_uses_current_server_consent_and_entitlement(monkeypatch,entitlement,consent,expected):
    from app.services import family_circle_runtime_authority as r
    uid=uuid4();circle=S(id=uuid4(),plan='family')
    monkeypatch.setattr(r,'membership_snapshot',AsyncMock(return_value=S(circle=circle,membership=S(user_id=uid,role='adult_member',seat='member'))))
    monkeypatch.setattr(r,'_consent_state',AsyncMock(return_value=p.ConsentState({p.CONSENT_AI_BEHAVIORAL:consent})))
    monkeypatch.setattr(r,'resolve_entitlement',AsyncMock(return_value=S(permission_entitlement=entitlement)))
    result=run(r.runtime_decision(None,actor_user_id=uid,action=p.ACTION_PRODUCE_AI_PROFILE))
    assert result.canonical and result.allowed is expected
    # No client/catalog feature dictionary is an authorization input.
    assert 'features' not in p.PermissionContext.__dataclass_fields__


def test_catalog_capacity_is_runtime_authority_without_static_fallback():
    from app.services.family_circle_plan_service import runtime_seat_capacity
    row=dict(plan_key='family',display_name='Family',price_inr=999,billing_period='month',trial_days=None,
             seat_capacities={'member':3},feature_flags={'mutual_visibility':False},sort_order=1)
    db=S(execute=AsyncMock(return_value=S(mappings=lambda:S(first=lambda:row))))
    assert run(runtime_seat_capacity(db,'family','member'))==3
    db.execute.return_value=S(mappings=lambda:S(first=lambda:None))
    with pytest.raises(ValueError,match='unavailable'):run(runtime_seat_capacity(db,'family','member'))
