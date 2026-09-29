"""FC-02 - additive Family Circle + active membership authority.

Production currently relies on idempotent startup schema safeguards in addition
to the historical Alembic chain. This DDL creates only new tables/indexes and
never rewrites legacy guardian/relationship/subscription records.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def ensure_family_circle_authority_tables() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS family_circles (
                    id UUID PRIMARY KEY,
                    name VARCHAR(120) NULL,
                    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_family_circles_status
                        CHECK (status IN ('active', 'closed'))
                )
                """
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_family_circles_owner_user_id "
                "ON family_circles(owner_user_id)"
            )
        )

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS circle_memberships (
                    id UUID PRIMARY KEY,
                    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE CASCADE,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    created_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    ended_at TIMESTAMPTZ NULL,
                    CONSTRAINT ck_circle_memberships_role
                        CHECK (role IN ('owner', 'co_admin', 'adult_member', 'minor')),
                    CONSTRAINT ck_circle_memberships_status
                        CHECK (status IN ('active', 'left', 'removed'))
                )
                """
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_circle_memberships_circle_id "
                "ON circle_memberships(circle_id)"
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_circle_memberships_user_id "
                "ON circle_memberships(user_id)"
            )
        )

        # D6 — one active Circle per person.
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_circle_membership_one_active_circle_per_user "
                "ON circle_memberships(user_id) WHERE status = 'active'"
            )
        )
        # Exactly one active Owner maximum; creation service supplies the required owner.
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_circle_membership_one_active_owner "
                "ON circle_memberships(circle_id) "
                "WHERE status = 'active' AND role = 'owner'"
            )
        )
        # D10 default / T19 — max one active Co-Admin.
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_circle_membership_one_active_co_admin "
                "ON circle_memberships(circle_id) "
                "WHERE status = 'active' AND role = 'co_admin'"
            )
        )

        await session.commit()

    logger.info("[FC-02] Family Circle authority schema ready")


if __name__ == "__main__":
    asyncio.run(ensure_family_circle_authority_tables())
