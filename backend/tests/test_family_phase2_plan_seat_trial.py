from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.family_circle_permissions import (
    PLAN_FAMILY,
    PLAN_INDIVIDUAL,
    PLAN_TRIAL,
    SEAT_GUARDIAN,
    SEAT_MEMBER,
    SEAT_PROTECTED,
)
from app.core.family_circle_roles import (
    CIRCLE_ROLE_ADULT_MEMBER,
    CIRCLE_ROLE_MINOR,
    CIRCLE_ROLE_OWNER,
)
from app.models.family_circle import CircleMembership, FamilyCircle, FamilyTrialClaim
from app.services.family_circle_plan_service import (
    CirclePlanError,
    TrialAlreadyUsedError,
    TRIAL_DURATION_DAYS,
    add_membership_with_seat,
    assert_seat_available,
    get_plan_shape,
    initialize_circle_plan,
    seat_capacity,
    trial_fingerprints,
    trial_window_is_active,
    validate_seat_for_membership,
)


def test_plan_shapes_match_locked_v1_capacity():
    assert get_plan_shape(PLAN_TRIAL).capacities == {SEAT_PROTECTED: 1, SEAT_GUARDIAN: 2}
    assert get_plan_shape(PLAN_INDIVIDUAL).capacities == {SEAT_PROTECTED: 1, SEAT_GUARDIAN: 2}
    assert get_plan_shape(PLAN_FAMILY).capacities == {SEAT_MEMBER: 4}
    assert seat_capacity(PLAN_TRIAL, SEAT_PROTECTED) == 1
    assert seat_capacity(PLAN_TRIAL, SEAT_GUARDIAN) == 2
    assert seat_capacity(PLAN_INDIVIDUAL, SEAT_PROTECTED) == 1
    assert seat_capacity(PLAN_INDIVIDUAL, SEAT_GUARDIAN) == 2
    assert seat_capacity(PLAN_FAMILY, SEAT_MEMBER) == 4


@pytest.mark.parametrize(
    "plan,seat",
    [
        (PLAN_TRIAL, SEAT_MEMBER),
        (PLAN_INDIVIDUAL, SEAT_MEMBER),
        (PLAN_FAMILY, SEAT_PROTECTED),
        (PLAN_FAMILY, SEAT_GUARDIAN),
        ("unknown", SEAT_MEMBER),
    ],
)
def test_invalid_plan_seat_pairs_fail_closed(plan, seat):
    with pytest.raises(CirclePlanError):
        seat_capacity(plan, seat)


def test_minor_cannot_take_guardian_seat_but_can_be_tracked():
    with pytest.raises(CirclePlanError, match="Minor"):
        validate_seat_for_membership(PLAN_TRIAL, SEAT_GUARDIAN, CIRCLE_ROLE_MINOR)
    assert validate_seat_for_membership(PLAN_TRIAL, SEAT_PROTECTED, CIRCLE_ROLE_MINOR) == SEAT_PROTECTED
    assert validate_seat_for_membership(PLAN_FAMILY, SEAT_MEMBER, CIRCLE_ROLE_MINOR) == SEAT_MEMBER


def test_trial_fingerprints_are_normalized_irreversible_and_stable():
    a = trial_fingerprints("+91 98765 43210", "device-ABC-12345")
    b = trial_fingerprints("9876543210", "device-ABC-12345")
    assert a == b
    assert len(a[0]) == 64 and len(a[1]) == 64
    assert "9876543210" not in a[0]
    assert "device-ABC-12345" not in a[1]


class _ScalarOne:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _ScalarMaybe:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ScalarsFirst:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _QueueSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.flush_count = 0
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        if not self.results:
            raise AssertionError("unexpected execute")
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flush_count += 1

    async def get(self, model, identity):
        for value in reversed(self.added):
            if isinstance(value, model) and getattr(value, "id", None) == identity:
                return value
        return None


def _circle(*, plan=None):
    return FamilyCircle(
        id=uuid.uuid4(),
        name="Test Circle",
        owner_user_id=uuid.uuid4(),
        status="active",
        plan=plan,
    )


def _owner_membership(circle: FamilyCircle):
    return CircleMembership(
        id=uuid.uuid4(),
        circle_id=circle.id,
        user_id=circle.owner_user_id,
        role=CIRCLE_ROLE_OWNER,
        seat=None,
        status="active",
        created_by_user_id=circle.owner_user_id,
    )


