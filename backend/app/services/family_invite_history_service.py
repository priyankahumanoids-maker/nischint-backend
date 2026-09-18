"""Durable Family Circle invite history.

This service is intentionally isolated from the existing short-lived invite-code
mechanism. It never stores the 6-character invite code. The active code remains
owned by the existing users active-invite field exactly as before; this table records only the
lifecycle metadata needed by Settings -> Family Circle -> Invite History.

The table is created idempotently on first use because the current Cloud Build
path deploys the image directly and does not run Alembic. History persistence is
best-effort from the existing invite endpoints so a history outage can never
break QR/invite generation, cancellation, validation, or member joining.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS family_invite_history (
    id UUID PRIMARY KEY,
    guardian_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ NULL,
    accepted_at TIMESTAMPTZ NULL,
    accepted_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    accepted_role VARCHAR(30) NULL
)
"""

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS ix_family_invite_history_guardian_created
ON family_invite_history (guardian_user_id, created_at DESC)
"""


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value is not None else None)


async def ensure_table(session: AsyncSession) -> None:
    await session.execute(text(_TABLE_SQL))
    await session.execute(text(_INDEX_SQL))


async def record_generated(
    session: AsyncSession,
    *,
    guardian_user_id,
    expires_at,
) -> None:
    """Record a newly generated invite without storing its code."""
    await ensure_table(session)
    now = datetime.now(timezone.utc)

    # There can only be one active short code on the users active-invite field. If a new
    # one is generated, any previous unresolved history row is either already
    # expired or was replaced by this explicit generation action.
    await session.execute(
        text(
            """
            UPDATE family_invite_history
            SET status = CASE
                    WHEN expires_at <= :now THEN 'expired'
                    ELSE 'superseded'
                END,
                resolved_at = :now
            WHERE guardian_user_id = :guardian_user_id
              AND status = 'pending'
            """
        ),
        {"guardian_user_id": guardian_user_id, "now": now},
    )

    await session.execute(
        text(
            """
            INSERT INTO family_invite_history (
                id, guardian_user_id, status, created_at, expires_at
            ) VALUES (
                :id, :guardian_user_id, 'pending', :created_at, :expires_at
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "guardian_user_id": guardian_user_id,
            "created_at": now,
            "expires_at": expires_at,
        },
    )


async def resolve_latest(
    session: AsyncSession,
    *,
    guardian_user_id,
    status: str,
    accepted_by_user_id=None,
    accepted_role: str | None = None,
) -> None:
    """Resolve the guardian's latest still-pending invite history row."""
    if status not in {"accepted", "revoked", "expired", "superseded"}:
        raise ValueError(f"Unsupported family invite history status: {status}")

    await ensure_table(session)
    now = datetime.now(timezone.utc)

    await session.execute(
        text(
            """
            UPDATE family_invite_history
            SET status = :status,
                resolved_at = :now,
                accepted_at = CASE
                    WHEN :status = 'accepted' THEN :now
                    ELSE accepted_at
                END,
                accepted_by_user_id = CASE
                    WHEN :status = 'accepted' THEN :accepted_by_user_id
                    ELSE accepted_by_user_id
                END,
                accepted_role = CASE
                    WHEN :status = 'accepted' THEN :accepted_role
                    ELSE accepted_role
                END
            WHERE id = (
                SELECT id
                FROM family_invite_history
                WHERE guardian_user_id = :guardian_user_id
                  AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
            )
            """
        ),
        {
            "guardian_user_id": guardian_user_id,
            "status": status,
            "now": now,
            "accepted_by_user_id": accepted_by_user_id,
            "accepted_role": accepted_role,
        },
    )


async def list_for_guardian(
    session: AsyncSession,
    *,
    guardian_user_id,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return newest-first invite history for one guardian."""
    await ensure_table(session)
    now = datetime.now(timezone.utc)
    capped = max(1, min(int(limit or 20), 50))

    rows = (
        await session.execute(
            text(
                """
                SELECT
                    h.id,
                    CASE
                        WHEN h.status = 'pending' AND h.expires_at <= :now
                            THEN 'expired'
                        ELSE h.status
                    END AS effective_status,
                    h.created_at,
                    h.expires_at,
                    h.resolved_at,
                    h.accepted_at,
                    h.accepted_by_user_id,
                    h.accepted_role,
                    accepted.full_name AS accepted_name,
                    accepted.email AS accepted_email
                FROM family_invite_history h
                LEFT JOIN users accepted ON accepted.id = h.accepted_by_user_id
                WHERE h.guardian_user_id = :guardian_user_id
                ORDER BY h.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "guardian_user_id": guardian_user_id,
                "now": now,
                "limit": capped,
            },
        )
    ).mappings().all()

    return [
        {
            "id": str(row["id"]),
            "status": str(row["effective_status"]),
            "created_at": _iso(row["created_at"]),
            "expires_at": _iso(row["expires_at"]),
            "resolved_at": _iso(row["resolved_at"]),
            "accepted_at": _iso(row["accepted_at"]),
            "accepted_by_user_id": (
                str(row["accepted_by_user_id"])
                if row["accepted_by_user_id"] is not None
                else None
            ),
            "accepted_role": row["accepted_role"],
            "accepted_name": row["accepted_name"],
            "accepted_email": row["accepted_email"],
        }
        for row in rows
    ]
