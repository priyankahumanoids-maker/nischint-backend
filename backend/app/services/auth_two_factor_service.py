"""SMS-only two-factor authentication foundation for NISCHINT.

This module is intentionally additive. Existing password/session flows remain the
source of truth until an account explicitly enables SMS 2FA. The preference is
stored separately from the users table and is bound to the verified phone hash.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

TWO_FACTOR_METHOD = "sms"
TWO_FACTOR_LOGIN_PURPOSE = "two_factor_login"
TWO_FACTOR_ENABLE_PURPOSE = "two_factor_enable"
TWO_FACTOR_DISABLE_PURPOSE = "two_factor_disable"
TWO_FACTOR_CHALLENGE_TTL_SECONDS = 10 * 60

_schema_ready = False
_schema_lock = asyncio.Lock()


def normalize_phone(phone: str | None) -> str:
    raw = str(phone or "").strip()
    if not raw.startswith("+"):
        return ""
    digits = raw[1:]
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        return ""
    return f"+{digits}"


def phone_hash(phone: str | None) -> str:
    normalized = normalize_phone(phone)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mask_phone(phone: str | None) -> str:
    normalized = normalize_phone(phone)
    if not normalized:
        return ""
    digits = normalized[1:]
    visible = digits[-4:]
    country = digits[: max(0, len(digits) - 10)]
    prefix = f"+{country}" if country else "+"
    hidden_count = max(2, len(digits) - len(country) - len(visible))
    return f"{prefix}{'•' * hidden_count}{visible}"


async def ensure_two_factor_schema() -> None:
    """Create the isolated 2FA settings table only when 2FA is first configured.

    Normal sign-in does not depend on DDL. This preserves existing authentication
    availability before any account opts into 2FA.
    """
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        from app.db.session import async_session

        async with async_session() as schema_session:
            await schema_session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS auth_two_factor_settings (
                        user_id UUID PRIMARY KEY
                            REFERENCES users(id) ON DELETE CASCADE,
                        sms_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        phone_hash VARCHAR(64),
                        enabled_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            await schema_session.commit()
        _schema_ready = True


async def _table_exists(session: AsyncSession) -> bool:
    result = await session.execute(
        text("SELECT to_regclass('public.auth_two_factor_settings')")
    )
    return result.scalar_one_or_none() is not None


async def get_sms_two_factor_state(
    session: AsyncSession,
    *,
    user_id: Any,
    phone: str | None,
) -> dict[str, Any]:
    """Read 2FA state without creating schema or changing normal login behavior."""
    normalized = normalize_phone(phone)
    current_hash = phone_hash(normalized)
    if not await _table_exists(session):
        return {
            "configured": False,
            "enabled": False,
            "phone_matches": True,
            "phone_valid": bool(normalized),
            "masked_phone": mask_phone(normalized),
        }

    result = await session.execute(
        text(
            """
            SELECT sms_enabled, phone_hash
            FROM auth_two_factor_settings
            WHERE user_id = CAST(:user_id AS UUID)
            """
        ),
        {"user_id": str(user_id)},
    )
    row = result.mappings().first()
    configured = bool(row and row["sms_enabled"])
    stored_hash = str(row["phone_hash"] or "") if row else ""
    phone_matches = not configured or bool(current_hash and stored_hash == current_hash)
    return {
        "configured": configured,
        "enabled": configured and phone_matches,
        "phone_matches": phone_matches,
        "phone_valid": bool(normalized),
        "masked_phone": mask_phone(normalized),
    }


async def set_sms_two_factor_enabled(
    session: AsyncSession,
    *,
    user_id: Any,
    phone: str,
    enabled: bool,
) -> None:
    await ensure_two_factor_schema()
    normalized = normalize_phone(phone)
    if enabled and not normalized:
        raise ValueError("A valid E.164 mobile number is required for SMS 2FA")
    await session.execute(
        text(
            """
            INSERT INTO auth_two_factor_settings (
                user_id, sms_enabled, phone_hash, enabled_at, updated_at
            )
            VALUES (
                CAST(:user_id AS UUID),
                :enabled,
                :phone_hash,
                CASE WHEN :enabled THEN NOW() ELSE NULL END,
                NOW()
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                sms_enabled = EXCLUDED.sms_enabled,
                phone_hash = EXCLUDED.phone_hash,
                enabled_at = CASE
                    WHEN EXCLUDED.sms_enabled THEN COALESCE(
                        auth_two_factor_settings.enabled_at,
                        NOW()
                    )
                    ELSE NULL
                END,
                updated_at = NOW()
            """
        ),
        {
            "user_id": str(user_id),
            "enabled": bool(enabled),
            "phone_hash": phone_hash(normalized) if enabled else None,
        },
    )


def create_login_challenge(*, user_id: Any, email: str, provider: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "two_factor_challenge",
        "sub": str(user_id),
        "email": str(email or "").strip().casefold(),
        "provider": str(provider or "local")[:32],
        "iat": now.timestamp(),
        "exp": now + timedelta(seconds=TWO_FACTOR_CHALLENGE_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_login_challenge(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            str(token or ""),
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None
    if payload.get("type") != "two_factor_challenge":
        return None
    if not payload.get("sub") or not payload.get("email"):
        return None
    provider = str(payload.get("provider") or "local")
    if provider not in {"local", "cognito"}:
        return None
    return payload