def test_trial_initialization_is_exactly_seven_days_and_collects_no_payment_state():
    circle = _circle(plan=None)
    owner = _owner_membership(circle)
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    # lock result, seated-count result, existing-trial-claim result
    session = _QueueSession([_ScalarOne(None), _ScalarOne(0), _ScalarsFirst(None)])

    asyncio.run(
        initialize_circle_plan(
            session,
            circle=circle,
            owner_membership=owner,
            plan=PLAN_TRIAL,
            owner_seat=SEAT_PROTECTED,
            phone="+919876543210",
            device_id="device-12345678",
            now=now,
        )
    )

    assert circle.plan == PLAN_TRIAL
    assert owner.seat == SEAT_PROTECTED
    assert circle.trial_started_at == now
    assert circle.trial_ends_at == now + timedelta(days=TRIAL_DURATION_DAYS)
    assert circle.trial_ends_at - circle.trial_started_at == timedelta(days=7)
    assert len(session.added) == 1
    claim = session.added[0]
    assert isinstance(claim, FamilyTrialClaim)
    assert claim.phone_fingerprint != "+919876543210"
    assert claim.device_fingerprint != "device-12345678"
    assert not hasattr(circle, "payment_method")
    assert not hasattr(claim, "payment_method")
    assert session.flush_count == 1


def test_second_trial_same_phone_or_device_is_refused_server_side():
    circle = _circle(plan=None)
    owner = _owner_membership(circle)
    existing = SimpleNamespace(circle_id=uuid.uuid4())
    session = _QueueSession([_ScalarOne(None), _ScalarOne(0), _ScalarsFirst(existing)])

    with pytest.raises(TrialAlreadyUsedError, match="already used"):
        asyncio.run(
            initialize_circle_plan(
                session,
                circle=circle,
                owner_membership=owner,
                plan=PLAN_TRIAL,
                owner_seat=SEAT_PROTECTED,
                phone="+919876543210",
                device_id="device-12345678",
            )
        )
    assert circle.plan is None
    assert owner.seat is None
    assert session.added == []
    assert session.flush_count == 0


@pytest.mark.parametrize(
    "plan,seat,current",
    [
        (PLAN_TRIAL, SEAT_PROTECTED, 1),   # second protected refused
        (PLAN_TRIAL, SEAT_GUARDIAN, 2),    # third guardian refused
        (PLAN_INDIVIDUAL, SEAT_PROTECTED, 1),
        (PLAN_INDIVIDUAL, SEAT_GUARDIAN, 2),
        (PLAN_FAMILY, SEAT_MEMBER, 4),      # fifth Family member refused
    ],
)
def test_capacity_refuses_overflow(plan, seat, current):
    circle = _circle(plan=plan)
    # lock is performed by add-member wrapper; assert_seat_available itself only counts.
    session = _QueueSession([_ScalarOne(current)])
    with pytest.raises(CirclePlanError, match="capacity is full"):
        asyncio.run(
            assert_seat_available(
                session,
                circle=circle,
                seat=seat,
                role=CIRCLE_ROLE_ADULT_MEMBER,
            )
        )


@pytest.mark.parametrize(
    "plan,seat,current",
    [
        (PLAN_TRIAL, SEAT_PROTECTED, 0),
        (PLAN_TRIAL, SEAT_GUARDIAN, 1),
        (PLAN_INDIVIDUAL, SEAT_GUARDIAN, 1),
        (PLAN_FAMILY, SEAT_MEMBER, 3),
    ],
)
def test_capacity_accepts_available_seat(plan, seat, current):
    circle = _circle(plan=plan)
    session = _QueueSession([_ScalarOne(current)])
    assert (
        asyncio.run(
            assert_seat_available(
                session,
                circle=circle,
                seat=seat,
                role=CIRCLE_ROLE_ADULT_MEMBER,
            )
        )
        == seat
    )


def test_paid_plan_selection_does_not_fake_payment_or_create_trial_claim():
    for plan, seat in [(PLAN_INDIVIDUAL, SEAT_GUARDIAN), (PLAN_FAMILY, SEAT_MEMBER)]:
        circle = _circle(plan=None)
        owner = _owner_membership(circle)
        session = _QueueSession([_ScalarOne(None), _ScalarOne(0)])
        asyncio.run(
            initialize_circle_plan(
                session,
                circle=circle,
                owner_membership=owner,
                plan=plan,
                owner_seat=seat,
            )
        )
        assert circle.plan == plan
        assert owner.seat == seat
        assert circle.trial_started_at is None
        assert circle.trial_ends_at is None
        assert session.added == []
        assert session.flush_count == 1



def test_add_membership_with_seat_is_canonical_capacity_path():
    circle = _circle(plan=PLAN_TRIAL)
    user = SimpleNamespace(id=uuid.uuid4(), date_of_birth=date(1990, 1, 1))
    # circle row lock, guardian seat count=1 (one slot remains), no existing membership
    session = _QueueSession([_ScalarOne(None), _ScalarOne(1), _ScalarMaybe(None)])
    identity = asyncio.run(
        add_membership_with_seat(
            session,
            circle=circle,
            user=user,
            role=CIRCLE_ROLE_ADULT_MEMBER,
            seat=SEAT_GUARDIAN,
            created_by_user_id=circle.owner_user_id,
        )
    )
    membership = next(value for value in session.added if isinstance(value, CircleMembership))
    assert identity.user_id == user.id
    assert membership.seat == SEAT_GUARDIAN
    assert session.flush_count == 2


