"""Migration-only, additive FC04/FC06 constraint convergence.

The existing DDL is the definition authority. Empty transaction-local reference
tables let PostgreSQL canonicalize CHECK/index expressions: no hand-written
normalizer can accidentally treat a weaker expression as equivalent. References
are ON COMMIT DROP; existing application objects are never dropped/replaced.
No engine, connection, environment, startup hook or commit is created here.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text


class FamilySchemaCompatibilityError(RuntimeError):
    pass


def ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def fail(table: str, item: str, reason: str):
    raise FamilySchemaCompatibilityError(
        f"FC schema preflight: {table}.{item}: {reason}; no replacement or data repair is permitted"
    )


def sql_list(value: str) -> list[str]:
    """Split this versioned DDL grammar, preserving literals and nested lists."""
    result, start, depth, quoted, i = [], 0, 0, False, 0
    while i < len(value):
        char = value[i]
        if char == "'":
            if quoted and i + 1 < len(value) and value[i + 1] == "'":
                i += 2
                continue
            quoted = not quoted
        elif not quoted:
            depth += (char == '(') - (char == ')')
            if char == ',' and depth == 0:
                result.append(value[start:i].strip())
                start = i + 1
        i += 1
    if quoted or depth:
        raise ValueError("Unsupported/unbalanced FC DDL")
    return result + [value[start:].strip()]


@dataclass
class Constraint:
    name: str
    definition: str
    columns: tuple[str, ...] = ()
    target: str | None = None
    delete_action: str = "a"


@dataclass
class Table:
    name: str
    create: str
    columns: dict[str, str] = field(default_factory=dict)
    constraints: list[Constraint] = field(default_factory=list)
    additions: dict[str, str] = field(default_factory=dict)
    indexes: dict[str, str] = field(default_factory=dict)


def schema_manifest(ddl: str) -> list[Table]:
    """Enumerate PK, FK, UNIQUE, CHECK, columns and indexes from canonical DDL.

    This deliberately accepts only the existing FC04/FC06 grammar; unexpected
    constraints fail rather than being silently ignored when the DDL evolves.
    """
    tables = {}
    for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", ddl, re.S):
        name, body = match.groups()
        table = tables[name] = Table(name, match.group(0))
        for part in sql_list(body):
            named = re.fullmatch(r"CONSTRAINT (\w+)\s+((?:CHECK|UNIQUE)\s*\(.*\))", part, re.S)
            if named:
                table.constraints.append(Constraint(*named.groups()))
                continue
            col = re.match(r"(\w+)\s+(UUID|VARCHAR\(\d+\)|TIMESTAMPTZ|BOOLEAN|JSONB|INTEGER)(?=\s|$)", part)
            if not col or part.startswith(('CONSTRAINT', 'CHECK', 'FOREIGN', 'UNIQUE')):
                raise ValueError(f"Unsupported FC declaration: {name}")
            column = col[1]
            if 'PRIMARY KEY' in part:
                table.constraints.append(Constraint(name + '_pkey', f'PRIMARY KEY ({column})', (column,)))
            if re.search(r'\bUNIQUE\b', part):
                table.constraints.append(Constraint(name + '_' + column + '_key', f'UNIQUE ({column})', (column,)))
            fk = re.search(r'REFERENCES (\w+)\(id\) ON DELETE (CASCADE|RESTRICT|SET NULL)', part)
            if fk:
                table.constraints.append(Constraint(name + '_' + column + '_fkey',
                    f'FOREIGN KEY ({column}) REFERENCES {fk[1]}(id) ON DELETE {fk[2]}',
                    (column,), fk[1], {'CASCADE': 'c', 'RESTRICT': 'r', 'SET NULL': 'n'}[fk[2]]))
            declaration = re.sub(r' REFERENCES \w+\(id\) ON DELETE (CASCADE|RESTRICT|SET NULL)', '', part)
            declaration = declaration.replace('PRIMARY KEY', 'NOT NULL').replace(' UNIQUE', '')
            table.columns[column] = declaration
    if not tables:
        raise ValueError('No FC tables found')
    for match in re.finditer(r'ALTER TABLE (\w+)\s+ADD COLUMN IF NOT EXISTS (\w+)\s+([^;]+);', ddl):
        table, column, declaration = match.groups()
        tables[table].additions[column] = match.group(0)
        tables[table].columns.setdefault(column, column + ' ' + declaration)
    for match in re.finditer(r'CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+)\s+ON (\w+)\s*\([^;]+;', ddl):
        name, table = match[1], match[2]
        tables[table].indexes[name] = match.group(0)
    return list(tables.values())


RELATION_SQL = """SELECT c.oid, n.nspname AS schema, c.relname AS name, c.relkind
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE c.oid=to_regclass(:name)"""
COLUMNS_SQL = """SELECT a.attname AS name, format_type(a.atttypid,a.atttypmod) AS type,
 a.attnotnull AS not_null, a.attcollation AS collation,
 pg_get_expr(d.adbin,d.adrelid) AS default_expr
 FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
 WHERE a.attrelid=:oid AND a.attnum>0 AND NOT a.attisdropped"""
CONSTRAINTS_SQL = """SELECT c.conname AS name, c.contype AS kind,
 ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num,ord)
       JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord) AS columns,
 c.condeferrable AS deferrable, c.condeferred AS deferred, c.convalidated AS validated,
 COALESCE((to_jsonb(c)->>'conenforced')::boolean, TRUE) AS enforced,
 c.connoinherit AS no_inherit, c.conindid AS index_oid,
 pg_get_constraintdef(c.oid, FALSE) AS definition,
 c.confrelid AS target_oid, c.confupdtype AS update_action,
 c.confdeltype AS delete_action, c.confmatchtype AS match_type,
 to_jsonb(c)->>'confdelsetcols' AS delete_columns,
 ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(num,ord)
       JOIN pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.num ORDER BY k.ord) AS target_columns
 FROM pg_constraint c WHERE c.conrelid=:oid"""
INDEX_SQL = """SELECT i.indexrelid AS oid, i.indrelid AS table_oid,
 i.indisunique AS unique, i.indimmediate AS immediate, i.indisvalid AS valid,
 i.indisready AS ready, i.indislive AS live, am.amname AS method,
 i.indnkeyatts AS key_count, i.indnatts AS total_count,
 COALESCE((to_jsonb(i)->>'indnullsnotdistinct')::boolean,FALSE) AS nulls_not_distinct,
 ARRAY(SELECT pg_get_indexdef(i.indexrelid,k,FALSE) FROM generate_series(1,i.indnatts) k) AS keys,
 i.indclass::text AS opclasses, i.indcollation::text AS collations, i.indoption::text AS options,
 pg_get_expr(i.indpred,i.indrelid,FALSE) AS predicate
 FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_am am ON am.oid=c.relam
 WHERE i.indexrelid=:oid"""


def rows(bind, sql, **params):
    return [dict(row) for row in bind.execute(text(sql), params).mappings().all()]


def relation(bind, name):
    found = rows(bind, RELATION_SQL, name=name)
    return found[0] if found else None


def qualified(rel):
    return ident(rel['schema']) + '.' + ident(rel['name'])


def same_index(actual: dict, expected: dict) -> bool:
    ignored = {'oid', 'table_oid'}
    return (all(actual.get(k) for k in ('valid', 'ready', 'live'))
            and {k: v for k, v in actual.items() if k not in ignored}
            == {k: v for k, v in expected.items() if k not in ignored})


def constraint_action(table: str, expected: dict, existing: list[dict]) -> str:
    """Pure fail-closed planner: preserve, add, or validate. Never replace."""
    named = [row for row in existing if row['name'] == expected['name']]
    related = [row for row in existing if row['kind'] == expected['kind']
               and tuple(row['columns']) == tuple(expected['columns'])]
    candidates = [row for row in existing if row in named or row in related]
    if not candidates:
        # A different PK cannot coexist; make the error explicit before ADD.
        if expected['kind'] == 'p' and any(row['kind'] == 'p' for row in existing):
            fail(table, expected['name'], 'incompatible primary key')
        return 'add'
    ignored = {'name', 'validated', 'index_oid'}
    def signature(row):
        value = {k: v for k, v in row.items() if k not in ignored}
        # PostgreSQL appends NOT VALID to otherwise identical FK/CHECK SQL.
        value['definition'] = re.sub(r' NOT VALID$', '', value.get('definition', ''))
        return value
    for actual in candidates:
        if signature(actual) != signature(expected):
            fail(table, expected['name'], 'incompatible existing constraint')
    return 'preserve' if all(row['validated'] for row in candidates) else 'validate'


def _execute(bind, table, item, sql):
    try:
        bind.execute(text(sql))
    except Exception as exc:
        # PostgreSQL validates existing rows for ADD/VALIDATE/SET NOT NULL.
        # Do not expose row values in the public migration/preflight message.
        raise FamilySchemaCompatibilityError(
            f'FC schema preflight: {table}.{item}: additive DDL/validation failed; '
            'transaction must roll back; inspect schema/data in disposable DB'
        ) from None


def _index(bind, table, actual_rel, name, statement):
    reference_name = '_fc7_ix_' + uuid.uuid4().hex[:20]
    temp = '_fc7_ix_table_' + uuid.uuid4().hex[:20]
    _execute(bind, table, name,
             f'CREATE TEMP TABLE {ident(temp)} (LIKE {qualified(actual_rel)}) ON COMMIT DROP')
    expected_sql = re.sub(r'INDEX IF NOT EXISTS \w+', 'INDEX ' + ident(reference_name), statement, count=1)
    expected_sql = re.sub(r'ON \w+', 'ON pg_temp.' + ident(temp), expected_sql, count=1)
    _execute(bind, table, name, expected_sql)
    expected = rows(bind, INDEX_SQL, oid=relation(bind, 'pg_temp.' + reference_name)['oid'])[0]
    current = relation(bind, ident(actual_rel['schema']) + '.' + ident(name))
    if current:
        found = rows(bind, INDEX_SQL, oid=current['oid'])
        if not found or found[0]['table_oid'] != actual_rel['oid'] or not same_index(found[0], expected):
            fail(table, name, 'incompatible or invalid existing index')
        return
    repair = re.sub(r'ON \w+', 'ON ' + qualified(actual_rel), statement, count=1)
    _execute(bind, table, name, repair)


def converge_constraints(bind, ddl: str):
    """Called only by Alembic, within its transaction, never by app startup."""
    if not bind.in_transaction():
        raise FamilySchemaCompatibilityError('FC preflight requires an enclosing migration transaction')

    # Alembic owns NISCHINT application objects in public.  Keep pg_temp
    # available for transaction-local reference tables used by the
    # compatibility validator.
    bind.execute(text("SET LOCAL search_path TO public, pg_temp"))
    for table in schema_manifest(ddl):
        actual = relation(bind, table.name)
        if actual is None:
            _execute(bind, table.name, 'table', table.create)
            actual = relation(bind, table.name)
        if not actual or actual['relkind'] != 'r' or actual['schema'].startswith('pg_temp'):
            fail(table.name, 'table', 'missing, temporary, partitioned or unsupported relation')
        target = qualified(actual)
        _execute(bind, table.name, 'lock', f'LOCK TABLE {target} IN ACCESS EXCLUSIVE MODE')
        present = {row['name']: row for row in rows(bind, COLUMNS_SQL, oid=actual['oid'])}
        for col in table.columns:
            if col not in present:
                if col not in table.additions:
                    fail(table.name, col, 'missing column without approved additive definition')
                repair = table.additions[col].replace('ALTER TABLE ' + table.name, 'ALTER TABLE ' + target, 1)
                _execute(bind, table.name, col, repair)
        temp = '_fc7_expected_' + uuid.uuid4().hex[:20]
        definitions = list(table.columns.values())
        reference_names = {}
        for number, constraint in enumerate(table.constraints):
            if not constraint.target:
                reference_names[constraint.name] = temp + '_' + str(number)
                definitions.append('CONSTRAINT ' + ident(reference_names[constraint.name]) + ' ' + constraint.definition)
        _execute(bind, table.name, 'reference',
                 f'CREATE TEMP TABLE {ident(temp)} (' + ', '.join(definitions) + ') ON COMMIT DROP')
        reference = relation(bind, 'pg_temp.' + temp)
        expected_cols = rows(bind, COLUMNS_SQL, oid=reference['oid'])
        present = {row['name']: row for row in rows(bind, COLUMNS_SQL, oid=actual['oid'])}
        for expected in expected_cols:
            current = present[expected['name']]
            col = expected['name']
            if current['type'] != expected['type'] or current['collation'] != expected['collation']:
                fail(table.name, col, 'incompatible type or collation')
            if current['not_null'] and not expected['not_null']:
                fail(table.name, col, 'incompatible NOT NULL; implicit relaxation refused')
            if expected['not_null'] and not current['not_null']:
                _execute(bind, table.name, col, f'ALTER TABLE {target} ALTER COLUMN {ident(col)} SET NOT NULL')
            if current['default_expr'] != expected['default_expr']:
                if current['default_expr'] is not None or expected['default_expr'] is None:
                    fail(table.name, col, 'incompatible default')
                _execute(bind, table.name, col, f'ALTER TABLE {target} ALTER COLUMN {ident(col)} SET DEFAULT {expected["default_expr"]}')
        reference_constraints = {row['name']: row for row in rows(bind, CONSTRAINTS_SQL, oid=reference['oid'])}
        existing = rows(bind, CONSTRAINTS_SQL, oid=actual['oid'])
        for spec in table.constraints:
            if spec.target:
                ref = relation(bind, spec.target)
                if not ref:
                    fail(table.name, spec.name, 'missing referenced table')
                definition = f'FOREIGN KEY ({spec.columns[0]}) REFERENCES {qualified(ref)}(id)'
                # pg_get_constraintdef may omit schema quoting; compare FK
                # structure/OIDs instead of its display SQL.
                expected = dict(name=spec.name, kind='f', columns=list(spec.columns),
                    deferrable=False, deferred=False, validated=True, enforced=True,
                    no_inherit=True, index_oid=0, definition='', target_oid=ref['oid'],
                    update_action='a', delete_action=spec.delete_action, match_type='s',
                    delete_columns=None, target_columns=['id'])
                candidates = [dict(row, definition='') if row['kind'] == 'f' else row for row in existing]
                repair = definition + ' ON DELETE ' + {'c': 'CASCADE', 'r': 'RESTRICT', 'n': 'SET NULL'}[spec.delete_action]
            else:
                expected = dict(reference_constraints[reference_names[spec.name]], name=spec.name)
                candidates, repair = existing, spec.definition
            action = constraint_action(table.name, expected, candidates)
            if action == 'add':
                if expected['kind'] in ('p', 'u'):
                    # A correct standalone index may already occupy the
                    # automatic constraint name. Attach it; never drop/rebuild
                    # it or silently accept a different index definition.
                    occupied = relation(bind, ident(actual['schema']) + '.' + ident(spec.name))
                    if occupied:
                        indexes = rows(bind, INDEX_SQL, oid=occupied['oid'])
                        wanted = rows(bind, INDEX_SQL, oid=expected['index_oid'])[0]
                        if (not indexes or indexes[0]['table_oid'] != actual['oid']
                                or not same_index(indexes[0], wanted)):
                            fail(table.name, spec.name, 'incompatible object occupying constraint index name')
                        repair = ('PRIMARY KEY' if expected['kind'] == 'p' else 'UNIQUE') + ' USING INDEX ' + ident(spec.name)
                _execute(bind, table.name, spec.name, f'ALTER TABLE {target} ADD CONSTRAINT {ident(spec.name)} {repair}')
            else:
                matches = [row for row in candidates if row['name'] == spec.name or
                           (row['kind'] == expected['kind'] and row['columns'] == expected['columns'])]
                for row in matches:
                    if expected['kind'] in ('p', 'u'):
                        left = rows(bind, INDEX_SQL, oid=row['index_oid'])[0]
                        right = rows(bind, INDEX_SQL, oid=expected['index_oid'])[0]
                        if not same_index(left, right):
                            fail(table.name, spec.name, 'incompatible backing index')
                    if not row['validated']:
                        _execute(bind, table.name, row['name'], f'ALTER TABLE {target} VALIDATE CONSTRAINT {ident(row["name"])}')
        for name, statement in table.indexes.items():
            _index(bind, table.name, actual, name, statement)


def converge_existing_indexes(bind, statements):
    """Validate FC07's historical indexes as well as repairing missing ones."""
    for statement in statements:
        match = re.match(r'CREATE (?:UNIQUE )?INDEX IF NOT EXISTS (\w+) ON (\w+)', statement)
        if not match:
            continue
        name, table = match.groups()
        actual = relation(bind, table)
        if not actual or actual['relkind'] != 'r':
            fail(table, name, 'missing or unsupported table')
        _execute(bind, table, 'lock', f'LOCK TABLE {qualified(actual)} IN ACCESS EXCLUSIVE MODE')
        _index(bind, table, actual, name, statement)
