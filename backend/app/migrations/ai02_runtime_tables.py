"""
AI-02 - Idempotent runtime bootstrap for active AI/risk schema.

Production does not currently execute the historical Alembic chain.
This safeguard creates only schema whose contract is known and actively
required by deployed services.

Each schema group uses an independent transaction. A failure in one
group cannot roll back schema successfully created by another group.

Ensures:
    - device_digital_twins
    - predictive_risks
    - PostGIS extension
    - location_risk_zones

The migration never drops, truncates, deletes, or replaces existing data.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db.session import async_session

logger = logging.getLogger(__name__)


DEVICE_DIGITAL_TWINS_DDL = [
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
]


PREDICTIVE_RISKS_DDL = [
    """
    CREATE TABLE IF NOT EXISTS predictive_risks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        prediction_type VARCHAR(64) NOT NULL,
        prediction_score DOUBLE PRECISION NOT NULL,
        prediction_window_hours INTEGER NOT NULL DEFAULT 48,
        confidence DOUBLE PRECISION NOT NULL,
        explanation TEXT NOT NULL,
        feature_vector JSONB NOT NULL DEFAULT '{}'::jsonb,
        trend_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_predictive_risks_device_id
        ON predictive_risks(device_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_predictive_risks_active_created
        ON predictive_risks(is_active, created_at DESC)
    """,
]


POSTGIS_DDL = [
    """
    CREATE EXTENSION IF NOT EXISTS postgis
    """,
]


LOCATION_RISK_ZONES_DDL = [
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
        ON location_risk_zones
        USING GIST (geom)
    """,
]


async def _run_schema_group(name: str, statements: list[str]) -> bool:
    """
    Execute and commit one independent schema group.

    Failure rolls back only this group, never previously completed groups.
    """
    async with async_session() as session:
        try:
            for statement in statements:
                await session.execute(text(statement))

            await session.commit()

            logger.info("[AI-02] schema group ready: %s", name)
            return True

        except Exception:
            await session.rollback()
            logger.exception("[AI-02] schema group failed: %s", name)
            return False


async def ensure_ai_risk_runtime_tables() -> None:
    """
    Ensure known active AI/risk schema exists.

    Groups deliberately run independently so optional spatial support
    cannot roll back non-spatial AI tables.
    """
    results: dict[str, bool] = {}

    # Non-spatial tables first. They must not depend on PostGIS.
    results["device_digital_twins"] = await _run_schema_group(
        "device_digital_twins",
        DEVICE_DIGITAL_TWINS_DDL,
    )

    results["predictive_risks"] = await _run_schema_group(
        "predictive_risks",
        PREDICTIVE_RISKS_DDL,
    )

    # Neon reports PostGIS 3.3.3 as available but currently uninstalled.
    results["postgis"] = await _run_schema_group(
        "postgis",
        POSTGIS_DDL,
    )

    # Only attempt spatial risk table creation when PostGIS succeeded.
    if results["postgis"]:
        results["location_risk_zones"] = await _run_schema_group(
            "location_risk_zones",
            LOCATION_RISK_ZONES_DDL,
        )
    else:
        results["location_risk_zones"] = False
        logger.error(
            "[AI-02] location_risk_zones skipped because PostGIS is unavailable"
        )

    failed = [name for name, ok in results.items() if not ok]

    if failed:
        raise RuntimeError(
            "AI-02 runtime schema incomplete: " + ", ".join(failed)
        )

    logger.info(
        "[AI-02] runtime AI/risk schema ready: "
        "device_digital_twins, predictive_risks, "
        "postgis, location_risk_zones"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ensure_ai_risk_runtime_tables())
