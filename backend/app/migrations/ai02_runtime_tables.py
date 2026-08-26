"""
AI-02 - Runtime safeguards for AI/risk tables.

Production currently does not execute the historical Alembic chain at
container startup. Several active services therefore depend on tables
whose canonical migrations were never applied to the live database.

This safeguard is idempotent and runs before background schedulers start.

Ensures:
    - device_digital_twins
    - location_risk_zones

It does not delete, truncate, rewrite, or replace existing data.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db.session import async_session

logger = logging.getLogger(__name__)


DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS device_digital_twins (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        twin_version INTEGER NOT NULL DEFAULT 1,
        wake_hour INTEGER,
        sleep_hour INTEGER,
        peak_activity_hour INTEGER,
        movement_interval_minutes DOUBLE PRECISION,
        typical_inactivity_max_minutes DOUBLE PRECISION,
        daily_rhythm JSONB NOT NULL DEFAULT '{}'::jsonb,
        activity_windows JSONB NOT NULL DEFAULT '[]'::jsonb,
        profile_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0,
        training_data_points INTEGER NOT NULL DEFAULT 0,
        last_trained_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_digital_twin_device UNIQUE (device_id)
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS ix_device_digital_twins_device_id
        ON device_digital_twins(device_id)
    """,

    """
    CREATE TABLE IF NOT EXISTS location_risk_zones (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        latitude DOUBLE PRECISION NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        geom geometry(Point, 4326),
        radius_meters DOUBLE PRECISION NOT NULL DEFAULT 500,
        risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
        risk_level VARCHAR(32) NOT NULL DEFAULT 'low',
        risk_type VARCHAR(64),
        factors JSONB NOT NULL DEFAULT '[]'::jsonb,
        zone_name VARCHAR(255),
        incident_count INTEGER NOT NULL DEFAULT 0,
        last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_location_risk_zones_risk_type
        ON location_risk_zones(risk_type)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_location_risk_zones_risk_score
        ON location_risk_zones(risk_score DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_location_risk_zones_updated
        ON location_risk_zones(last_updated DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_location_risk_zones_geom
        ON location_risk_zones USING GIST (geom)
    """,
]


async def ensure_ai_risk_runtime_tables() -> None:
    """Ensure required AI/risk tables exist without replacing existing data."""
    async with async_session() as session:
        try:
            for statement in DDL_STATEMENTS:
                await session.execute(text(statement))
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    logger.info(
        "[AI-02] runtime AI/risk schema ready "
        "(device_digital_twins, location_risk_zones)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ensure_ai_risk_runtime_tables())
