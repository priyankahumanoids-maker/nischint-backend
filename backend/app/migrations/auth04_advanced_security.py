"""AUTH-04 - durable sessions, token epochs, and OTP verification state.

Idempotent startup DDL.  This migration does not delete, disable, or modify any
existing user account or family relationship.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_auth_advanced_security_tables() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    provider VARCHAR(32) NOT NULL DEFAULT 'local',
                    device_label VARCHAR(255),
                    user_agent VARCHAR(512),
                    ip_hash VARCHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    revoked_reason VARCHAR(80)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_active
                ON auth_sessions (user_id, revoked_at, expires_at)
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_auth_sessions_expires
                ON auth_sessions (expires_at)
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_user_token_epochs (
                    user_id UUID PRIMARY KEY
                        REFERENCES users(id) ON DELETE CASCADE,
                    tokens_valid_after TIMESTAMPTZ NOT NULL
                )
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_otps (
                    email_hash VARCHAR(64) NOT NULL,
                    purpose VARCHAR(40) NOT NULL,
                    code_digest VARCHAR(64) NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at TIMESTAMPTZ NOT NULL,
                    resend_available_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (email_hash, purpose),
                    CONSTRAINT ck_auth_otps_attempts CHECK (attempts >= 0)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_auth_otps_expires
                ON auth_otps (expires_at)
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_email_verifications (
                    user_id UUID PRIMARY KEY
                        REFERENCES users(id) ON DELETE CASCADE,
                    email_hash VARCHAR(64) NOT NULL,
                    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    source VARCHAR(40) NOT NULL DEFAULT 'otp'
                )
                """
            )
        )

        # Security bookkeeping only; bounded cleanup is safe and does not touch
        # user accounts or application data.
        await session.execute(
            text(
                """
                DELETE FROM auth_sessions
                WHERE expires_at <= NOW() - INTERVAL '7 days'
                """
            )
        )
        await session.execute(
            text(
                """
                DELETE FROM auth_otps
                WHERE expires_at <= NOW()
                """
            )
        )

        await session.commit()

    logger.info(
        "[AUTH-04] sessions + token epochs + OTP verification schema ready"
    )
