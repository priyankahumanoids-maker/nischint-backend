"""Source-contract tests for Day-2 authorization ownership hardening.

These tests deliberately avoid importing the FastAPI application so they can run
in the lightweight local validation environment without pulling the full backend
runtime dependency graph.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMERGENCY = ROOT / "app" / "api" / "emergency.py"
GUARDIAN_DASHBOARD = ROOT / "app" / "api" / "guardian_dashboard.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            end = getattr(node, "end_lineno", None)
            assert end is not None
            return "\n".join(lines[node.lineno - 1 : end])
    raise AssertionError(f"Function {name!r} not found in {path}")


def test_emergency_location_update_is_owner_only():
    src = _function_source(EMERGENCY, "location_update")
    assert "_get_emergency_event_or_404" in src
    assert "str(event.user_id) != str(user.id)" in src
    assert "Only the emergency owner may update its live location." in src
    assert "update_emergency_location" in src


def test_emergency_status_requires_owner_relationship_or_system_access():
    helper = _function_source(EMERGENCY, "_caller_can_monitor_emergency")
    endpoint = _function_source(EMERGENCY, "get_status")

    assert '{"admin", "operator"}' in helper
    assert "str(event_user_id) == str(user.id)" in helper
    assert "_get_linked_user_ids" in helper
    assert "include_checkin_recovery=False" in helper
    assert "_caller_can_monitor_emergency" in endpoint
    assert 'status_code=404' in endpoint


def test_emergency_resolve_is_primary_guardian_or_system_only():
    helper = _function_source(EMERGENCY, "_caller_can_resolve_emergency")
    endpoint = _function_source(EMERGENCY, "resolve_sos")

    assert '{"admin", "operator"}' in helper
    assert "is_primary_guardian" in helper
    assert "_get_linked_user_ids" in helper
    assert "include_checkin_recovery=False" in helper
    # Owner-self authorization must not bypass the cancellation PIN workflow.
    assert "str(event_user_id) == str(user.id)" not in helper
    assert "_caller_can_resolve_emergency" in endpoint


def test_end_session_requires_owner_primary_guardian_or_system_access():
    src = _function_source(GUARDIAN_DASHBOARD, "end_session")

    assert "GuardianSession" in src
    assert "str(journey.user_id) == str(user.id)" in src
    assert '{"admin", "operator"}' in src
    assert "is_primary_guardian" in src
    assert "_get_linked_user_ids" in src
    assert "include_checkin_recovery=False" in src
    assert "You are not authorized to end this journey session." in src
