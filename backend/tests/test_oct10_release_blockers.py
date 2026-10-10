"""No-network/no-DB behavioral tests against the actual Python function AST."""
import ast
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def load_function(relative, name, namespace):
    original = ast.parse((ROOT / relative).read_text(encoding='utf8'))
    fn = next(n for n in original.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)
    fn.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),fn],type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace)
    exec(compile(module, str(ROOT / relative), 'exec'),scope)
    return scope[name]


class FamilyInviteError(Exception): pass


class Cursor:
    def __init__(self, row=None): self.row=row
    def scalar_one_or_none(self): return self.row
    def mappings(self): return self
    def all(self): return self.row


class Session:
    def __init__(self, value=None): self.value=value;self.calls=[]
    async def execute(self, statement, params):
        self.calls.append((str(statement),params))
        return Cursor(self.value)


def service_scope(role='owner'):
    circle=SimpleNamespace(id=uuid.uuid4())
    return {
        '_load_circle_and_actor':AsyncMock(return_value=(circle, SimpleNamespace(role=role))),
        'FamilyInviteError':FamilyInviteError,
        'datetime':datetime, 'timezone':timezone,
        'text':lambda sql:sql,
        'append_family_audit':AsyncMock(),
        '_expire_pending_invites':AsyncMock(),
    },circle


def test_pending_cancel_scope_and_no_member_delete():
    ns,circle=service_scope()
    fn=load_function('app/services/family_circle_invite_service.py','revoke_pending_invite_by_id',ns)
    invite=uuid.uuid4();session=Session(value=invite)
    assert asyncio.run(fn(session,actor=SimpleNamespace(id=uuid.uuid4()),invite_id=invite)) is True
    sql,args=session.calls[0]
    assert "status='pending'" in sql and 'circle_id=:circle_id' in sql
    assert args['circle_id']==circle.id and args['id']==invite
    assert 'circle_memberships' not in sql
    ns['append_family_audit'].assert_awaited_once()


def test_accepted_or_revoked_invite_cannot_be_revoked_again():
    ns,_=service_scope()
    fn=load_function('app/services/family_circle_invite_service.py','revoke_pending_invite_by_id',ns)
    assert asyncio.run(fn(Session(value=None),actor=SimpleNamespace(id=uuid.uuid4()),invite_id=uuid.uuid4())) is False
    ns['append_family_audit'].assert_not_awaited()


def test_non_admin_cannot_list_or_cancel():
    ns,_=service_scope('adult_member')
    revoke=load_function('app/services/family_circle_invite_service.py','revoke_pending_invite_by_id',ns)
    listing=load_function('app/services/family_circle_invite_service.py','list_pending_invites',ns)
    with pytest.raises(FamilyInviteError,match='Owner or Co-Admin'):
        asyncio.run(revoke(Session(),actor=SimpleNamespace(id=uuid.uuid4()),invite_id=uuid.uuid4()))
    with pytest.raises(FamilyInviteError,match='Owner or Co-Admin'):
        asyncio.run(listing(Session(),actor=SimpleNamespace(id=uuid.uuid4())))


def test_pending_list_has_no_code_hash_or_private_identifiers():
    ns,circle=service_scope()
    created=datetime.now(timezone.utc)
    invite={'id':uuid.uuid4(),'seat':'member','invitee_kind':'adult',
            'created_at':created,'expires_at':created+timedelta(hours=48),'code_hash':'DO_NOT_LEAK'}
    fn=load_function('app/services/family_circle_invite_service.py','list_pending_invites',ns)
    session=Session(value=[invite])
    result=asyncio.run(fn(session,actor=SimpleNamespace(id=uuid.uuid4())))
    assert result[0]['id']==str(invite['id']) and 'code_hash' not in result[0]
    assert set(result[0])=={'id','seat','invitee_kind','created_at','expires_at'}
    sql,params=session.calls[0]
    assert "status='pending'" in sql and 'circle_id=:circle_id' in sql
    assert params['circle_id']==circle.id


class Column:
    def __eq__(self,other):return True


class FakeEntity:
    id=Column();user_id=Column();circle_id=Column();status=Column();full_name=Column()


class Query:
    def join(self,*args):return self
    def where(self,*args):return self


def roster_scope(membership):
    return {'Depends': lambda _: None,'get_current_user':None,'get_db_session':None,
            'get_active_membership':AsyncMock(return_value=membership),'HTTPException':HTTPException,
            'FamilyCircle':FakeEntity, 'CircleMembership':FakeEntity, 'User':FakeEntity,
            'select': lambda *_:Query()}


def test_roster_rejects_no_membership_without_database_lookup():
    scope=roster_scope(None)
    fn=load_function('app/api/family_circle_onboarding.py','family_circle_visible_members',scope)
    with pytest.raises(HTTPException) as err:
        asyncio.run(fn(user=SimpleNamespace(id=uuid.uuid4()),session=SimpleNamespace()))
    assert err.value.status_code==404


def test_roster_returns_names_roles_and_seats_but_not_phone_location():
    circle_id=uuid.uuid4();membership=SimpleNamespace(circle_id=circle_id)
    scope=roster_scope(membership)
    class RosterSession:
        async def get(self,table,cid):return SimpleNamespace(plan='family')
        async def execute(self,query):return Cursor([(SimpleNamespace(role='adult_member',seat='member'),SimpleNamespace(id=uuid.uuid4(),full_name='Synthetic User',phone='PRIVATE'))])
    fn=load_function('app/api/family_circle_onboarding.py','family_circle_visible_members',scope)
    data=asyncio.run(fn(user=SimpleNamespace(id=uuid.uuid4()),session=RosterSession()))
    result=data['members'][0]
    assert set(result)=={'user_id','name','role','seat'}
    assert result['name']=='Synthetic User' and result['seat']=='member'
