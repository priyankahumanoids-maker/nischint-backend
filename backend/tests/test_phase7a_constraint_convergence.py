"""Source/planner tests only. No PostgreSQL, Alembic runner or engine imports."""
import ast
import copy
import re
from pathlib import Path

import pytest

from app.migrations import family_constraint_compat as compat
from app.migrations.fc04_family_consent_authority import _DDL
from app.migrations.fc06_family_entitlement_lifecycle_audit import DDL

ROOT = Path(__file__).resolve().parents[1]

# Explicit inventory: changes to the canonical DDL must update this contract.
EXPECTED = {
    'family_consent_events': ('id', ['subject_user_id', 'actor_user_id'],
        ['ck_family_consent_event_purpose', 'ck_family_consent_event_state'], []),
    'family_sharing_states': ('user_id', ['user_id'], ['ck_family_sharing_pause_mode'], []),
    'family_circle_entitlements': ('circle_id', ['circle_id'],
        ['ck_family_entitlement_state', 'ck_family_entitlement_pending_plan'], []),
    'family_billing_events': ('id', ['circle_id'], [], ['uq_family_billing_provider_event']),
    'family_circle_audit_log': ('id', ['circle_id', 'actor_user_id', 'subject_user_id'], [],
        ['family_circle_audit_log_event_key_key']),
    'family_location_view_log': ('id', ['circle_id', 'viewer_user_id', 'subject_user_id'],
        ['ck_family_location_view_kind', 'ck_family_location_viewer_kind'], []),
    'family_notification_outbox': ('id', ['circle_id', 'recipient_user_id'], [],
        ['family_notification_outbox_event_key_key']),
    'family_age18_transitions': ('user_id', ['user_id', 'circle_id'], [], []),
}


def manifest():
    return compat.schema_manifest(_DDL) + compat.schema_manifest(DDL)


def test_every_required_constraint_is_explicitly_enumerated():
    tables = manifest()
    assert {t.name for t in tables} == set(EXPECTED)
    assert sum(len(t.constraints) for t in tables) == 33
    assert sum(len(t.indexes) for t in tables) == 9
    for table in tables:
        pk, fks, checks, uniques = EXPECTED[table.name]
        assert {c.name for c in table.constraints} == {
            table.name + '_pkey', *[table.name + '_' + col + '_fkey' for col in fks], *checks, *uniques,
        }
        assert next(c for c in table.constraints if c.name.endswith('_pkey')).columns == (pk,)
        for constraint in table.constraints:
            assert constraint.definition in table.create or constraint.columns or constraint.definition.startswith('UNIQUE')


def test_nullability_defaults_and_additive_columns_come_from_fresh_ddl():
    tables = {t.name: t for t in manifest()}
    assert 'next_attempt_at' in tables['family_notification_outbox'].additions
    assert 'NOT NULL DEFAULT NOW()' in tables['family_notification_outbox'].columns['next_attempt_at']
    assert 'NOT NULL' not in tables['family_location_view_log'].columns['viewer_user_id']
    assert 'NOT NULL' in tables['family_location_view_log'].columns['subject_user_id']
    assert tables['family_circle_audit_log'].constraints[1].delete_action == 'r'
    assert next(c for c in tables['family_location_view_log'].constraints if c.columns == ('viewer_user_id',)).delete_action == 'n'
    assert 'WHERE event_key IS NOT NULL' in tables['family_circle_audit_log'].indexes['uq_family_audit_event_key']
    assert 'WHERE' not in tables['family_circle_audit_log'].indexes['uq_family_audit_event_key_all']


def row(kind='c', **changes):
    return dict(dict(name='required', kind=kind, columns=['state'], deferrable=False,
        deferred=False, validated=True, enforced=True, no_inherit=False, index_oid=0,
        definition="CHECK (state = ANY (ARRAY['granted', 'withdrawn']))",
        target_oid=0, update_action=' ', delete_action=' ', match_type=' ',
        delete_columns=None, target_columns=[]), **changes)


