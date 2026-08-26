from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ROLES_PATH = BACKEND_ROOT / 'app' / 'core' / 'product_roles.py'
DEPS_PATH = BACKEND_ROOT / 'app' / 'api' / 'deps.py'
RBAC_PATH = BACKEND_ROOT / 'app' / 'core' / 'rbac.py'
ROLES_PATH = BACKEND_ROOT / 'app' / 'core' / 'roles.py'
AUTH_PATH = BACKEND_ROOT / 'app' / 'api' / 'auth.py'


def _load_product_roles():
    spec = importlib.util.spec_from_file_location('nischint_product_roles_test', PRODUCT_ROLES_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_product_role_vocabulary_and_aliases_are_canonical():
    roles = _load_product_roles()

    assert roles.normalize_role('parent') == 'guardian'
    assert roles.normalize_role('co-guardian') == 'co_parent'
    assert roles.normalize_role('co parent') == 'co_parent'
    assert roles.normalize_role('kids') == 'child'
    assert roles.normalize_role('women') == 'woman'
    assert roles.normalize_role('elderly') == 'senior'
    assert roles.normalize_role('family_member') == 'family'

    assert roles.PROTECTED_MEMBER_ROLES == {'child', 'woman', 'senior', 'family'}
    assert roles.PRIMARY_GUARDIAN_ROLES == {'guardian'}
    assert roles.CO_GUARDIAN_ROLES == {'co_parent'}


def test_co_parent_remains_distinct_from_primary_guardian():
    roles = _load_product_roles()

    assert roles.is_primary_guardian('guardian') is True
    assert roles.is_primary_guardian('parent') is True
    assert roles.is_primary_guardian('co_parent') is False
    assert roles.is_co_guardian('co_guardian') is True
    assert roles.is_guardian_monitor('co-parent') is True
    assert roles.is_protected_member('co_parent') is False


def test_cognito_primary_role_selection_supports_all_product_roles():
    roles = _load_product_roles()

    for role in ('child', 'woman', 'senior', 'family', 'co_parent'):
        assert roles.select_primary_role([role]) == role

    assert roles.select_primary_role(['child', 'guardian']) == 'guardian'
    assert roles.select_primary_role(['co_parent', 'admin']) == 'admin'
    assert roles.select_primary_role(['unknown-role']) is None


def test_all_three_rbac_helpers_use_canonical_role_normalization():
    deps = _source(DEPS_PATH)
    rbac = _source(RBAC_PATH)
    roles = _source(ROLES_PATH)

    assert 'normalize_roles(role)' in deps
    assert 'normalize_role(user.role)' in deps

    assert 'VALID_ROLES = set(CANONICAL_ROLES)' in rbac
    assert 'normalize_roles(cognito_groups)' in rbac
    assert 'allowed = normalize_roles(allowed_roles)' in rbac

    assert 'normalized_allowed = normalize_roles(allowed_roles)' in roles
    assert 'normalize_role(current_user.role)' in roles


def test_auth_cognito_sync_uses_canonical_product_role_selector():
    source = _source(AUTH_PATH)
    tree = ast.parse(source, filename=str(AUTH_PATH))

    assert 'select_primary_role(cognito_groups)' in source
    assert 'sorted(normalize_roles(cognito_groups))' in source
    # The old incomplete hard-coded priority must be gone.
    assert '"guardian": 2, "child": 1' not in source

    # Keep registration contract explicit: family invite can create exactly the
    # product protected/co-parent roles already supported by the mobile flow.
    assert 'pattern="^(child|woman|senior|family|co_parent)$"' in source
