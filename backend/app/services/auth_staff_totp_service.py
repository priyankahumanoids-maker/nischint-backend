"""Staff authenticator-TOTP service for NISCHINT Phase 7C-7.

Design goals:
- Reuse AUTH05 `auth_two_factor_settings` TOTP columns; no schema change.
- Preserve ordinary-user SMS 2FA completely unchanged.
- Encrypt TOTP seed material at rest with authenticated encryption.
- Reject replayed TOTP timesteps using the AUTH05 durable `totp_last_step`.
- Issue a short-lived staff proof bound to the current bearer access token.

This module does not grant staff authority. Current least-privilege authority is
resolved independently by `app.core.rbac` from the live users.role value.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_foundation_policy import aware
from app.core.config import settings
from app.services.auth_totp_foundation_service import (
    accept_verified_totp_step,
    disable_totp,
    stage_totp_enrollment,
)

STAFF_ROLES = frozenset({"admin", "operator"})
STAFF_PROOF_TYPE = "staff_totp_proof"
STAFF_PROOF_TTL_SECONDS = 5 * 60
TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_ISSUER = "NISCHINT"
_KEY_ID = "jwt-root-aesgcm-v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _b32encode(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _b32decode(value: str) -> bytes:
    cleaned = "".join(str(value or "").strip().upper().split())
    padding = "=" * ((8 - (len(cleaned) % 8)) % 8)
    return base64.b32decode(cleaned + padding, casefold=True)


def _derive_encryption_key() -> bytes:
    root = str(settings.jwt_secret or "").encode("utf-8")
    if len(root) < 16:
        raise RuntimeError("JWT root secret is too weak for staff TOTP seed protection")
    # Domain-separated key derivation from the already-required server secret.
    # No plaintext fallback is ever permitted.
    return hmac.new(root, b"nischint:staff-totp:aesgcm:v1", hashlib.sha256).digest()


class StaffTotpCipher:
    """Authenticated encryption adapter used by AUTH05 TOTP storage."""

    def encrypt(self, plaintext: bytes, *, context: bytes) -> tuple[bytes, str]:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except Exception as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("Authenticated encryption support unavailable") from exc
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(_derive_encryption_key()).encrypt(nonce, plaintext, context)
        return nonce + ciphertext, _KEY_ID

    def decrypt(self, ciphertext: bytes, *, context: bytes, key_id: str) -> bytes:
        if str(key_id or "") != _KEY_ID:
            raise RuntimeError("Unsupported staff TOTP key version")
        if not isinstance(ciphertext, (bytes, bytearray)) or len(ciphertext) < 29:
            raise RuntimeError("Invalid staff TOTP ciphertext")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except Exception as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("Authenticated encryption support unavailable") from exc
        raw = bytes(ciphertext)
        return AESGCM(_derive_encryption_key()).decrypt(raw[:12], raw[12:], context)


def _context(user_id: Any) -> bytes:
    return f"nischint:totp:{user_id}".encode("utf-8")


def _totp_code(secret: bytes, step: int) -> str:
    if not isinstance(step, int) or step < 0:
        raise ValueError("Invalid TOTP step")
    msg = struct.pack(">Q", step)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _matching_step(secret: bytes, code: str, now: datetime) -> int | None:
    candidate = str(code or "").strip()
    if len(candidate) != TOTP_DIGITS or not candidate.isdigit():
        return None
    current = int(aware(now).timestamp()) // TOTP_PERIOD_SECONDS
    # Prefer current step, then adjacent allowed clock-skew windows.
    for step in (current, current - 1, current + 1):
        if step < 0:
            continue
        if hmac.compare_digest(_totp_code(secret, step), candidate):
            return step
    return None


def _access_token_hash(access_token: str) -> str:
    return hashlib.sha256(str(access_token or "").encode("utf-8")).hexdigest()


def _proof_payload(*, user_id: Any, access_token: str, now: datetime) -> dict[str, Any]:
    now = aware(now)
    return {
        "type": STAFF_PROOF_TYPE,
        "sub": str(user_id),
        "ath": _access_token_hash(access_token),
        "iat": int(now.timestamp()),
        "exp": now + timedelta(seconds=STAFF_PROOF_TTL_SECONDS),
    }


def create_staff_proof(*, user_id: Any, access_token: str, now: datetime | None = None) -> str:
    payload = _proof_payload(user_id=user_id, access_token=access_token, now=now or _utcnow())
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_staff_proof(
    proof: str,
    *,
    user_id: Any,
    access_token: str,
) -> bool:
    try:
        payload = jwt.decode(
            str(proof or ""),
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return False
    return (
        payload.get("type") == STAFF_PROOF_TYPE
        and str(payload.get("sub") or "") == str(user_id)
        and hmac.compare_digest(
            str(payload.get("ath") or ""),
            _access_token_hash(access_token),
        )
    )


async def get_staff_totp_state(session: AsyncSession, *, user_id: Any) -> dict[str, Any]:
    result = await session.execute(
        text(
            """
            SELECT totp_state, totp_enrolled_at, totp_verified_at, totp_disabled_at
            FROM auth_two_factor_settings
            WHERE user_id = CAST(:uid AS UUID)
            """
        ),
        {"uid": str(user_id)},
    )
    row = result.mappings().first()
    state = str(row["totp_state"] if row else "disabled")
    return {
        "state": state,
        "enabled": state == "enabled",
        "pending": state == "pending",
        "enrolled_at": row["totp_enrolled_at"] if row else None,
        "verified_at": row["totp_verified_at"] if row else None,
        "disabled_at": row["totp_disabled_at"] if row else None,
    }


async def _load_secret(session: AsyncSession, *, user_id: Any) -> tuple[bytes, str]:
    result = await session.execute(
        text(
            """
            SELECT totp_state, totp_ciphertext, totp_key_id
            FROM auth_two_factor_settings
            WHERE user_id = CAST(:uid AS UUID)
            """
        ),
        {"uid": str(user_id)},
    )
    row = result.mappings().first()
    if not row or row["totp_state"] not in {"pending", "enabled"}:
        raise ValueError("Authenticator TOTP is not enrolled")
    ciphertext = row["totp_ciphertext"]
    key_id = str(row["totp_key_id"] or "")
    if ciphertext is None or not key_id:
        raise RuntimeError("Authenticator TOTP seed is unavailable")
    secret = StaffTotpCipher().decrypt(
        bytes(ciphertext),
        context=_context(user_id),
        key_id=key_id,
    )
    if len(secret) < 20:
        raise RuntimeError("Authenticator TOTP seed is invalid")
    return secret, str(row["totp_state"])


async def begin_staff_totp_enrollment(
    session: AsyncSession,
    *,
    user_id: Any,
    account_label: str,
    now: datetime | None = None,
) -> dict[str, str]:
    now = aware(now or _utcnow())
    state = await get_staff_totp_state(session, user_id=user_id)
    if state["enabled"]:
        raise ValueError("Authenticator TOTP is already enabled")
    if state["pending"]:
        # Pending enrollment is not an active factor. Allow a fresh QR/manual
        # secret to be issued without creating a permanent recovery bypass.
        await disable_totp(session, user_id=user_id, now=now)

    secret = secrets.token_bytes(20)
    await stage_totp_enrollment(
        session,
        user_id=user_id,
        secret=secret,
        cipher=StaffTotpCipher(),
        now=now,
    )
    encoded = _b32encode(secret)
    label = quote(f"{TOTP_ISSUER}:{str(account_label or user_id).strip()}")
    issuer = quote(TOTP_ISSUER)
    uri = (
        f"otpauth://totp/{label}?secret={encoded}&issuer={issuer}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD_SECONDS}"
    )
    return {"secret": encoded, "otpauth_uri": uri}


async def verify_staff_totp_code(
    session: AsyncSession,
    *,
    user_id: Any,
    code: str,
    now: datetime | None = None,
) -> bool:
    now = aware(now or _utcnow())
    secret, _state = await _load_secret(session, user_id=user_id)
    step = _matching_step(secret, code, now)
    if step is None:
        return False
    return await accept_verified_totp_step(
        session,
        user_id=user_id,
        step=step,
        now=now,
    )


async def verify_staff_totp_and_issue_proof(
    session: AsyncSession,
    *,
    user_id: Any,
    code: str,
    access_token: str,
    now: datetime | None = None,
) -> str | None:
    now = aware(now or _utcnow())
    state = await get_staff_totp_state(session, user_id=user_id)
    if not state["enabled"]:
        return None
    if not await verify_staff_totp_code(
        session,
        user_id=user_id,
        code=code,
        now=now,
    ):
        return None
    return create_staff_proof(user_id=user_id, access_token=access_token, now=now)


__all__ = [
    "STAFF_PROOF_TTL_SECONDS",
    "STAFF_ROLES",
    "StaffTotpCipher",
    "begin_staff_totp_enrollment",
    "create_staff_proof",
    "get_staff_totp_state",
    "verify_staff_proof",
    "verify_staff_totp_and_issue_proof",
    "verify_staff_totp_code",
]
