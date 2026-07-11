"""
SB-01 Day 1 — Idempotent DDL for the safety-brain learning loop.

Path D: creates `safety_event_feedback`, the ground-truth feedback
table that captures guardian/user/operator verdicts on SafetyEvents.
This is the table Hermes will eventually compute false-positive rates
from (replacing the misuse of `behavior_anomalies.extended_inactivity`
flags as a stand-in).

Run idempotently from the backend startup path or via:

    python -m app.migrations.sb01_safety_event_feedback
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.db.session import async_session

logger = logging.getLogger(__name__)

# Pure DDL — idempotent, safe to run on every boot.
DDL = """
CREATE TABLE IF NOT EXISTS safety_event_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    safety_event_id UUID NOT NULL REFERENCES safety_events(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    verdict         VARCHAR(20) NOT NULL
                       CHECK (verdict IN ('confirmed', 'false_positive', 'unsure')),
    feedback_source VARCHAR(20) NOT NULL
                       CHECK (feedback_source IN ('guardian', 'user', 'operator')),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sef_safety_event_id
    ON safety_event_feedback(safety_event_id);

CREATE INDEX IF NOT EXISTS idx_sef_user_id_created
    ON safety_event_feedback(user_id, created_at DESC);

-- One verdict per (event, source) — re-submitting overwrites via the
-- API's ON CONFLICT clause, NOT silently appending duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sef_event_source
    ON safety_event_feedback(safety_event_id, feedback_source);
"""


async def ensure_safety_event_feedback_table() -> None:
    """Create the table + indexes if missing. Safe to call on every boot."""
    async with async_session() as session:
        # Split on semicolons so each statement runs in its own round-trip.
        for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
            await session.execute(text(stmt))
        await session.commit()
    logger.info("[SB-01] safety_event_feedback table ensured")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(ensure_safety_event_feedback_table())