@pytest.mark.parametrize('kind', ['c', 'p', 'u', 'f'])
def test_correct_constraints_preserved_including_equivalent_old_names(kind):
    expected = row(kind)
    for actual in [copy.deepcopy(expected), row(kind, name='historical_name', index_oid=987)]:
        before = copy.deepcopy(actual)
        assert compat.constraint_action('table', expected, [actual]) == 'preserve'
        assert actual == before


@pytest.mark.parametrize('kind', ['c', 'p', 'u', 'f'])
def test_missing_constraints_are_additive(kind):
    assert compat.constraint_action('table', row(kind), []) == 'add'


@pytest.mark.parametrize('changed', [
    {'definition': 'CHECK (TRUE)'}, {'deferrable': True}, {'deferred': True},
    {'columns': ['wrong_column']}, {'kind': 'u'}, {'target_oid': 77},
    {'delete_action': 'c'}, {'update_action': 'c'}, {'match_type': 'f'},
    {'delete_columns': '[1]'}, {'target_columns': ['wrong_id']}, {'enforced': False},
    {'no_inherit': True},
])
def test_incompatible_constraints_fail_closed(changed):
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='incompatible existing constraint'):
        compat.constraint_action('table', row(), [row(**changed)])


def test_renamed_wrong_foreign_key_and_conflicting_primary_key_fail_closed():
    with pytest.raises(compat.FamilySchemaCompatibilityError):
        compat.constraint_action('table', row('f'), [row('f', name='old_fk', delete_action='c')])
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='incompatible primary key'):
        compat.constraint_action('table', row('p'), [row('p', name='old_pk', columns=['other'])])
    with pytest.raises(compat.FamilySchemaCompatibilityError):
        compat.constraint_action('table', row(), [row(), row(name='extra_stronger_check', definition='CHECK (FALSE)')])


@pytest.mark.parametrize('kind', ['c', 'f'])
def test_not_valid_constraint_requires_validation(kind):
    expected = row(kind)
    assert compat.constraint_action('table', expected,
        [row(kind, validated=False, definition=expected['definition'] + ' NOT VALID')]) == 'validate'


def index(**changes):
    return dict(dict(oid=1, table_oid=2, unique=True, immediate=True, valid=True,
        ready=True, live=True, method='btree', key_count=1, total_count=1,
        nulls_not_distinct=False, keys=['event_key'], opclasses='3126',
        collations='100', options='0', predicate=None), **changes)


@pytest.mark.parametrize('changed', [
    {'unique': False}, {'valid': False}, {'ready': False}, {'live': False},
    {'immediate': False}, {'nulls_not_distinct': True}, {'method': 'hash'},
    {'keys': ['other']}, {'key_count': 2}, {'total_count': 2},
    {'predicate': 'event_key IS NOT NULL'}, {'collations': '999'},
    {'opclasses': '999'}, {'options': '3'},
])
def test_incompatible_indexes_rejected(changed):
    assert not compat.same_index(index(**changed), index())


def test_correct_indexes_are_preserved_without_oid_identity_requirement():
    assert compat.same_index(index(oid=88, table_oid=99), index())


@pytest.mark.parametrize('statement', [
    'ALTER TABLE t ADD CONSTRAINT ck CHECK (state IN (\'a\'))',
    'ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (user_id) REFERENCES users(id)',
    'ALTER TABLE t ADD CONSTRAINT uq UNIQUE(event_key)',
    'ALTER TABLE t VALIDATE CONSTRAINT ck',
    'ALTER TABLE t ALTER COLUMN state SET NOT NULL',
])
def test_violating_data_aborts_without_cleanup_or_retry(statement):
    seen = []
    class InvalidData:
        def execute(self, sql):
            seen.append(str(sql))
            raise RuntimeError('simulated constraint violation with private row contents')
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='transaction must roll back') as err:
        compat._execute(InvalidData(), 't', 'constraint', statement)
    assert seen == [statement]
    assert 'private row' not in str(err.value)
    assert err.value.__suppress_context__


def test_transaction_required_before_any_metadata_or_ddl():
    class NoTransaction:
        def in_transaction(self): return False
        def execute(self, *args): raise AssertionError('DDL attempted')
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='enclosing migration transaction'):
        compat.converge_constraints(NoTransaction(), DDL)


