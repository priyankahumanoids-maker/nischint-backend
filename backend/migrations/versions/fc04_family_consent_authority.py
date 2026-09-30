"""FC-04: additive Phase 3 consent evidence and sharing state."""
from __future__ import annotations

from sqlalchemy import text

_DDL = """
CREATE TABLE IF NOT EXISTS family_consent_events (
    id UUID PRIMARY KEY,
    subject_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    purpose VARCHAR(40) NOT NULL,
    state VARCHAR(20) NOT NULL,
    notice_version VARCHAR(40) NOT NULL,
    language VARCHAR(8) NOT NULL,
    device_id VARCHAR(160) NULL,
    parental_basis VARCHAR(80) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_family_consent_event_purpose CHECK (purpose IN ('location','background_location','behavioral_ai','microphone','wearable')),
    CONSTRAINT ck_family_consent_event_state CHECK (state IN ('granted','withdrawn'))
);
CREATE INDEX IF NOT EXISTS ix_family_consent_events_subject_purpose_created
ON family_consent_events(subject_user_id, purpose, created_at DESC);

CREATE TABLE IF NOT EXISTS family_sharing_states (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    pause_mode VARCHAR(16) NULL,
    paused_until TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_family_sharing_pause_mode CHECK (pause_mode IS NULL OR pause_mode IN ('1h','8h','manual'))
);
"""

async def ensure_family_phase3_consent_schema() -> None:
    from app.db.session import async_session
    async with async_session() as session:
        for statement in [x.strip() for x in _DDL.split(';') if x.strip()]:
            await session.execute(text(statement))
        await session.commit()
