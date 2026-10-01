"""Durable Family Circle notification outbox.

Lifecycle state commits first. Push transport is attempted afterwards and a
failed/no-token delivery remains pending for a later retry instead of rolling
back privacy/membership state or being silently lost.
"""
from __future__ import annotations

import json
import uuid
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue_family_notifications(
    session: AsyncSession,
    *,
    circle_id,
    recipient_user_ids: Iterable,
    event_type: str,
    title: str,
    body: str,
    payload: dict | None = None,
    event_key_prefix: str | None = None,
) -> list[str]:
    ids: list[str] = []
    for recipient in recipient_user_ids:
        recipient_id = str(recipient)
        event_key = f"{event_key_prefix}:{recipient_id}" if event_key_prefix else None
        outbox_id = uuid.uuid4()
        result = await session.execute(
            text(
                """
                INSERT INTO family_notification_outbox
                    (id, circle_id, recipient_user_id, event_key, event_type,
                     title, body, payload_json, created_at)
                VALUES
                    (:id, :circle_id, :recipient_user_id, :event_key, :event_type,
                     :title, :body, CAST(:payload AS JSONB), NOW())
                ON CONFLICT (event_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": outbox_id,
                "circle_id": circle_id,
                "recipient_user_id": recipient_id,
                "event_key": event_key,
                "event_type": str(event_type),
                "title": str(title)[:160],
                "body": str(body)[:500],
                "payload": json.dumps(payload or {}, separators=(",", ":"), sort_keys=True),
            },
        )
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            ids.append(str(inserted))
        elif event_key:
            existing = (
                await session.execute(
                    text("SELECT id FROM family_notification_outbox WHERE event_key=:event_key"),
                    {"event_key": event_key},
                )
            ).scalar_one_or_none()
            if existing is not None:
                ids.append(str(existing))
    return ids


async def deliver_outbox_notifications(session: AsyncSession, *, outbox_ids: Iterable[str]) -> dict:
    ids = [str(x) for x in outbox_ids if x]
    if not ids:
        return {"delivered": 0, "pending": 0}
    delivered = 0
    pending = 0
    from app.services.push_service import get_users_push_tokens, send_push_to_tokens

    for outbox_id in ids:
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, recipient_user_id, event_type, title, body, payload_json,
                           delivered_at, attempts
                      FROM family_notification_outbox
                     WHERE id=:id
                     FOR UPDATE
                    """
                ),
                {"id": outbox_id},
            )
        ).mappings().first()
        if not row or row["delivered_at"] is not None:
            continue
        recipient = row["recipient_user_id"]
        if recipient is None:
            await session.execute(
                text("UPDATE family_notification_outbox SET attempts=attempts+1, last_error='recipient_deleted' WHERE id=:id"),
                {"id": outbox_id},
            )
            pending += 1
            continue
        try:
            recipient_uuid = uuid.UUID(str(recipient))
            tokens = await get_users_push_tokens(session, [recipient_uuid])
            if not tokens:
                await session.execute(
                    text("UPDATE family_notification_outbox SET attempts=attempts+1, last_error='no_push_token' WHERE id=:id"),
                    {"id": outbox_id},
                )
                pending += 1
                continue
            payload = row["payload_json"] if isinstance(row["payload_json"], dict) else {}
            data = {"type": str(row["event_type"]), **payload}
            await send_push_to_tokens(tokens, str(row["title"]), str(row["body"]), data=data)
            await session.execute(
                text("UPDATE family_notification_outbox SET delivered_at=NOW(), attempts=attempts+1, last_error=NULL WHERE id=:id"),
                {"id": outbox_id},
            )
            delivered += 1
        except Exception as exc:
            await session.execute(
                text("UPDATE family_notification_outbox SET attempts=attempts+1, last_error=:error WHERE id=:id"),
                {"id": outbox_id, "error": str(exc)[:300]},
            )
            pending += 1
    return {"delivered": delivered, "pending": pending}


async def pending_notifications_for_user(session: AsyncSession, *, user_id, limit: int = 50) -> list[str]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id FROM family_notification_outbox
                 WHERE recipient_user_id=:uid AND delivered_at IS NULL
                 ORDER BY created_at ASC LIMIT :limit
                """
            ),
            {"uid": str(user_id), "limit": max(1, min(int(limit), 100))},
        )
    ).scalars().all()
    return [str(x) for x in rows]


__all__ = [
    "enqueue_family_notifications", "deliver_outbox_notifications",
    "pending_notifications_for_user",
]
