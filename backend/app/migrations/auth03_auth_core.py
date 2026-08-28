"""AUTH-03 - durable local authentication security state.

Production currently relies on application-startup schema safeguards rather
than the historical Alembic chain.

This migration creates durable PostgreSQL state for:

* single-use local refresh-token rotation;
* local password-reset codes.

It is idempotent and safe to run on every application boot.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_auth_core_tables() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_refresh_consumptions (
                    token_id VARCHAR(64) PRIMARY KEY,
                    user_id UUID NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                    ix_auth_refresh_consumptions_expires
                ON auth_refresh_consumptions (expires_at)
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                    ix_auth_refresh_consumptions_user
                ON auth_refresh_consumptions (user_id)
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_password_resets (
                    email_hash VARCHAR(64) PRIMARY KEY,
                    code_digest VARCHAR(64) NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_auth_password_resets_attempts
                        CHECK (attempts >= 0)
                )
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                    ix_auth_password_resets_expires
                ON auth_password_resets (expires_at)
                """
            )
        )

        # Bounded cleanup. These rows are security bookkeeping only and no
        # longer serve a purpose after their credential lifetime ends.
        await session.execute(
            text(
                """
                DELETE FROM auth_refresh_consumptions
                WHERE expires_at <= NOW()
                """
            )
        )

        await session.execute(
            text(
                """
                DELETE FROM auth_password_resets
                WHERE expires_at <= NOW()
                """
            )
        )

        await session.commit()

    logger.info(
        "[AUTH-03] refresh-consumption + password-reset schema ready"
    )
