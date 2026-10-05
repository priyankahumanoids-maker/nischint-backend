"""TOTP storage/replay foundation extending SMS settings; no authenticator API.

A later key-management adapter MUST provide authenticated encryption, binding
ciphertext to the supplied subject context. No plaintext fallback/default key.
Timestep acceptance is called only AFTER a verifier validates the TOTP MAC.
"""
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from app.core.auth_foundation_policy import aware, totp_step_allowed


class SecretCipher(Protocol):
    def encrypt(self, plaintext: bytes, *, context: bytes) -> tuple[bytes, str]:
        """Return authenticated ciphertext and a non-secret key-version ID."""


async def stage_totp_enrollment(session, *, user_id: UUID, secret: bytes,
                                cipher: SecretCipher, now: datetime) -> None:
    aware(now)
    if not isinstance(secret, bytes) or len(secret) < 20:
        raise ValueError("TOTP secret must provide at least 160 bits")
    ciphertext, key_id = cipher.encrypt(secret, context=f"nischint:totp:{user_id}".encode())
    if (not isinstance(ciphertext, bytes) or len(ciphertext) <= len(secret)
            or ciphertext == secret or not isinstance(key_id, str) or not 1 <= len(key_id) <= 160):
        raise ValueError("Authenticated ciphertext and key-version identifier required")
    # Do not alter SMS preferences or invoke the old lazy schema helper.
    await session.execute(text("""
        INSERT INTO auth_two_factor_settings (user_id) VALUES (:uid) ON CONFLICT (user_id) DO NOTHING
    """), {"uid": user_id})
    result = await session.execute(text("""
        UPDATE auth_two_factor_settings SET totp_state='pending',totp_ciphertext=:ciphertext,
            totp_key_id=:key_id,totp_enrolled_at=:now,totp_verified_at=NULL,
            totp_last_step=NULL,totp_disabled_at=NULL,updated_at=:now
        WHERE user_id=:uid AND totp_state='disabled' RETURNING user_id
    """), {"uid": user_id, "ciphertext": ciphertext, "key_id": key_id, "now": now})
    if result.scalar_one_or_none() is None:
        raise ValueError("Existing TOTP enrollment must be explicitly disabled before replacement")


async def accept_verified_totp_step(session, *, user_id: UUID, step: int, now: datetime) -> bool:
    if not totp_step_allowed(step, None, now):
        return False
    result = await session.execute(text("""
        UPDATE auth_two_factor_settings SET totp_state='enabled',totp_last_step=:step,
            totp_verified_at=:now,updated_at=:now
        WHERE user_id=:uid AND totp_state IN ('pending','enabled')
            AND totp_ciphertext IS NOT NULL AND totp_key_id IS NOT NULL
            AND (totp_last_step IS NULL OR totp_last_step<:step)
        RETURNING user_id
    """), {"uid": user_id, "step": step, "now": aware(now)})
    return result.scalar_one_or_none() is not None


async def disable_totp(session, *, user_id: UUID, now: datetime) -> bool:
    """Trusted future recovery/step-up caller only; SMS preferences preserved."""
    result = await session.execute(text("""
        UPDATE auth_two_factor_settings SET totp_state='disabled',totp_ciphertext=NULL,
            totp_key_id=NULL,totp_last_step=NULL,totp_verified_at=NULL,
            totp_disabled_at=:now,updated_at=:now WHERE user_id=:uid
        RETURNING user_id
    """), {"uid": user_id, "now": aware(now)})
    return result.scalar_one_or_none() is not None
