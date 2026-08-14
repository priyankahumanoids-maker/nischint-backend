"""Idempotent runtime safeguard for persisted safety-zone addresses."""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_safe_zone_address_column() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text("ALTER TABLE safe_zones ADD COLUMN IF NOT EXISTS address VARCHAR(300)")
        )
        await session.commit()
    logger.info("[GZ-02] safe_zones.address schema ready")
