"""Idempotent staging/runtime safeguard for persisted profile photos."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_user_profile_photo_column() -> None:
    """Add the nullable column when a deployment has not run Alembic yet."""
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS profile_photo_data TEXT"
            )
        )
        await session.commit()
    logger.info("[PF-01] users.profile_photo_data schema ready")
