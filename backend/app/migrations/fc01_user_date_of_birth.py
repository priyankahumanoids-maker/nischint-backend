"""FC-01 - Family Circle v1.0 date-of-birth identity foundation.

Production has historically used idempotent startup/pre-deploy schema safeguards in
addition to Alembic. This migration is safe to run repeatedly and leaves every
existing user intact by adding a nullable DATE column.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_user_date_of_birth_column() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS date_of_birth DATE"
            )
        )
        await session.commit()

    logger.info("[FC-01] users.date_of_birth schema ready")


if __name__ == "__main__":
    asyncio.run(ensure_user_date_of_birth_column())