def test_new_helper_contains_no_application_data_rewrite_or_constraint_drop():
    source = (ROOT / 'app/migrations/family_constraint_compat.py').read_text()
    assert 'DROP CONSTRAINT' not in source and 'DROP INDEX' not in source
    assert 'DELETE FROM' not in source and 'UPDATE ' not in source
    assert 'DROP NOT NULL' not in source
    assert 'ON COMMIT DROP' in source  # empty scratch objects only
    assert 'pg_constraint' in source and 'pg_index' in source
    assert 'pg_get_constraintdef' in source and 'pg_get_indexdef' in source
    assert 'app.db' not in source and 'create_engine' not in source


def test_fresh_and_upgrade_use_identical_ddl_and_shared_preflight():
    for filename, ddl_name in [('fc04_family_consent_authority.py', '_DDL'),
                               ('fc06_family_entitlement_lifecycle_audit.py', 'DDL')]:
        source = (ROOT / 'migrations/versions' / filename).read_text()
        assert 'converge_constraints(' in source
        assert f'import {ddl_name}' in source
    upgrade = (ROOT / 'migrations/versions/fc07_schema_compat.py').read_text()
    assert 'converge_constraints(bind, CONSENT_DDL)' in upgrade
    assert 'converge_constraints(bind, LIFECYCLE_DDL)' in upgrade
    assert 'converge_existing_indexes(bind, STATEMENTS)' in upgrade
    # Existing runtime helpers are not wired to the migration-only preflight.
    for name in ('fc04_family_consent_authority.py', 'fc06_family_entitlement_lifecycle_audit.py'):
        assert 'converge_constraints' not in (ROOT / 'app/migrations' / name).read_text()


def test_canonical_ddl_extraction_does_not_silently_ignore_new_constraint_grammar():
    with pytest.raises(ValueError, match='Unsupported FC declaration'):
        compat.schema_manifest('CREATE TABLE IF NOT EXISTS t (\n id UUID,\n CONSTRAINT x EXCLUDE (id WITH =)\n);')
    assert compat.sql_list("x VARCHAR(40) DEFAULT 'a,b', CHECK (x IN ('a,b','c'))") == [
        "x VARCHAR(40) DEFAULT 'a,b'", "CHECK (x IN ('a,b','c'))"]


SAMPLE = """CREATE TABLE IF NOT EXISTS sample (
    id UUID PRIMARY KEY,
    state VARCHAR(20) NOT NULL,
    CONSTRAINT ck_sample CHECK (state IN ('granted','withdrawn'))
);
"""


def simulated_catalog(monkeypatch, *, absent_table=False, constraints='missing',
                      column_change=None, reject=None):
    """Recording connection plus catalog snapshots, never a database emulator.

    Exercises the real orchestrator/SQL emitter. PostgreSQL parsing, locking and
    DDL execution still require the explicitly deferred disposable-DB tests.
    """
    executed = []
    real = dict(oid=10, schema='public', name='sample', relkind='r')
    ref = dict(oid=20, schema='pg_temp_1', name='reference', relkind='r')
    expected_columns = [dict(name='id', type='uuid', not_null=True, collation=0, default_expr=None),
                        dict(name='state', type='character varying(20)', not_null=True, collation=100, default_expr=None)]
    actual_columns = copy.deepcopy(expected_columns)
    if column_change:
        actual_columns[1].update(column_change)
    pk = row('p', name='sample_pkey', columns=['id'], definition='PRIMARY KEY (id)', index_oid=30)
    check = row(name='ck_sample')
    original = [] if constraints == 'missing' else [pk, check]
    if constraints == 'wrong':
        original[1] = row(name='ck_sample', definition='CHECK (TRUE)')
    if constraints == 'not_valid':
        original[1] = row(name='ck_sample', validated=False, definition=check['definition'] + ' NOT VALID')
    class Connection:
        def in_transaction(self): return True
        def execute(self, statement):
            sql = str(statement)
            executed.append(sql)
            if reject and reject in sql:
                raise RuntimeError('simulated bad existing data')
    def lookup(bind, name):
        if name.startswith('pg_temp.'):
            return ref
        if name != 'sample':
            return None
        if absent_table and not any(sql.startswith('CREATE TABLE') for sql in executed):
            return None
        return real
    def metadata(bind, sql, **params):
        if sql == compat.COLUMNS_SQL:
            return copy.deepcopy(expected_columns if params['oid'] == 20 else actual_columns)
        if sql == compat.CONSTRAINTS_SQL:
            if params['oid'] == 10:
                return copy.deepcopy(original)
            reference_sql = next(sql for sql in executed if sql.startswith('CREATE TEMP TABLE'))
            names = re.findall(r'CONSTRAINT "([^"]+)"', reference_sql)
            return [dict(pk, name=names[0]), dict(check, name=names[1])]
        if sql == compat.INDEX_SQL:
            return [index()]
        raise AssertionError('Unexpected catalog SQL')
    monkeypatch.setattr(compat, 'relation', lookup)
    monkeypatch.setattr(compat, 'rows', metadata)
    return Connection(), executed


