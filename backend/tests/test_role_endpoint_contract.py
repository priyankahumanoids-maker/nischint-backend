"""Source-contract tests for Day 2 Family/Role endpoint alignment.

These tests intentionally avoid importing the full FastAPI application so they
can run in the lightweight local verification environment.
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"Function not found: {name}")


def test_admin_user_management_uses_canonical_product_roles():
    src = _read("app/api/admin.py")
    assert "CANONICAL_ROLES" in src
    assert "_ADMIN_ROLE_PATTERN" in src
    assert 'pattern="^(admin|guardian|operator|caregiver|user)$"' not in src
    assert "for role in sorted(CANONICAL_ROLES):" in src
    assert "user.role = normalize_role(body.role)" in src
    assert "role=normalize_role(body.role)" in src


def test_legacy_sos_trigger_and_cancel_accept_all_protected_member_roles():
    src = _read("app/api/sos.py")
    assert "PROTECTED_MEMBER_ROLES" in src
    assert "_trigger_role = require_role(sorted(_ESCAPE_ROLES | PROTECTED_MEMBER_ROLES))" in src

    trigger = _function_source(src, "trigger_sos")
    cancel = _function_source(src, "cancel_sos")
    history = _function_source(src, "sos_history")
    get_config = _function_source(src, "get_config")

    assert "Depends(_trigger_role)" in trigger
    assert "Depends(_trigger_role)" in cancel
    # Existing guardian/operator/admin-only config/history boundaries stay unchanged.
    assert "Depends(_escape_role)" in history
    assert "Depends(_escape_role)" in get_config


def test_all_protected_members_receive_their_own_dashboard_alert_view():
    src = _read("app/api/guardian_dashboard.py")
    assert "from app.core.product_roles import" in src
    assert "is_protected_member" in src
    get_alerts = _function_source(src, "get_alerts")
    assert "if is_protected_member(user.role):" in get_alerts
    assert "get_child_alerts" in get_alerts
