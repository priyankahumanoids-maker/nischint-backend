"""Family Circle v1.0 Phase 1A DOB/age foundation tests.

These tests are intentionally DB-free. They validate the calendar-age policy and
source contracts without importing the full FastAPI application.
"""

from __future__ import annotations

import ast
import importlib.util
from datetime import date
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AGE_POLICY_PATH = BACKEND_ROOT / "app" / "core" / "age_policy.py"
AUTH_PATH = BACKEND_ROOT / "app" / "api" / "auth.py"
USER_MODEL_PATH = BACKEND_ROOT / "app" / "models" / "user.py"
USER_SCHEMA_PATH = BACKEND_ROOT / "app" / "schemas" / "user.py"
RUNTIME_MIGRATION_PATH = BACKEND_ROOT / "app" / "migrations" / "fc01_user_date_of_birth.py"
ALEMBIC_MIGRATION_PATH = BACKEND_ROOT / "migrations" / "versions" / "fc01_user_date_of_birth.py"


def _load_age_policy():
    spec = importlib.util.spec_from_file_location("fc01_age_policy", AGE_POLICY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"Function {name!r} not found in {path}")


def test_exact_18th_birthday_boundary():
    policy = _load_age_policy()
    dob = date(2008, 9, 29)

    assert policy.calculate_age(dob, date(2026, 9, 28)) == 17
    assert policy.is_minor(dob, date(2026, 9, 28)) is True
    assert policy.calculate_age(dob, date(2026, 9, 29)) == 18
    assert policy.is_minor(dob, date(2026, 9, 29)) is False


def test_calendar_age_handles_leap_day_and_future_dates():
    policy = _load_age_policy()
    leap_dob = date(2008, 2, 29)

    assert policy.calculate_age(leap_dob, date(2026, 2, 28)) == 17
    assert policy.calculate_age(leap_dob, date(2026, 3, 1)) == 18

    try:
        policy.calculate_age(date(2027, 1, 1), date(2026, 9, 29))
    except ValueError as exc:
        assert "future" in str(exc).lower()
    else:
        raise AssertionError("Future DOB must be rejected")


def test_user_model_persists_nullable_dob_without_storing_mutable_age():
    source = USER_MODEL_PATH.read_text(encoding="utf-8")
    assert "date_of_birth: Mapped[date | None]" in source
    assert "sa.Date()" in source
    assert "date_of_birth" in source and "nullable=True" in source
    assert "age: Mapped[" not in source


def test_new_registration_schema_requires_dob():
    source = USER_SCHEMA_PATH.read_text(encoding="utf-8")
    register_start = source.index("class RegisterRequest")
    register_end = source.index("class UserResponse", register_start)
    register_block = source[register_start:register_end]
    assert "date_of_birth: date" in register_block
    assert "date_of_birth: Optional" not in register_block


def test_normal_self_registration_rejects_minors_before_consuming_phone_ticket():
    register_source = _function_source(AUTH_PATH, "register")
    age_guard = register_source.index("_require_adult_self_registration(req.date_of_birth)")
    consume_ticket = register_source.index("_consume_signup_phone_verification")
    assert age_guard < consume_ticket

    guard_source = _function_source(AUTH_PATH, "_require_adult_self_registration")
    assert "ADULT_AGE_YEARS" in guard_source
    assert "Ask a parent to add you to their circle." in guard_source
    assert "HTTP_403_FORBIDDEN" in guard_source


def test_legacy_invite_join_still_rejects_minors_while_parent_created_minor_invites_are_canonical():
    source = _function_source(AUTH_PATH, "verify_invite_code")
    legacy_start = source.index("# Lock the guardian row until commit")
    legacy = source[legacy_start:]
    age_guard = legacy.index("_require_adult_self_registration(req.date_of_birth)")
    user_create = legacy.index("new_user = User(")
    assert age_guard < user_create
    assert "accept_invite_for_user" in source
    assert "canonical_preview.invitee_kind" in source
    assert "date_of_birth=req.date_of_birth" in source


def test_all_new_account_paths_persist_dob_and_tokens_carry_dob_not_age():
    source = AUTH_PATH.read_text(encoding="utf-8")
    assert source.count("date_of_birth=req.date_of_birth") >= 3
    assert source.count('"date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None') >= 5

    issue_source = _function_source(AUTH_PATH, "_issue_local_session_response")
    assert '"date_of_birth"' in issue_source
    assert '"age"' not in issue_source


def test_me_endpoint_derives_age_at_read_time_and_preserves_legacy_nulls():
    source = _function_source(AUTH_PATH, "get_me")
    assert "date_of_birth = user.date_of_birth" in source
    assert "calculate_age(date_of_birth) if date_of_birth is not None else None" in source
    assert '"date_of_birth"' in source
    assert '"age"' in source
    assert '"is_minor"' in source


def test_schema_migrations_are_additive_and_existing_users_remain_compatible():
    runtime = RUNTIME_MIGRATION_PATH.read_text(encoding="utf-8")
    alembic = ALEMBIC_MIGRATION_PATH.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS date_of_birth DATE" in runtime
    assert 'sa.Column("date_of_birth", sa.Date(), nullable=True)' in alembic
    assert 'down_revision = "gz02_safe_zone_address"' in alembic
