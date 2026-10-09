"""Offline creator transaction regression: real ORM INSERTs, SQLite memory only.
PostgreSQL concurrency/transaction acceptance remains a staging validation step.
"""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import MetaData, Table, Column, Uuid, create_engine, event, select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.family_circle import FamilyCircle, CircleMembership, FamilyTrialClaim
from app.services import family_circle_service as authority
from app.services import family_circle_onboarding_service as onboarding
from app.services import family_circle_plan_service as plans


class MemoryTransaction:
    def __init__(self, monkeypatch):
        self.engine = create_engine('sqlite:///:memory:')
        event.listen(self.engine, 'connect', lambda connection, _: connection.execute('PRAGMA foreign_keys=ON'))
        metadata = MetaData()
        self.users = Table('users', metadata, Column('id', Uuid, primary_key=True))
        for model in (FamilyCircle, CircleMembership, FamilyTrialClaim):
            model.__table__.to_metadata(metadata)
        metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = SimpleNamespace(id=uuid4(), date_of_birth=date(1990, 1, 1), phone='+919000000001', role='woman')
        self.db.execute(self.users.insert().values(id=self.user.id))
        self.inserts = []
        self.flushes = []
        event.listen(self.engine, 'before_cursor_execute', self.capture)
        # Only the catalog transport and unrelated legal/entitlement writes are faked.
        # Creator, plan initialization, trial claim, membership queries and flushes are real.
        async def catalog(_session, plan):
            return plans.get_plan_shape(plan)
        monkeypatch.setattr(plans, 'get_runtime_plan_shape', catalog)
        monkeypatch.setattr(onboarding, 'seed_entitlement_state', AsyncMock())
        monkeypatch.setattr(onboarding, 'record_legal_acceptance', AsyncMock())

    def capture(self, connection, cursor, statement, parameters, context, many):
        if statement.startswith('INSERT INTO '):
            self.inserts.append(statement.split()[2])

    async def execute(self, statement, params=None):
        return self.db.execute(statement, params or {})

    async def get(self, model, identity):
        return self.db.get(model, identity)

    def add(self, obj):
        self.db.add(obj)

    async def flush(self):
        self.flushes.append([(type(obj).__name__, getattr(obj, 'plan', None), getattr(obj, 'seat', None)) for obj in self.db.new])
        self.db.flush()

    def count(self, model):
        return self.db.scalar(select(func.count()).select_from(model))

    def close(self):
        self.db.rollback()
        self.db.close()
        self.engine.dispose()


def create(tx, plan='family', seat='member'):
    return asyncio.run(onboarding.create_creator_circle(tx, user=tx.user, plan=plan, seat=seat,
        device_id='synthetic-creator-installation', circle_name='Synthetic Circle', legal_accepted=True))


@pytest.mark.parametrize('plan,seat', [('family','member'),('trial','protected'),('trial','guardian'),('individual','protected'),('individual','guardian')])
def test_real_creator_sequence_and_completed_retry(monkeypatch, plan, seat):
    tx = MemoryTransaction(monkeypatch)
    try:
        result = create(tx, plan, seat)
        assert result.has_circle and result.role == 'owner'
        assert result.plan == plan and result.seat == seat
        assert tx.inserts[:2] == ['family_circles', 'circle_memberships']
        assert tx.flushes[0] == [('FamilyCircle', plan, None)]
        assert tx.flushes[1] == [('CircleMembership', None, seat)]
        assert tx.count(FamilyCircle) == tx.count(CircleMembership) == 1
        member = tx.db.scalars(select(CircleMembership)).one()
        assert member.user_id == tx.user.id and member.role == 'owner'
        assert tx.user.role == 'woman'
        circle = tx.db.get(FamilyCircle, result.circle_id)
        before = (circle.trial_started_at, circle.trial_ends_at, len(tx.inserts), len(tx.flushes))
        repeated = create(tx, plan, seat)
        assert repeated.circle_id == result.circle_id
        assert before == (circle.trial_started_at, circle.trial_ends_at, len(tx.inserts), len(tx.flushes))
        assert tx.count(CircleMembership) == 1
        onboarding.seed_entitlement_state.assert_awaited_once()
        onboarding.record_legal_acceptance.assert_awaited_once()
        if plan == 'trial':
            assert circle.trial_ends_at - circle.trial_started_at == timedelta(days=7)
            assert tx.count(FamilyTrialClaim) == 1
        else:
            assert tx.count(FamilyTrialClaim) == 0 and result.payment_required
    finally:
        tx.close()


