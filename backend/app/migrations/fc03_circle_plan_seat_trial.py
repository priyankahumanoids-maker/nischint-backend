"""FC-03 - Family Circle plan, seat and 7-day trial authority.

Adds only Family Circle v1.0 columns/table/indexes.  Legacy guardian,
relationship and existing subscription tables are intentionally untouched.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_circle_plan_seat_trial_schema() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(text("ALTER TABLE family_circles ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NULL"))
        await session.execute(text("ALTER TABLE family_circles ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ NULL"))
        await session.execute(text("ALTER TABLE family_circles ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ NULL"))
        await session.execute(text("ALTER TABLE circle_memberships ADD COLUMN IF NOT EXISTS seat VARCHAR(20) NULL"))

        await session.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'ck_family_circles_plan'
                    ) THEN
                        ALTER TABLE family_circles
                        ADD CONSTRAINT ck_family_circles_plan
                        CHECK (plan IS NULL OR plan IN ('trial', 'individual', 'family'));
                    END IF;
                END
                $$;
                """
            )
        )
        await session.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'ck_circle_memberships_seat'
                    ) THEN
                        ALTER TABLE circle_memberships
                        ADD CONSTRAINT ck_circle_memberships_seat
                        CHECK (seat IS NULL OR seat IN ('protected', 'guardian', 'member'));
                    END IF;
                END
                $$;
                """
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS family_trial_claims (
                    id UUID PRIMARY KEY,
                    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE CASCADE,
                    phone_fingerprint VARCHAR(64) NOT NULL,
                    device_fingerprint VARCHAR(64) NOT NULL,
                    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_family_trial_claims_circle_id "
                "ON family_trial_claims(circle_id)"
            )
        )
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_family_trial_claim_phone "
                "ON family_trial_claims(phone_fingerprint)"
            )
        )
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_family_trial_claim_device "
                "ON family_trial_claims(device_fingerprint)"
            )
        )
        await session.commit()

    logger.info("[FC-03] Family Circle plan/seat/trial schema ready")


if __name__ == "__main__":
    asyncio.run(ensure_circle_plan_seat_trial_schema())
