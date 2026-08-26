"""Day-2 authentication foundation source-contract tests.

These tests intentionally avoid importing the full FastAPI application package.
`app.api.__init__` imports every router in the backend, which would make a small
authentication contract test pull in the entire AI/geo/runtime dependency set.

The production modules are still validated separately with `py_compile`.
These tests lock the expected authentication contracts using Python's AST only.
"""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = BACKEND_ROOT / "app" / "api" / "auth.py"
COGNITO_PATH = BACKEND_ROOT / "app" / "core" / "cognito.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found")


def _source(path: Path, node: ast.AST) -> str:
    text = path.read_text(encoding="utf-8")
    segment = ast.get_source_segment(text, node)
    return segment or ""


def _router_post_paths(fn: ast.AST) -> set[str]:
    paths: set[str] = set()
    for decorator in getattr(fn, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "post"
            and isinstance(target.value, ast.Name)
            and target.value.id == "router"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and isinstance(decorator.args[0].value, str)
        ):
            paths.add(decorator.args[0].value)
    return paths


def _called_attributes(node: ast.AST) -> set[str]:
    attrs: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            attrs.add(child.func.attr)
    return attrs


def test_auth_router_exposes_password_recovery_and_logout():
    tree = _tree(AUTH_PATH)

    forgot = _function(tree, "forgot_password")
    reset = _function(tree, "reset_password")
    logout = _function(tree, "logout")

    assert "/forgot-password" in _router_post_paths(forgot)
    assert "/reset-password" in _router_post_paths(reset)
    assert "/logout" in _router_post_paths(logout)


def test_local_reset_contract_is_hashed_one_time_and_attempt_bounded():
    tree = _tree(AUTH_PATH)

    store_fn = _function(tree, "_store_local_password_reset")
    consume_fn = _function(tree, "_consume_local_password_reset")

    store_src = _source(AUTH_PATH, store_fn)
    consume_src = _source(AUTH_PATH, consume_fn)
    full_src = AUTH_PATH.read_text(encoding="utf-8")

    assert 'PASSWORD_RESET_TTL_SECONDS = 15 * 60' in full_src
    assert "PASSWORD_RESET_MAX_ATTEMPTS = 5" in full_src
    assert "_password_reset_digest(email, code)" in store_src
    assert "set_json" in store_src
    assert "ttl=PASSWORD_RESET_TTL_SECONDS" in store_src

    assert "hmac.compare_digest" in consume_src
    assert "PASSWORD_RESET_MAX_ATTEMPTS" in consume_src
    assert "delete_key" in consume_src
    assert "set_json" in consume_src


def test_cognito_password_reset_contract_calls_expected_aws_operations():
    tree = _tree(COGNITO_PATH)

    forgot = _function(tree, "forgot_password")
    confirm = _function(tree, "confirm_forgot_password")

    assert "forgot_password" in _called_attributes(forgot)
    assert "confirm_forgot_password" in _called_attributes(confirm)

    forgot_src = _source(COGNITO_PATH, forgot)
    confirm_src = _source(COGNITO_PATH, confirm)

    assert "_compute_secret_hash" in forgot_src
    assert "_compute_secret_hash" in confirm_src
    assert "ClientId" in forgot_src
    assert "ClientId" in confirm_src


def test_logout_contract_is_best_effort_and_cognito_revocation_exists():
    auth_tree = _tree(AUTH_PATH)
    cognito_tree = _tree(COGNITO_PATH)

    logout = _function(auth_tree, "logout")
    admin_logout = _function(cognito_tree, "admin_global_sign_out")

    logout_src = _source(AUTH_PATH, logout)

    assert "admin_global_sign_out" in logout_src
    assert "server_revoked" in logout_src
    assert any(isinstance(node, ast.ExceptHandler) for node in ast.walk(logout))

    assert "admin_user_global_sign_out" in _called_attributes(admin_logout)
    admin_src = _source(COGNITO_PATH, admin_logout)
    assert "UserPoolId" in admin_src
    assert "Username" in admin_src
