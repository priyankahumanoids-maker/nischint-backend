"""MED-01 - persistent Senior medicine schedules and dose adherence.

The mobile Medicine screen already uses /api/senior/medicine.  Older production
schemas only contain the legacy ``seniors`` dependent profile, so this runtime
migration creates user-account-backed medicine tables without modifying that
legacy table.

The migration is idempotent and safe to run on each application boot.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_medication_tables() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS medication_schedules (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    name VARCHAR(160) NOT NULL,
                    dosage VARCHAR(120) NOT NULL,
                    instructions TEXT NULL,
                    time_of_day VARCHAR(5) NOT NULL,
                    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
                    days_of_week JSONB NOT NULL DEFAULT '[0,1,2,3,4,5,6]'::jsonb,
                    starts_on DATE NOT NULL,
                    ends_on DATE NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_medication_schedules_user_active
                ON medication_schedules (user_id, is_active, starts_on)
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS medication_dose_events (
                    id UUID PRIMARY KEY,
                    schedule_id UUID NOT NULL REFERENCES medication_schedules(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    scheduled_for TIMESTAMPTZ NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    responded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    responded_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    notes TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_medication_dose_status
                        CHECK (status IN ('taken', 'missed', 'skipped')),
                    CONSTRAINT uq_medication_dose_schedule_time
                        UNIQUE (schedule_id, scheduled_for)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_medication_dose_user_time
                ON medication_dose_events (user_id, scheduled_for DESC)
                """
            )
        )
        await session.commit()

    logger.info("[MED-01] medication schedules + dose events schema ready")
