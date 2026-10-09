"""Offline Family GET and unpaid formation gate; no external services."""
import ast
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as S
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.models.family_circle import FamilyCircle, CircleMembership
from app.models.user import User
from app.services import family_circle_runtime_authority as runtime
from app.services import family_circle_entitlement_service as ent
from app.services import family_circle_invite_service as invites

ROOT = Path(__file__).resolve().parents[1]
class Rows:
    def __init__(self, rows=()): self.rows=list(rows); self.rowcount=1
    def first(self): return self.rows[0] if self.rows else None
    def scalar_one_or_none(self): return self.first()
    def scalar_one(self): return self.first()
    def mappings(self): return self
    def scalars(self): return self
    def all(self): return self.rows

class DB:
    def __init__(self, role='owner', state='payment_pending'):
        self.owner=S(id=uuid4(), date_of_birth=date(1990,1,1), is_active=True, full_name='Synthetic Owner')
        self.circle=FamilyCircle(id=uuid4(),owner_user_id=self.owner.id,plan='family',status='active')
        self.members=[CircleMembership(id=uuid4(),circle_id=self.circle.id,user_id=self.owner.id,role=role,seat='member',status='active')]
        self.users={self.owner.id:self.owner}; self.invite=None; self.state=state; self.queries=[]; self.pending=[]
    async def get(self, model, uid, **kw):
        if model is User: return self.users.get(uid)
        if model is FamilyCircle: return self.circle
        return next((m for m in self.members if m.id==uid),None)
    def add(self, obj): self.pending.append(obj)
    async def flush(self):
        self.members.extend(self.pending); self.pending=[]
    async def commit(self): pass
    async def execute(self, statement, params=None):
        sql=str(statement); self.queries.append(sql); params=params or {}
        if 'FROM family_circle_entitlements' in sql:
            return Rows([] if self.state is None else [dict(state=self.state,current_period_end=None,grace_until=None)])
        if 'FROM family_plan_catalog' in sql:
            return Rows([dict(plan_key='family',display_name='Family',price_inr=999,billing_period='month',trial_days=None,seat_capacities={'member':4},feature_flags={},sort_order=2)])
        if 'family_age18_transitions' in sql or 'family_consent_events' in sql or 'family_sharing_states' in sql: return Rows()
        if 'family_lifecycle_operations' in sql: return Rows([0])
        if sql.startswith('INSERT INTO family_circle_invites') or 'INSERT INTO family_circle_invites' in sql:
            self.invite=dict(params,status='pending',plan='family',circle_name='Synthetic',owner_name='Synthetic Owner'); return Rows()
        if 'FROM family_circle_invites' in sql:
            if 'count(' in sql.lower(): return Rows([int(bool(self.invite and self.invite['status']=='pending'))])
            if sql.strip().startswith('SELECT 1'): return Rows()
            return Rows([self.invite] if self.invite else [])
        if 'UPDATE family_circle_invites' in sql:
            if "status='accepted'" in sql: self.invite['status']='accepted'; return Rows([self.invite['id']])
            return Rows()
        if 'FROM circle_memberships' in sql:
            if 'count(' in sql.lower(): return Rows([sum(m.seat is not None for m in self.members)])
            if sql.strip().startswith('SELECT user_id'): return Rows([self.owner.id])
            values=statement.compile().params
            uid=values.get('user_id_1')
            ms=[m for m in self.members if uid is None or m.user_id==uid]
            if 'JOIN family_circles' in sql: return Rows([(m,self.circle) for m in ms])
            return Rows(ms)
        return Rows()


def setup(monkeypatch, role='owner', state='payment_pending'):
    db=DB(role,state)
    monkeypatch.setattr(invites,'append_family_audit',AsyncMock())
    from app.services import family_circle_notification_outbox as outbox
    monkeypatch.setattr(outbox,'enqueue_family_notifications',AsyncMock())
    return db


def endpoint(name):
    rel='app/api/family_circle_phase6.py' if name=='my_entitlement' else 'app/api/family_circle_runtime.py'
    node=next(n for n in ast.parse((ROOT/rel).read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
    node.decorator_list=[ast.Name(id='bounded_runtime_read',ctx=ast.Load())]
    node.args.defaults=[ast.Constant(value=None)]*len(node.args.defaults)
    for a in node.args.args: a.annotation=None
    ns=dict(vars(runtime)); ns['resolve_entitlement']=ent.resolve_entitlement
    from app.core import family_circle_permissions as permissions
    ns.update(vars(permissions)); ns['__name__']='local_family_endpoint'; ns['User']=User
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),rel,'exec'),ns)
    return ns[name]