def test_add_membership_with_seat_refuses_full_capacity_before_membership_insert():
    circle = _circle(plan=PLAN_FAMILY)
    user = SimpleNamespace(id=uuid.uuid4(), date_of_birth=date(1990, 1, 1))
    # row lock then count=4; add_membership must never be reached.
    session = _QueueSession([_ScalarOne(None), _ScalarOne(4)])
    with pytest.raises(CirclePlanError, match="capacity is full"):
        asyncio.run(
            add_membership_with_seat(
                session,
                circle=circle,
                user=user,
                role=CIRCLE_ROLE_ADULT_MEMBER,
                seat=SEAT_MEMBER,
                created_by_user_id=circle.owner_user_id,
            )
        )
    assert session.added == []
    assert session.flush_count == 0

def test_trial_window_has_exact_end_boundary():
    circle = _circle(plan=PLAN_TRIAL)
    start = datetime(2026, 9, 29, tzinfo=timezone.utc)
    circle.trial_started_at = start
    circle.trial_ends_at = start + timedelta(days=7)
    assert trial_window_is_active(circle, now=start)
    assert trial_window_is_active(circle, now=circle.trial_ends_at - timedelta(microseconds=1))
    assert not trial_window_is_active(circle, now=circle.trial_ends_at)


def test_model_ddl_contains_plan_seat_and_trial_claim_uniqueness():
    dialect = postgresql.dialect()
    circle_sql = str(CreateTable(FamilyCircle.__table__).compile(dialect=dialect))
    member_sql = str(CreateTable(CircleMembership.__table__).compile(dialect=dialect))
    claim_sql = str(CreateTable(FamilyTrialClaim.__table__).compile(dialect=dialect))
    claim_indexes = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect))
        for index in FamilyTrialClaim.__table__.indexes
    )
    assert "plan" in circle_sql and "trial_started_at" in circle_sql and "trial_ends_at" in circle_sql
    assert "trial" in circle_sql and "individual" in circle_sql and "family" in circle_sql
    assert "seat" in member_sql and "protected" in member_sql and "guardian" in member_sql and "member" in member_sql
    assert "CREATE TABLE family_trial_claims" in claim_sql
    assert "uq_family_trial_claim_phone" in claim_indexes
    assert "uq_family_trial_claim_device" in claim_indexes


def test_runtime_migration_is_additive_idempotent_and_commits(monkeypatch):
    import app.migrations.fc03_circle_plan_seat_trial as migration

    class _RecordingSession:
        def __init__(self):
            self.sql = []
            self.commits = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            self.sql.append(str(statement))

        async def commit(self):
            self.commits += 1

    recorder = _RecordingSession()

    def fake_async_session():
        return recorder

    import sys
    import types
    fake_db_session = types.ModuleType("app.db.session")
    fake_db_session.async_session = fake_async_session
    monkeypatch.setitem(sys.modules, "app.db.session", fake_db_session)

    asyncio.run(migration.ensure_circle_plan_seat_trial_schema())
    sql = "\n".join(recorder.sql)
    assert "ADD COLUMN IF NOT EXISTS plan" in sql
    assert "ADD COLUMN IF NOT EXISTS seat" in sql
    assert "CREATE TABLE IF NOT EXISTS family_trial_claims" in sql
    assert "uq_family_trial_claim_phone" in sql
    assert "uq_family_trial_claim_device" in sql
    assert "member_subscriptions" not in sql
    assert "guardian_relationships" not in sql
    assert "relationships" not in sql
    assert "DROP TABLE" not in sql
    assert recorder.commits == 1


def test_server_wires_fc03_after_fc02_and_before_user_seed():
    from pathlib import Path

    server_text = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert server_text.count("ensure_circle_plan_seat_trial_schema") == 2
    fc02 = server_text.index("await ensure_family_circle_authority_tables()")
    fc03 = server_text.index("await ensure_circle_plan_seat_trial_schema()")
    seed = server_text.index("from app.services.user_seed import seed_operational_accounts")
    assert fc02 < fc03 < seed
    assert "[FC-03] required startup DDL failed; refusing startup" in server_text


def test_alembic_chains_from_fc02_and_never_touches_legacy_subscription_tables():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "migrations" / "versions" / "fc03_circle_plan_seat_trial.py").read_text(encoding="utf-8")
    assert 'revision = "fc03_circle_plan_seat_trial"' in text
    assert 'down_revision = "fc02_family_circle_authority"' in text
    assert '"family_trial_claims"' in text
    assert 'op.add_column("family_circles"' in text
    assert 'op.add_column("circle_memberships"' in text
    assert "member_subscriptions" not in text
    assert "guardian_relationships" not in text