@pytest.mark.parametrize('absent_table', [False, True])
def test_real_orchestrator_emits_additive_missing_constraint_sql(monkeypatch, absent_table):
    connection, executed = simulated_catalog(monkeypatch, absent_table=absent_table)
    compat.converge_constraints(connection, SAMPLE)
    assert any(sql.startswith('CREATE TABLE') for sql in executed) is absent_table
    repairs = [sql for sql in executed if sql.startswith('ALTER TABLE')]
    assert repairs == [
        'ALTER TABLE "public"."sample" ADD CONSTRAINT "sample_pkey" PRIMARY KEY (id)',
        'ALTER TABLE "public"."sample" ADD CONSTRAINT "ck_sample" CHECK (state IN (\'granted\',\'withdrawn\'))',
    ]


def test_real_orchestrator_leaves_correct_existing_constraints_untouched(monkeypatch):
    connection, executed = simulated_catalog(monkeypatch, constraints='correct')
    compat.converge_constraints(connection, SAMPLE)
    assert not any(sql.startswith('ALTER TABLE') for sql in executed)


def test_real_orchestrator_rejects_incompatible_constraint_without_replacement(monkeypatch):
    connection, executed = simulated_catalog(monkeypatch, constraints='wrong')
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='incompatible existing constraint'):
        compat.converge_constraints(connection, SAMPLE)
    assert not any(sql.startswith('ALTER TABLE') for sql in executed)


def test_real_orchestrator_validates_existing_not_valid_check(monkeypatch):
    connection, executed = simulated_catalog(monkeypatch, constraints='not_valid')
    compat.converge_constraints(connection, SAMPLE)
    assert [sql for sql in executed if sql.startswith('ALTER TABLE')] == [
        'ALTER TABLE "public"."sample" VALIDATE CONSTRAINT "ck_sample"']


@pytest.mark.parametrize('change,reason', [
    ({'type': 'text'}, 'incompatible type'),
    ({'collation': 777}, 'collation'),
    ({'default_expr': "'invalid'::character varying"}, 'incompatible default'),
])
def test_real_orchestrator_rejects_incompatible_columns(monkeypatch, change, reason):
    connection, executed = simulated_catalog(monkeypatch, column_change=change)
    with pytest.raises(compat.FamilySchemaCompatibilityError, match=reason):
        compat.converge_constraints(connection, SAMPLE)
    assert not any(sql.startswith('ALTER TABLE') for sql in executed)


def test_real_orchestrator_missing_not_null_is_additive_and_invalid_rows_abort(monkeypatch):
    connection, executed = simulated_catalog(monkeypatch, column_change={'not_null': False}, reject='SET NOT NULL')
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='transaction must roll back'):
        compat.converge_constraints(connection, SAMPLE)
    assert executed[-1] == 'ALTER TABLE "public"."sample" ALTER COLUMN "state" SET NOT NULL'
    assert not any('ADD CONSTRAINT' in sql for sql in executed)


