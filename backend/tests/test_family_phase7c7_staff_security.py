from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from jose import jwt

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "app" / "api" / "admin.py"
RBAC = ROOT / "app" / "core" / "rbac.py"
SMS_2FA = ROOT / "app" / "services" / "auth_two_factor_service.py"
TOTP_FOUNDATION = ROOT / "app" / "services" / "auth_totp_foundation_service.py"
COGNITO = ROOT / "app" / "core" / "cognito.py"
STAFF_TOTP = ROOT / "app" / "services" / "auth_staff_totp_service.py"

PROTECTED_HASHES = {
    SMS_2FA: "4542ead8c462de0899955d7d7c74a2be87f48aa05d0e49124bb25b5c7fbba9e5",
    TOTP_FOUNDATION: "50964abe4e765f119f63a40721fc4fdbfd790f294d54c37df806e97462496a91",
    COGNITO: "2810f4a81b450ad3ff32b10d6e207c69124065db3e398684f251b8965dde1cfa",
}


def src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_protected_sms_foundation_and_cognito_unchanged():
    for path, expected in PROTECTED_HASHES.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"protected source drifted: {path}"


def test_staff_rbac_ignores_provider_staff_groups_and_refreshes_db_role():
    source = src(RBAC)
    assert 'STAFF_ROLES = frozenset({"admin", "operator"})' in source
    assert "provider_roles - STAFF_ROLES" in source
    assert "async def _current_db_role" in source
    assert "select(User.role, User.is_active).where(User.id == user.id)" in source
    assert "def require_staff_role" in source
    assert "require_totp: bool = True" in source
    assert 'request.headers.get("X-Nischint-Staff-Proof")' in source


def test_admin_boundary_requires_staff_totp_except_exact_bootstrap_routes():
    source = src(ADMIN)
    assert '_admin_role = require_staff_role(["admin"])' in source
    assert '_read_role = require_staff_role(["admin", "operator"])' in source
    assert 'require_totp=False' in source
    for route in (
        '/security/totp/status',
        '/security/totp/enroll',
        '/security/totp/activate',
        '/security/totp/proof',
    ):
        assert route in source
    assert '/security/totp/disable' not in source
    assert 'X-Nischint-Staff-Proof' in source


def test_role_change_revokes_sessions_and_bumps_epoch():
    source = src(ADMIN)
    start = source.index("async def update_user_role(")
    end = source.index('@router.put("/users/{user_id}/facility")', start)
    block = source[start:end]
    assert 'reason="admin_role_changed"' in block
    assert "revoke_all_auth_sessions" in block
    assert "bump_user_token_epoch" in block
    assert "user_cache.invalidate_user_keys" in block
    assert "DB role remains authoritative" in block


def test_staff_totp_service_uses_auth05_state_and_no_plaintext_fallback():
    source = src(STAFF_TOTP)
    assert "auth_two_factor_settings" in source
    assert "stage_totp_enrollment" in source
    assert "accept_verified_totp_step" in source
    assert "AESGCM" in source
    assert "No plaintext fallback" in source or "No plaintext fallback" in source
    assert "totp_ciphertext" in source
    assert "totp_key_id" in source
    assert "STAFF_PROOF_TTL_SECONDS = 5 * 60" in source


def test_rfc6238_six_digit_vector_and_adjacent_window():
    from app.services.auth_staff_totp_service import _matching_step, _totp_code

    secret = b"12345678901234567890"
    # RFC 6238 SHA1 vector at T=59 seconds gives 94287082 for 8 digits;
    # the corresponding 6-digit HOTP truncation is 287082.
    assert _totp_code(secret, 1) == "287082"
    now = datetime.fromtimestamp(59, tz=timezone.utc)
    assert _matching_step(secret, "287082", now) == 1


def test_authenticated_seed_encryption_roundtrip_and_aad_binding():
    from cryptography.exceptions import InvalidTag
    from app.services.auth_staff_totp_service import StaffTotpCipher

    cipher = StaffTotpCipher()
    secret = b"01234567890123456789"
    ciphertext, key_id = cipher.encrypt(secret, context=b"user-A")
    assert ciphertext != secret
    assert len(ciphertext) > len(secret)
    assert cipher.decrypt(ciphertext, context=b"user-A", key_id=key_id) == secret
    try:
        cipher.decrypt(ciphertext, context=b"user-B", key_id=key_id)
    except InvalidTag:
        pass
    else:
        raise AssertionError("TOTP ciphertext must be bound to the user context")


def test_staff_proof_is_short_lived_and_access_token_bound():
    from app.services.auth_staff_totp_service import create_staff_proof, verify_staff_proof

    uid = "11111111-1111-1111-1111-111111111111"
    now = datetime.now(timezone.utc)
    proof = create_staff_proof(user_id=uid, access_token="access-A", now=now)
    assert verify_staff_proof(proof, user_id=uid, access_token="access-A")
    assert not verify_staff_proof(proof, user_id=uid, access_token="access-B")
    assert not verify_staff_proof(
        proof,
        user_id="22222222-2222-2222-2222-222222222222",
        access_token="access-A",
    )

    old = create_staff_proof(
        user_id=uid,
        access_token="access-A",
        now=now - timedelta(minutes=10),
    )
    assert not verify_staff_proof(old, user_id=uid, access_token="access-A")


def test_stale_local_token_groups_cannot_create_staff_role():
    from app.core.config import settings
    from app.core.rbac import get_user_roles

    token = jwt.encode(
        {
            "type": "access",
            "sub": "11111111-1111-1111-1111-111111111111",
            "cognito:groups": ["admin", "operator"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    user = SimpleNamespace(role="guardian")
    roles = get_user_roles(user, token)
    assert "guardian" in roles
    assert "admin" not in roles
    assert "operator" not in roles