@pytest.mark.parametrize('name',['my_entitlement','get_my_runtime_authority'])
def test_get_truthful_bounded_queries_no_redis_or_provider(monkeypatch,name):
    db=setup(monkeypatch)
    from app.services import redis_service
    def forbidden(*a,**kw): raise AssertionError('GET must not call Redis')
    monkeypatch.setattr(redis_service,'get_json',forbidden)
    monkeypatch.setattr(redis_service,'is_available',forbidden)
    result=asyncio.run(endpoint(name)(session=db,user=db.owner))
    assert (result['plan'],result['role'],result['seat'])==('family','owner','member')
    assert result.get('state',result.get('entitlement_state'))=='payment_pending'
    assert result['entitlement']=='lifeline' and result['payment_required']
    for key in ('can_produce_location','can_produce_ai','can_produce_voice','can_produce_wearable'): assert not result[key]
    if name=='my_entitlement': assert result['can_invite'] and result['gateway_enabled'] is False
    assert len(db.queries)<22
    assert not any('FOR UPDATE' in q or q.lstrip().startswith(('INSERT','UPDATE')) for q in db.queries)


@pytest.mark.parametrize('name',['my_entitlement','get_my_runtime_authority'])
def test_get_db_stall_times_out_and_loop_runs(monkeypatch,name):
    db=setup(monkeypatch)
    monkeypatch.setattr(runtime,'RUNTIME_READ_TIMEOUT_SECONDS',0.03)
    async def stall(*args,**kwargs): await asyncio.Event().wait()
    db.execute=stall
    async def run():
        task=asyncio.create_task(endpoint(name)(session=db,user=db.owner))
        await asyncio.sleep(0.005)
        assert not task.done()
        with pytest.raises(HTTPException) as exc: await asyncio.wait_for(task,0.3)
        assert exc.value.status_code==503
        assert runtime._READ_STATE.get() is None
    asyncio.run(run())


@pytest.mark.parametrize('role,allowed',[('owner',True),('co_admin',True),('adult_member',False),('minor',False)])
def test_unpaid_invite_and_join_real_service_path(monkeypatch,role,allowed):
    db=setup(monkeypatch,role)
    async def run():
        if not allowed:
            with pytest.raises(invites.FamilyInviteError): await invites.create_invite(db,actor=db.owner,requested_seat='member')
            return
        code,expiry,circle,seat,kind=await invites.create_invite(db,actor=db.owner,requested_seat='member')
        assert seat=='member' and kind=='adult'
        assert timedelta(hours=47,minutes=59)<expiry-datetime.now(timezone.utc)<=timedelta(hours=48)
        preview=await invites.preview_invite(db,code)
        assert preview.plan=='family' and preview.seat=='member'
        adult=S(id=uuid4(),date_of_birth=date(1991,1,1),is_active=True,full_name='Synthetic Adult')
        db.users[adult.id]=adult
        joined=await invites.accept_invite_for_user(db,code=code,new_user=adult)
        assert joined.seat=='member' and joined.role=='adult_member'
        assert len(db.members)==2 and db.invite['status']=='accepted'
        assert (await ent.resolve_entitlement(db,circle)).permission_entitlement=='lifeline'
        with pytest.raises(invites.FamilyInviteError): await invites.accept_invite_for_user(db,code=code,new_user=adult)
    asyncio.run(run())


@pytest.mark.parametrize('state',[None,'lifeline','unexpected'])
def test_missing_or_nonpending_entitlement_cannot_form(monkeypatch,state):
    db=setup(monkeypatch,state=state)
    with pytest.raises(invites.FamilyInviteError):
        asyncio.run(invites.create_invite(db,actor=db.owner,requested_seat='member'))


@pytest.mark.parametrize('reason',['full','expired','revoked','existing','minor'])
def test_invitation_restrictions(monkeypatch,reason):
    db=setup(monkeypatch)
    async def run():
        code,*_=await invites.create_invite(db,actor=db.owner,requested_seat='member')
        adult=S(id=uuid4(),date_of_birth=date(1991,1,1),is_active=True,full_name='Synthetic')
        db.users[adult.id]=adult
        if reason=='full':
            for _ in range(3): db.members.append(CircleMembership(id=uuid4(),user_id=uuid4(),circle_id=db.circle.id,seat='member',role='adult_member',status='active'))
            with pytest.raises(invites.FamilyInviteError): await invites.create_invite(db,actor=db.owner,requested_seat='member')
        if reason=='expired': db.invite['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
        if reason=='revoked': db.invite['status']='revoked'
        if reason=='existing': db.members.append(CircleMembership(id=uuid4(),user_id=adult.id,circle_id=uuid4(),seat='member',role='adult_member',status='active'))
        if reason=='minor': adult.date_of_birth=date(2015,1,1)
        with pytest.raises(ValueError): await invites.accept_invite_for_user(db,code=code,new_user=adult)
        assert db.invite['status']!='accepted'
    asyncio.run(run())


def test_read_cache_is_request_and_session_isolated(monkeypatch):
    db=setup(monkeypatch)
    async def run():
        handler=endpoint('get_my_runtime_authority')
        await handler(session=db,user=db.owner)
        db.state='paid_active'
        result=await handler(session=db,user=db.owner)
        assert result['entitlement']=='active'
        assert runtime._READ_STATE.get() is None
    asyncio.run(run())