@pytest.mark.parametrize('mode', ['correct', 'missing', 'incompatible'])
def test_real_index_emitter_preserves_adds_or_rejects(monkeypatch, mode):
    executed = []
    actual_rel = dict(oid=10, schema='public', name='sample', relkind='r')
    class Connection:
        def execute(self, sql): executed.append(str(sql))
    def lookup(bind, name):
        if name.startswith('pg_temp.'):
            return {'oid': 20}
        return None if mode == 'missing' else {'oid': 30}
    def metadata(bind, sql, **params):
        assert sql == compat.INDEX_SQL
        if params['oid'] == 20:
            return [index(table_oid=99)]
        return [index(table_oid=10, unique=mode != 'incompatible')]
    monkeypatch.setattr(compat, 'relation', lookup)
    monkeypatch.setattr(compat, 'rows', metadata)
    statement = 'CREATE UNIQUE INDEX IF NOT EXISTS uq_sample ON sample(event_key)'
    if mode == 'incompatible':
        with pytest.raises(compat.FamilySchemaCompatibilityError, match='incompatible or invalid existing index'):
            compat._index(Connection(), 'sample', actual_rel, 'uq_sample', statement)
    else:
        compat._index(Connection(), 'sample', actual_rel, 'uq_sample', statement)
    assert any('ON "public"."sample"' in sql for sql in executed) is (mode == 'missing')


@pytest.mark.parametrize('valid_index', [True, False])
def test_existing_standalone_constraint_index_is_attached_or_rejected(monkeypatch, valid_index):
    connection, executed = simulated_catalog(monkeypatch)
    previous_lookup, previous_rows = compat.relation, compat.rows
    def lookup(bind, name):
        if name == '"public"."sample_pkey"':
            return {'oid': 90}
        return previous_lookup(bind, name)
    def metadata(bind, sql, **params):
        if sql == compat.INDEX_SQL and params['oid'] == 90:
            return [index(table_oid=10, valid=valid_index)]
        return previous_rows(bind, sql, **params)
    monkeypatch.setattr(compat, 'relation', lookup)
    monkeypatch.setattr(compat, 'rows', metadata)
    if valid_index:
        compat.converge_constraints(connection, SAMPLE)
        assert 'ALTER TABLE "public"."sample" ADD CONSTRAINT "sample_pkey" PRIMARY KEY USING INDEX "sample_pkey"' in executed
    else:
        with pytest.raises(compat.FamilySchemaCompatibilityError, match='incompatible object occupying'):
            compat.converge_constraints(connection, SAMPLE)
        assert not any(sql.startswith('ALTER TABLE') for sql in executed)


def test_nullable_canonical_column_never_silently_relaxes_existing_not_null(monkeypatch):
    connection, executed = simulated_catalog(monkeypatch)
    previous_rows = compat.rows
    def metadata(bind, sql, **params):
        result = previous_rows(bind, sql, **params)
        if sql == compat.COLUMNS_SQL and params['oid'] == 20:
            result[1]['not_null'] = False
        return result
    monkeypatch.setattr(compat, 'rows', metadata)
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='implicit relaxation refused'):
        compat.converge_constraints(connection, SAMPLE.replace('state VARCHAR(20) NOT NULL', 'state VARCHAR(20) NULL'))
    assert not any(sql.startswith('ALTER TABLE') for sql in executed)


def test_missing_unapproved_column_requires_review_not_fabricated_data(monkeypatch):
    connection, executed = simulated_catalog(monkeypatch)
    previous_rows = compat.rows
    def metadata(bind, sql, **params):
        result = previous_rows(bind, sql, **params)
        if sql == compat.COLUMNS_SQL and params['oid'] == 10:
            return result[:1]
        return result
    monkeypatch.setattr(compat, 'rows', metadata)
    with pytest.raises(compat.FamilySchemaCompatibilityError, match='missing column without approved additive definition'):
        compat.converge_constraints(connection, SAMPLE)
    assert not any(sql.startswith('ALTER TABLE') for sql in executed)