def test_minor_denied_before_insert(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        tx.user.date_of_birth = date(2015, 1, 1)
        with pytest.raises(onboarding.FamilyOnboardingError, match='under 18'):
            create(tx)
        assert not tx.inserts and not tx.flushes
    finally:
        tx.close()


def test_existing_membership_blocks_different_plan(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        create(tx)
        with pytest.raises(onboarding.FamilyOnboardingError, match='already belongs'):
            create(tx, 'individual', 'protected')
        assert tx.count(FamilyCircle) == tx.count(CircleMembership) == 1
    finally:
        tx.close()


def test_parent_and_member_roll_back_on_later_failure(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        monkeypatch.setattr(onboarding, 'seed_entitlement_state', AsyncMock(side_effect=RuntimeError('synthetic failure')))
        with pytest.raises(RuntimeError, match='synthetic failure'):
            create(tx)
        tx.db.rollback()
        assert tx.count(FamilyCircle) == tx.count(CircleMembership) == 0
    finally:
        tx.close()


def test_initial_fields_require_exact_creator_state(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        identity = asyncio.run(authority.create_circle(tx, tx.user, plan='family', owner_seat='member'))
        circle = tx.db.get(FamilyCircle, identity.circle_id)
        member = tx.db.get(CircleMembership, identity.membership_id)
        with pytest.raises(plans.CirclePlanError, match='already been initialized'):
            asyncio.run(plans.initialize_circle_plan(tx, circle=circle, owner_membership=member, plan='family', owner_seat='member'))
        with pytest.raises(plans.CirclePlanError, match='does not match'):
            asyncio.run(plans.initialize_circle_plan(tx, circle=circle, owner_membership=member, plan='individual', owner_seat='protected', creator_fields_initialized=True))
    finally:
        tx.close()


def test_integrity_diagnostic_logs_identifier_only(monkeypatch):
    logged = []
    monkeypatch.setattr(authority.logger, 'warning', lambda *args: logged.append(args))
    original = RuntimeError('PRIVATE payload must never be logged')
    original.__cause__ = RuntimeError('PRIVATE')
    original.__cause__.constraint_name = 'circle_memberships_circle_id_fkey'
    async def fail():
        raise IntegrityError('PRIVATE SQL', {'phone': 'PRIVATE'}, original)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)), add=lambda obj: None, flush=fail)
    user = SimpleNamespace(id=uuid4(), date_of_birth=date(1990, 1, 1))
    with pytest.raises(authority.CircleAuthorityError, match='membership conflict'):
        asyncio.run(authority.create_circle(session, user))
    assert logged == [('Family Circle create conflict: exception=%s constraint=%s', 'RuntimeError', 'circle_memberships_circle_id_fkey')]
    assert 'PRIVATE' not in str(logged)


def test_original_combined_flush_reproduces_fk_failure_even_with_plan_seat(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        circle = FamilyCircle(id=uuid4(), owner_user_id=tx.user.id, status='active', plan='family')
        member = CircleMembership(id=uuid4(), circle_id=circle.id, user_id=tx.user.id,
            role='owner', status='active', seat='member', created_by_user_id=tx.user.id)
        tx.db.add_all([circle, member])
        with pytest.raises(IntegrityError, match='FOREIGN KEY constraint failed'):
            tx.db.flush()
        assert tx.inserts[0] == 'circle_memberships'
    finally:
        tx.close()


def test_preseated_creator_does_not_exempt_other_members(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        identity = asyncio.run(authority.create_circle(tx, tx.user, plan='family', owner_seat='member'))
        circle = tx.db.get(FamilyCircle, identity.circle_id)
        member = tx.db.get(CircleMembership, identity.membership_id)
        queries = []
        async def execute(statement, params=None):
            queries.append(statement)
            return SimpleNamespace(scalar_one=lambda: 1)
        tx.execute = execute
        with pytest.raises(plans.CirclePlanError, match='already has seat assignments'):
            asyncio.run(plans.initialize_circle_plan(tx, circle=circle, owner_membership=member,
                plan='family', owner_seat='member', creator_fields_initialized=True))
        query = queries[-1].compile()
        assert 'circle_memberships.id !=' in str(query)
        assert member.id in query.params.values()
    finally:
        tx.close()


def test_missing_runtime_catalog_fails_before_any_insert(monkeypatch):
    tx = MemoryTransaction(monkeypatch)
    try:
        monkeypatch.setattr(plans, 'get_runtime_plan_shape', AsyncMock(side_effect=plans.CirclePlanError('catalog unavailable')))
        with pytest.raises(onboarding.FamilyOnboardingError, match='catalog unavailable'):
            create(tx)
        assert not tx.inserts and not tx.flushes
    finally:
        tx.close()
