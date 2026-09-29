from __future__ import annotations

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.family_circle_roles import (
    CIRCLE_ROLE_ADULT_MEMBER,
    CIRCLE_ROLE_CO_ADMIN,
    CIRCLE_ROLE_MINOR,
    CIRCLE_ROLE_OWNER,
    CircleRoleError,
    role_for_date_of_birth,
)
from app.models.family_circle import CircleMembership, FamilyCircle
from app.services.family_circle_service import (
    CircleAuthorityError,
    add_membership,
    create_circle,
)


TODAY_ADULT = date(2026, 9, 29)


def test_circle_roles_are_separate_and_age_derived(monkeypatch):
    # age_policy uses current UTC date by default; pass dates safely far from boundary.
    adult_dob = date(2000, 1, 1)
    minor_dob = date(2015, 1, 1)

    assert role_for_date_of_birth(adult_dob, CIRCLE_ROLE_OWNER) == CIRCLE_ROLE_OWNER
    assert role_for_date_of_birth(adult_dob, CIRCLE_ROLE_CO_ADMIN) == CIRCLE_ROLE_CO_ADMIN
    assert role_for_date_of_birth(adult_dob, CIRCLE_ROLE_ADULT_MEMBER) == CIRCLE_ROLE_ADULT_MEMBER
    assert role_for_date_of_birth(minor_dob, CIRCLE_ROLE_MINOR) == CIRCLE_ROLE_MINOR

    with pytest.raises(CircleRoleError):
        role_for_date_of_birth(minor_dob, CIRCLE_ROLE_ADULT_MEMBER)
    with pytest.raises(CircleRoleError):
        role_for_date_of_birth(adult_dob, CIRCLE_ROLE_MINOR)
    with pytest.raises(CircleRoleError):
        role_for_date_of_birth(None, CIRCLE_ROLE_ADULT_MEMBER)


def test_model_ddl_has_additive_tables_and_required_constraints():
    dialect = postgresql.dialect()
    circle_sql = str(CreateTable(FamilyCircle.__table__).compile(dialect=dialect))
    membership_sql = str(CreateTable(CircleMembership.__table__).compile(dialect=dialect))
    index_sql = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect))
        for index in CircleMembership.__table__.indexes
    )

    assert "CREATE TABLE family_circles" in circle_sql
    assert "REFERENCES users" in circle_sql
    assert "CREATE TABLE circle_memberships" in membership_sql
    assert "owner" in membership_sql and "co_admin" in membership_sql
    assert "minor" in membership_sql and "adult_member" in membership_sql
    assert "uq_circle_membership_one_active_circle_per_user" in index_sql
    assert "uq_circle_membership_one_active_owner" in index_sql
    assert "uq_circle_membership_one_active_co_admin" in index_sql
    assert "WHERE status = 'active'" in index_sql


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.flush_count = 0

    async def execute(self, _statement):
        return _ScalarResult(self.existing)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flush_count += 1


@pytest.mark.parametrize("dob", [date(2010, 1, 1), None])
def test_minor_or_missing_dob_cannot_create_circle(dob):
    session = _FakeSession()
    owner = SimpleNamespace(id=uuid.uuid4(), date_of_birth=dob)

    with pytest.raises(CircleAuthorityError):
        asyncio.run(create_circle(session, owner))

    assert session.added == []
    assert session.flush_count == 0


def test_adult_create_circle_preserves_existing_user_id_and_creates_owner_membership():
    session = _FakeSession(existing=None)
    owner_id = uuid.uuid4()
    owner = SimpleNamespace(id=owner_id, date_of_birth=date(1990, 5, 5))

    identity = asyncio.run(create_circle(session, owner, name="  Pingale Family  "))

    assert identity.user_id == owner_id
    assert identity.role == CIRCLE_ROLE_OWNER
    assert len(session.added) == 2
    circle, membership = session.added
    assert isinstance(circle, FamilyCircle)
    assert isinstance(membership, CircleMembership)
    assert circle.owner_user_id == owner_id
    assert circle.name == "Pingale Family"
    assert membership.user_id == owner_id
    assert membership.circle_id == circle.id == identity.circle_id
    assert membership.role == CIRCLE_ROLE_OWNER
    assert session.flush_count == 1


def test_existing_active_membership_blocks_second_circle():
    existing = SimpleNamespace(id=uuid.uuid4())
    session = _FakeSession(existing=existing)
    owner = SimpleNamespace(id=uuid.uuid4(), date_of_birth=date(1990, 1, 1))

    with pytest.raises(CircleAuthorityError, match="already belongs"):
        asyncio.run(create_circle(session, owner))

    assert session.added == []


