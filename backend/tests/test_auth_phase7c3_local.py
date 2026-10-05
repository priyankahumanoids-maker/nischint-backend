"""Phase 7C-3 source-only contracts.

No application imports, database, Redis, provider, network or startup.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOBILE = Path(r"D:\Nischint\cb")


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def function_source(rel: str, name: str) -> str:
    source = text(rel)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"Function not found: {rel}:{name}")


class Phase7C3Contracts(unittest.TestCase):
    def test_access_default_is_fifteen_minutes(self):
        src = text("app/core/config.py")
        self.assertIn("jwt_expires_minutes: int = Field(default=15", src)

    def test_refresh_default_remains_thirty_days(self):
        self.assertIn("jwt_refresh_expires_days: int = Field(default=30", text("app/core/config.py"))

    def test_access_and_refresh_token_types_remain_separate(self):
        src = text("app/core/security.py")
        self.assertIn('"type": "access"', src)
        self.assertIn('"type": "refresh"', src)
        self.assertIn('payload.get("type") != "refresh"', src)
        self.assertIn('payload.get("type") == "refresh"', src)

    def test_refresh_replay_uses_existing_unique_consumption_store(self):
        src = function_source("app/api/auth.py", "_claim_local_refresh_once")
        self.assertIn("INSERT INTO auth_refresh_consumptions", src)
        self.assertIn("ON CONFLICT (token_id) DO NOTHING", src)
        self.assertIn("RETURNING token_id", src)

    def test_auth_boundary_lock_reuses_users_row(self):
        src = function_source("app/services/auth_session_service.py", "lock_user_auth_boundary")
        self.assertIn("FROM users", src)
        self.assertIn("FOR UPDATE", src)
        self.assertNotIn("INSERT INTO", src)

    def test_local_refresh_locks_before_session_or_epoch_validation(self):
        src = function_source("app/api/auth.py", "refresh")
        lock = src.index("lock_user_auth_boundary(session, refresh_user_id)")
        durable = src.index("validate_auth_session(")
        legacy = src.index("validate_legacy_token_epoch(")
        claim = src.index("_claim_local_refresh_once(")
        self.assertLess(lock, durable)
        self.assertLess(lock, legacy)
        self.assertLess(lock, claim)

    def test_local_refresh_commits_before_returning_replacement(self):
        src = function_source("app/api/auth.py", "refresh")
        claim = src.index("_claim_local_refresh_once(")
        next_refresh = src.index("next_refresh_token = create_refresh_token")
        commit = src.index("await session.commit()")
        response = src.index("return TokenResponse(")
        self.assertLess(claim, next_refresh)
        self.assertLess(next_refresh, commit)
        self.assertLess(commit, response)

    def test_logout_all_serializes_before_global_revocation(self):
        src = function_source("app/api/auth.py", "logout_all")
        lock = src.index("lock_user_auth_boundary(session, user.id)")
        revoke = src.index("revoke_all_auth_sessions(")
        epoch = src.index("bump_user_token_epoch(")
        self.assertLess(lock, revoke)
        self.assertLess(lock, epoch)

    def test_logout_all_commits_before_external_provider_call(self):
        src = function_source("app/api/auth.py", "logout_all")
        commit = src.index("await session.commit()")
        provider = src.index("admin_global_sign_out")
        self.assertLess(commit, provider)

    def test_password_reset_serializes_before_revocation_and_epoch(self):
        src = function_source("app/api/auth.py", "reset_password")
        lock = src.index("lock_user_auth_boundary(session, user.id)")
        revoke = src.index("revoke_all_auth_sessions(")
        epoch = src.index("bump_user_token_epoch(")
        self.assertLess(lock, revoke)
        self.assertLess(lock, epoch)

    def test_selected_session_revoke_stays_scoped(self):
        src = function_source("app/api/auth.py", "revoke_one_session")
        self.assertIn("revoke_auth_session(", src)
        self.assertNotIn("revoke_all_auth_sessions(", src)
        self.assertNotIn("bump_user_token_epoch(", src)

    def test_family_authority_not_added_to_local_session_claims(self):
        src = function_source("app/api/auth.py", "_issue_local_session_response")
        for forbidden in ("plan", "seat", "consent", "entitlement"):
            self.assertNotIn(f'"{forbidden}"', src)

    def test_phone_login_reuses_existing_local_session_issuer(self):
        src = function_source("app/api/phone_auth.py", "verify_phone_login")
        self.assertIn("_issue_local_session_response", src)

    def test_legacy_email_password_login_route_remains(self):
        src = text("app/api/auth.py")
        self.assertRegex(src, r'@router\.post\(\"/login\"[^\n]*\)')

    def test_provider_refresh_is_truthfully_legacy_nonrotating(self):
        src = function_source("app/api/auth.py", "refresh")
        self.assertIn("refresh_token=req.refresh_token", src)
        self.assertIn('auth_provider="cognito"', src)

    def test_session_positive_cache_remains_bounded(self):
        src = text("app/services/auth_session_service.py")
        self.assertIn("AUTH_SESSION_ACTIVE_CACHE_TTL_S = 2", src)
        self.assertIn("AUTH_SESSION_REVOKED_CACHE_TTL_S = 2 * 60 * 60", src)

    def test_no_new_7c3_migration_expected(self):
        names = [p.name for p in (ROOT / "migrations/versions").glob("*auth*.py")]
        self.assertIn("auth05_security_foundation.py", names)
        self.assertFalse(
            any(
                name.casefold().startswith("auth06")
                or "phase7c3" in name.casefold()
                or "phase_7c3" in name.casefold()
                for name in names
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
