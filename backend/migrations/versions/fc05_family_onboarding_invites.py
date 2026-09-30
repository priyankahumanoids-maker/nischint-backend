"""FC-05 - canonical Family Circle onboarding invite authority (Phase 4)."""
from __future__ import annotations

from sqlalchemy import text

_DDL = """
CREATE TABLE IF NOT EXISTS family_circle_invites (
    id UUID PRIMARY KEY,
    circle_id UUID NOT NULL REFERENCES family_circles(id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    code_hash VARCHAR(64) NOT NULL UNIQUE,
    seat VARCHAR(20) NOT NULL,
    invitee_kind VARCHAR(16) NOT NULL DEFAULT 'adult',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    parental_basis VARCHAR(80) NULL,
    parental_verification_ref VARCHAR(160) NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    accepted_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_family_circle_invites_seat
        CHECK (seat IN ('protected','guardian','member')),
    CONSTRAINT ck_family_circle_invites_kind
        CHECK (invitee_kind IN ('adult','minor')),
    CONSTRAINT ck_family_circle_invites_status
        CHECK (status IN ('pending','accepted','revoked','expired'))
);
CREATE INDEX IF NOT EXISTS ix_family_circle_invites_circle_status_seat
ON family_circle_invites(circle_id, status, seat);
CREATE INDEX IF NOT EXISTS ix_family_circle_invites_expiry
ON family_circle_invites(expires_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS family_legal_acceptances (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    terms_version VARCHAR(40) NOT NULL,
    privacy_version VARCHAR(40) NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_family_legal_acceptances_user_accepted
ON family_legal_acceptances(user_id, accepted_at DESC);
"""


async def ensure_family_phase4_invite_schema() -> None:
    from app.db.session import async_session

    async with async_session() as session:
        for statement in [part.strip() for part in _DDL.split(';') if part.strip()]:
            await session.execute(text(statement))
        await session.commit()