def test_add_membership_enforces_age_role_and_never_creates_second_owner():
    circle_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    adult_session = _FakeSession(existing=None)
    adult = SimpleNamespace(id=uuid.uuid4(), date_of_birth=date(1995, 1, 1))
    identity = asyncio.run(
        add_membership(
            adult_session,
            circle_id=circle_id,
            user=adult,
            role=CIRCLE_ROLE_CO_ADMIN,
            created_by_user_id=actor_id,
        )
    )
    assert identity.role == CIRCLE_ROLE_CO_ADMIN
    assert adult_session.added[0].user_id == adult.id

    minor_session = _FakeSession(existing=None)
    minor = SimpleNamespace(id=uuid.uuid4(), date_of_birth=date(2014, 1, 1))
    identity = asyncio.run(
        add_membership(
            minor_session,
            circle_id=circle_id,
            user=minor,
            role=CIRCLE_ROLE_MINOR,
            created_by_user_id=actor_id,
        )
    )
    assert identity.role == CIRCLE_ROLE_MINOR

    wrong_minor_session = _FakeSession(existing=None)
    with pytest.raises(CircleAuthorityError):
        asyncio.run(
            add_membership(
                wrong_minor_session,
                circle_id=circle_id,
                user=minor,
                role=CIRCLE_ROLE_ADULT_MEMBER,
                created_by_user_id=actor_id,
            )
        )

    owner_session = _FakeSession(existing=None)
    with pytest.raises(CircleAuthorityError, match="ownership transfer"):
        asyncio.run(
            add_membership(
                owner_session,
                circle_id=circle_id,
                user=adult,
                role=CIRCLE_ROLE_OWNER,
                created_by_user_id=actor_id,
            )
        )


def test_phase1b_is_additive_not_legacy_replacement():
    # Regression guard: Circle authority must coexist with legacy relationship systems.
    from app.models.guardian_network import GuardianInvite, GuardianRelationship
    from app.models.relationship import Relationship
    from app.models.user import User

    assert User.__tablename__ == "users"
    assert Relationship.__tablename__ == "relationships"
    assert GuardianRelationship.__tablename__ == "guardian_relationships"
    assert GuardianInvite.__tablename__ == "guardian_invites"
    assert FamilyCircle.__tablename__ == "family_circles"
    assert CircleMembership.__tablename__ == "circle_memberships"



def test_runtime_migration_is_additive_idempotent_and_commits(monkeypatch):
    import app.migrations.fc02_family_circle_authority as migration

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

    asyncio.run(migration.ensure_family_circle_authority_tables())

    sql = "\n".join(recorder.sql)
    assert "CREATE TABLE IF NOT EXISTS family_circles" in sql
    assert "CREATE TABLE IF NOT EXISTS circle_memberships" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_circle_membership_one_active_circle_per_user" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_circle_membership_one_active_owner" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_circle_membership_one_active_co_admin" in sql
    assert "ALTER TABLE users" not in sql
    assert "DROP TABLE" not in sql
    assert "guardian_relationships" not in sql
    assert "relationships" not in sql
    assert recorder.commits == 1


def test_server_wires_fc02_after_fc01_and_before_user_seed():
    from pathlib import Path

    server_text = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert server_text.count("ensure_family_circle_authority_tables") == 2  # import + await
    fc01 = server_text.index("await ensure_user_date_of_birth_column()")
    fc02 = server_text.index("await ensure_family_circle_authority_tables()")
    user_seed = server_text.index("from app.services.user_seed import seed_operational_accounts")
    assert fc01 < fc02 < user_seed
    assert "[FC-02] required startup DDL failed; refusing startup" in server_text



def test_alembic_recordkeeping_migration_chains_from_fc01_and_is_additive():
    from pathlib import Path

    migration = (Path(__file__).resolve().parents[1] / "migrations" / "versions" / "fc02_family_circle_authority.py").read_text(encoding="utf-8")
    assert 'revision = "fc02_family_circle_authority"' in migration
    assert 'down_revision = "fc01_user_date_of_birth"' in migration
    assert 'op.create_table(\n        "family_circles"' in migration
    assert 'op.create_table(\n        "circle_memberships"' in migration
    assert 'op.alter_column("users"' not in migration
    assert 'op.drop_table("relationships")' not in migration
    assert 'op.drop_table("guardian_relationships")' not in migration
