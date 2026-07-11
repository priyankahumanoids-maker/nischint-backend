"""NISCH-002B — User presence helper.

Tiny, single-purpose: write `User.last_known_lat / lng / at` for a
given user. Called from any location-bearing endpoint (journey ping,
guardian heartbeat, manual presence post). Safe to call concurrently —
SQL update is atomic per row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Union

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def update_last_known(
    session: AsyncSession,
    user_id: Union[str, uuid.UUID],
    lat: float,
    lng: float,
    *,
    ts: Optional[datetime] = None,
) -> None:
    """Update the user's last-known fix. Best-effort caller-safe.

    Caller is responsible for committing the surrounding transaction —
    we only `flush()` so SELECT/UPDATE ordering inside the same request
    is consistent. Production callers usually live inside a request that
    already commits at the end.
    """
    if not isinstance(user_id, uuid.UUID):
        user_id = uuid.UUID(str(user_id))
    if ts is None:
        ts = datetime.now(timezone.utc)
    elif ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            last_known_lat=float(lat),
            last_known_lng=float(lng),
            last_known_at=ts,
        )
    )
    await session.flush()


__all__ = ["update_last_known"]
