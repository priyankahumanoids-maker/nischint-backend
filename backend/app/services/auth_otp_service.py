"""AUTH-04 hashed OTP + email-verification foundation.

OTP enforcement is intentionally not wired into registration/login yet.  The
foundation is safe to deploy before a company-controlled email sender is
configured, and can be enabled after real inbox UAT.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

OTP_TTL_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
EMAIL_VERIFICATION_PURPOSE = "email_verification"


def normalize_email(email: str) -> str:
    return str(email or "").strip().casefold()


def email_hash(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def otp_digest(email: str, purpose: str, code: str) -> str:
    payload = (
        f"{normalize_email(email)}:{str(purpose or '').strip()}:{str(code or '').strip()}"
    ).encode("utf-8")
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


async def store_otp(
    session: AsyncSession,
    *,
    email: str,
    purpose: str,
    code: str,
) -> int:
    """Store one hashed OTP.

    Returns 0 when stored, otherwise the remaining resend-cooldown seconds.
    """
    ehash = email_hash(email)
    normalized_purpose = str(purpose or "").strip()[:40]

    current = await session.execute(
        text(
            """
            SELECT resend_available_at
            FROM auth_otps
            WHERE email_hash = :email_hash
              AND purpose = :purpose
            FOR UPDATE
            """
        ),
        {"email_hash": ehash, "purpose": normalized_purpose},
    )
    row = current.mappings().first()
    if row and row["resend_available_at"] is not None:
        now = datetime.now(timezone.utc)
        retry = int((row["resend_available_at"] - now).total_seconds())
        if retry > 0:
            return retry

    await session.execute(
        text(
            """
            INSERT INTO auth_otps (
                email_hash,
                purpose,
                code_digest,
                attempts,
                expires_at,
                resend_available_at,
                created_at
            )
            VALUES (
                :email_hash,
                :purpose,
                :code_digest,
                0,
                NOW() + (:ttl_seconds * INTERVAL '1 second'),
                NOW() + (:cooldown_seconds * INTERVAL '1 second'),
                NOW()
            )
            ON CONFLICT (email_hash, purpose)
            DO UPDATE SET
                code_digest = EXCLUDED.code_digest,
                attempts = 0,
                expires_at = EXCLUDED.expires_at,
                resend_available_at = EXCLUDED.resend_available_at,
                created_at = NOW()
            """
        ),
        {
            "email_hash": ehash,
            "purpose": normalized_purpose,
            "code_digest": otp_digest(email, normalized_purpose, code),
            "ttl_seconds": OTP_TTL_SECONDS,
            "cooldown_seconds": OTP_RESEND_COOLDOWN_SECONDS,
        },
    )
    return 0


async def consume_otp(
    session: AsyncSession,
    *,
    email: str,
    purpose: str,
    code: str,
) -> bool:
    ehash = email_hash(email)
    normalized_purpose = str(purpose or "").strip()[:40]

    await session.execute(
        text(
            """
            DELETE FROM auth_otps
            WHERE email_hash = :email_hash
              AND purpose = :purpose
              AND expires_at <= NOW()
            """
        ),
        {"email_hash": ehash, "purpose": normalized_purpose},
    )

    result = await session.execute(
        text(
            """
            SELECT code_digest, attempts
            FROM auth_otps
            WHERE email_hash = :email_hash
              AND purpose = :purpose
              AND expires_at > NOW()
            FOR UPDATE
            """
        ),
        {"email_hash": ehash, "purpose": normalized_purpose},
    )
    row = result.mappings().first()
    if not row:
        return False

    attempts = int(row["attempts"] or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        await session.execute(
            text(
                """
                DELETE FROM auth_otps
                WHERE email_hash = :email_hash
                  AND purpose = :purpose
                """
            ),
            {"email_hash": ehash, "purpose": normalized_purpose},
        )
        return False

    expected = str(row["code_digest"] or "")
    supplied = otp_digest(email, normalized_purpose, code)
    if not expected or not hmac.compare_digest(expected, supplied):
        attempts += 1
        if attempts >= OTP_MAX_ATTEMPTS:
            await session.execute(
                text(
                    """
                    DELETE FROM auth_otps
                    WHERE email_hash = :email_hash
                      AND purpose = :purpose
                    """
                ),
                {"email_hash": ehash, "purpose": normalized_purpose},
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE auth_otps
                    SET attempts = :attempts
                    WHERE email_hash = :email_hash
                      AND purpose = :purpose
                    """
                ),
                {
                    "attempts": attempts,
                    "email_hash": ehash,
                    "purpose": normalized_purpose,
                },
            )
        return False

    await session.execute(
        text(
            """
            DELETE FROM auth_otps
            WHERE email_hash = :email_hash
              AND purpose = :purpose
            """
        ),
        {"email_hash": ehash, "purpose": normalized_purpose},
    )
    return True


async def mark_email_verified(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
    source: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO auth_email_verifications (
                user_id,
                email_hash,
                verified_at,
                source
            )
            VALUES (
                CAST(:user_id AS UUID),
                :email_hash,
                NOW(),
                :source
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                email_hash = EXCLUDED.email_hash,
                verified_at = EXCLUDED.verified_at,
                source = EXCLUDED.source
            """
        ),
        {
            "user_id": str(user_id),
            "email_hash": email_hash(email),
            "source": str(source or "otp")[:40],
        },
    )


async def is_email_verified(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
) -> bool:
    result = await session.execute(
        text(
            """
            SELECT 1
            FROM auth_email_verifications
            WHERE user_id = CAST(:user_id AS UUID)
              AND email_hash = :email_hash
            LIMIT 1
            """
        ),
        {"user_id": str(user_id), "email_hash": email_hash(email)},
    )
    return result.scalar_one_or_none() is not None
